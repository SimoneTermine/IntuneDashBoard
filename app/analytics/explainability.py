"""
Explainability engine.
Given a device, determines which controls affect it, infers outcomes, 
and produces human-readable reason codes.

REASON CODES:
  TARGETING_MISS       - The control is not assigned to this device or its groups
  TARGETING_DIRECT     - Directly assigned (allDevices or device-specific)
  TARGETING_GROUP      - Assigned via group membership
  TARGETING_EXCLUDED   - Group assignment with exclude intent
  FILTER_EXCLUDED      - Assignment has a filter that may exclude this device
  GRAPH_DATA_MISSING   - Could not fetch enough data to determine
  CONFLICT_SETTING     - Two controls modify same category (heuristic)
  REQUIREMENT_NOT_MET  - Compliance rule not met based on known state
  STATUS_COMPLIANT     - Control reports compliant for this device
  STATUS_NONCOMPLIANT  - Control reports non-compliant for this device
  STATUS_ERROR         - Error state reported
  STATUS_UNKNOWN       - Status not determinable from local data
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, TypedDict

from sqlalchemy import and_

from app.db.database import session_scope
from app.db.models import (
    Device, Control, Assignment, Outcome,
    Group, DeviceGroupMembership, DeviceComplianceStatus,
    DeviceAppStatus, App,
)
from app.analytics.queries import (
    get_device_by_id, get_assignments_for_control,
    _device_to_dict, _control_to_dict,
)

logger = logging.getLogger(__name__)


@dataclass
class ExplainResult:
    control_id: str
    control_name: str
    control_type: str
    status: str
    reason_code: str
    reason_detail: str
    target_type: str = ""
    target_id: str = ""
    intent: str = "include"
    filter_id: Optional[str] = None
    source: str = "heuristic"


@dataclass
class ConflictHint:
    control_a_id: str
    control_a_name: str
    control_b_id: str
    control_b_name: str
    conflict_type: str  # same_category / overlapping_assignments
    detail: str


@dataclass
class DeviceExplanation:
    device_id: str
    device_name: str
    compliance_state: str
    results: list[ExplainResult] = field(default_factory=list)
    conflicts: list[ConflictHint] = field(default_factory=list)
    summary: str = ""
    data_completeness: str = "partial"  # full / partial / minimal


class ExplainabilityEngine:
    """
    Analyzes local data to explain device compliance/configuration state.
    
    This is a best-effort engine: it works from locally synced data.
    Some outcomes may be 'heuristic' when Graph doesn't expose full state.
    """

    def explain_device(self, device_id: str) -> DeviceExplanation:
        """
        Main entry point: explain why a device is in its current state.
        """
        device_data = get_device_by_id(device_id)
        if not device_data:
            raise ValueError(f"Device {device_id} not found in local DB")

        explanation = DeviceExplanation(
            device_id=device_id,
            device_name=device_data["device_name"],
            compliance_state=device_data["compliance_state"],
        )

        # Step 1: Determine which controls are assigned to this device
        candidate_controls = self._get_candidate_controls(device_id, device_data)

        # Step 2: For each control, determine outcome
        for ctrl_id, ctrl_data, assignment_info in candidate_controls:
            result = self._explain_control(device_id, device_data, ctrl_id, ctrl_data, assignment_info)
            explanation.results.append(result)

        # Step 3: Detect conflicts (heuristic)
        explanation.conflicts = self._detect_conflicts(explanation.results)

        # Step 4: Enrich with direct compliance policy status data
        self._enrich_with_compliance_status(device_id, explanation)

        # Step 5: Build summary
        explanation.summary = self._build_summary(explanation)
        explanation.data_completeness = self._assess_completeness(explanation)

        return explanation

    def _get_candidate_controls(
        self, device_id: str, device_data: dict
    ) -> list[tuple[str, dict, dict]]:
        """
        Return list of (ctrl_id, ctrl_data, assignment_info) for controls
        that may affect this device.
        
        Strategy:
        1. Controls with allDevices assignment → always apply
        2. Controls with group assignment where device has group membership
        3. Controls with allUsers assignment where device has a user
        """
        results = []

        with session_scope() as db:
            # Get device's group memberships from local cache
            memberships = db.query(DeviceGroupMembership.group_id).filter(
                DeviceGroupMembership.device_id == device_id
            ).all()
            device_group_ids = {row[0] for row in memberships}

            user_id = device_data.get("user_upn", "")
            has_user = bool(user_id)

            # Get all assignments and match
            from sqlalchemy.orm import joinedload
            assignments = db.query(Assignment).all()
            seen_controls = set()

            for asmt in assignments:
                ctrl_id = asmt.control_id
                match = False
                reason = ""

                if asmt.target_type == "allDevices":
                    match = True
                    reason = "allDevices"
                elif asmt.target_type == "allUsers" and has_user:
                    match = True
                    reason = "allUsers"
                elif asmt.target_type == "group" and asmt.target_id in device_group_ids:
                    match = True
                    reason = f"group:{asmt.target_id}"

                if match and ctrl_id not in seen_controls:
                    ctrl = db.get(Control, ctrl_id)
                    if ctrl:
                        from app.analytics.queries import _control_to_dict
                        results.append((
                            ctrl_id,
                            _control_to_dict(ctrl),
                            {
                                "target_type": asmt.target_type,
                                "target_id": asmt.target_id,
                                "intent": asmt.intent,
                                "filter_id": asmt.filter_id,
                                "filter_type": asmt.filter_type,
                                "match_reason": reason,
                            }
                        ))
                        seen_controls.add(ctrl_id)

        # If no group memberships synced, note data gap
        if not device_group_ids:
            logger.debug(f"No group memberships in local DB for device {device_id} — group-based targeting unknown")

        return results

    def _explain_control(
        self,
        device_id: str,
        device_data: dict,
        ctrl_id: str,
        ctrl_data: dict,
        assignment_info: dict,
    ) -> ExplainResult:
        intent = assignment_info.get("intent", "include")
        target_type = assignment_info.get("target_type", "")
        target_id = assignment_info.get("target_id", "")
        filter_id = assignment_info.get("filter_id")

        if intent == "exclude":
            return ExplainResult(
                control_id=ctrl_id,
                control_name=ctrl_data["display_name"],
                control_type=ctrl_data["control_type"],
                status="excluded",
                reason_code="TARGETING_EXCLUDED",
                reason_detail=f"Device is in an excluded group ({target_id}). This control does NOT apply.",
                target_type=target_type,
                target_id=target_id,
                intent="exclude",
                filter_id=filter_id,
                source="heuristic",
            )

        # Check for filter
        if filter_id:
            return ExplainResult(
                control_id=ctrl_id,
                control_name=ctrl_data["display_name"],
                control_type=ctrl_data["control_type"],
                status="filtered",
                reason_code="FILTER_EXCLUDED",
                reason_detail=(
                    f"Assignment has a filter (id={filter_id}). "
                    "Filter evaluation is not available in local data — outcome uncertain. "
                    "Check Intune portal for filter details."
                ),
                target_type=target_type,
                target_id=target_id,
                intent=intent,
                filter_id=filter_id,
                source="heuristic",
            )

        # Try to find a real outcome from Outcomes table
        real_outcome = self._get_stored_outcome(device_id, ctrl_id)
        if real_outcome:
            return ExplainResult(
                control_id=ctrl_id,
                control_name=ctrl_data["display_name"],
                control_type=ctrl_data["control_type"],
                status=(real_outcome.get("status") or "unknown"),
                reason_code=(real_outcome.get("reason_code") or "STATUS_UNKNOWN"),
                reason_detail=(real_outcome.get("reason_detail") or "Outcome from Graph data"),
                target_type=target_type,
                target_id=target_id,
                intent=intent,
                filter_id=filter_id,
                source=(real_outcome.get("source") or "graph_direct"),
            )

        # Infer from control type and device compliance state
        return self._infer_outcome(ctrl_data, device_data, target_type, target_id, filter_id, intent)

    def _infer_outcome(
        self, ctrl_data, device_data, target_type, target_id, filter_id, intent
    ) -> ExplainResult:
        ctrl_type = ctrl_data["control_type"]
        compliance_state = device_data.get("compliance_state", "unknown")

        if ctrl_type == "compliance_policy":
            if compliance_state == "compliant":
                status = "compliant"
                reason_code = "STATUS_COMPLIANT"
                detail = "Device is reported compliant. This policy likely evaluates successfully."
            elif compliance_state == "noncompliant":
                status = "noncompliant"
                reason_code = "STATUS_NONCOMPLIANT"
                detail = "Device is non-compliant. This policy may contribute to the non-compliance state. Check device compliance status in detail view."
            else:
                status = "unknown"
                reason_code = "STATUS_UNKNOWN"
                detail = f"Device compliance state is '{compliance_state}'. Detailed policy evaluation not available in local data."
        elif ctrl_type in ("config_policy", "settings_catalog", "endpoint_security"):
            # For config policies, we typically can't determine outcome without Graph query
            status = "applied"
            reason_code = "STATUS_UNKNOWN"
            detail = "Configuration policy is assigned to this device. Detailed setting-level state requires live Graph query or beta API."
        elif ctrl_type == "app":
            status = "unknown"
            reason_code = "GRAPH_DATA_MISSING"
            detail = "App assignment detected. Install state may be available in App Status tab if synced."
        else:
            status = "unknown"
            reason_code = "STATUS_UNKNOWN"
            detail = "Status not determinable from local data."

        return ExplainResult(
            control_id=ctrl_data["id"],
            control_name=ctrl_data["display_name"],
            control_type=ctrl_type,
            status=status,
            reason_code=reason_code,
            reason_detail=detail,
            target_type=target_type,
            target_id=target_id,
            intent=intent,
            filter_id=filter_id,
            source="inferred",
        )

    class _OutcomeView(TypedDict, total=False):
        status: Optional[str]
        reason_code: Optional[str]
        reason_detail: Optional[str]
        source: Optional[str]

    def _get_stored_outcome(self, device_id: str, ctrl_id: str) -> Optional["ExplainabilityEngine._OutcomeView"]:
        """Return an outcome snapshot safe to use outside the DB session.

        We must not leak ORM instances outside the session_scope(), otherwise SQLAlchemy
        can raise DetachedInstanceError when attributes are accessed after commit/close.
        """
        with session_scope() as db:
            row = (
                db.query(
                    Outcome.status,
                    Outcome.reason_code,
                    Outcome.reason_detail,
                    Outcome.source,
                )
                .filter(and_(Outcome.device_id == device_id, Outcome.control_id == ctrl_id))
                .first()
            )
            if not row:
                return None
            return {
                "status": row[0],
                "reason_code": row[1],
                "reason_detail": row[2],
                "source": row[3],
            }

    def _detect_conflicts(self, results: list[ExplainResult]) -> list[ConflictHint]:
        """
        Heuristic: if two compliance policies are assigned to the same device,
        they may set conflicting rules. If two config policies of the same type/platform
        are both applied, flag as potential conflict.
        """
        hints = []
        compliance_policies = [r for r in results if r.control_type == "compliance_policy" and r.intent == "include"]
        config_policies = [r for r in results if r.control_type in ("config_policy", "settings_catalog") and r.intent == "include"]

        if len(compliance_policies) > 1:
            for i, a in enumerate(compliance_policies):
                for b in compliance_policies[i+1:]:
                    hints.append(ConflictHint(
                        control_a_id=a.control_id,
                        control_a_name=a.control_name,
                        control_b_id=b.control_id,
                        control_b_name=b.control_name,
                        conflict_type="overlapping_compliance",
                        detail=(
                            "Multiple compliance policies assigned to this device. "
                            "The most restrictive settings will typically apply. "
                            "This is a heuristic — review individual policy settings."
                        ),
                    ))

        if len(config_policies) > 1:
            # Simplified: flag if same category name fragment appears
            seen_categories: dict[str, ExplainResult] = {}
            for r in config_policies:
                # Crude category extraction from name
                name_lower = r.control_name.lower()
                for cat in ["bitlocker", "defender", "firewall", "update", "edge", "password", "vpn", "wifi"]:
                    if cat in name_lower:
                        if cat in seen_categories:
                            other = seen_categories[cat]
                            hints.append(ConflictHint(
                                control_a_id=other.control_id,
                                control_a_name=other.control_name,
                                control_b_id=r.control_id,
                                control_b_name=r.control_name,
                                conflict_type="same_category",
                                detail=f"Two policies with '{cat}' in their names are both applied. They may set conflicting settings. This is a name-based heuristic — verify in Intune portal.",
                            ))
                        else:
                            seen_categories[cat] = r

        return hints

    def _enrich_with_compliance_status(self, device_id: str, explanation: DeviceExplanation):
        """Enrich with per-policy compliance status data if available."""
        with session_scope() as db:
            statuses = db.query(DeviceComplianceStatus).filter(
                DeviceComplianceStatus.device_id == device_id
            ).all()

            for cs in statuses:
                # Find matching result and update it
                for r in explanation.results:
                    if r.control_id == cs.policy_id:
                        r.status = cs.status or r.status
                        r.source = "graph_direct"
                        if cs.status == "compliant":
                            r.reason_code = "STATUS_COMPLIANT"
                            r.reason_detail = f"Compliance policy reports: {cs.status}. Last report: {cs.last_report_datetime}"
                        elif cs.status in ("noncompliant", "conflict"):
                            r.reason_code = "STATUS_NONCOMPLIANT" if cs.status == "noncompliant" else "CONFLICT_SETTING"
                            r.reason_detail = f"Compliance policy reports: {cs.status}. Last report: {cs.last_report_datetime}"

    def _build_summary(self, explanation: DeviceExplanation) -> str:
        n_assigned = len([r for r in explanation.results if r.intent == "include"])
        n_excluded = len([r for r in explanation.results if r.intent == "exclude"])
        n_noncompliant = len([r for r in explanation.results if "noncompliant" in r.status.lower()])
        n_conflicts = len(explanation.conflicts)

        parts = [
            f"Device '{explanation.device_name}' is {explanation.compliance_state.upper()}.",
            f"{n_assigned} control(s) apply, {n_excluded} explicitly excluded.",
        ]
        if n_noncompliant:
            parts.append(f"⚠️  {n_noncompliant} control(s) report non-compliance.")
        if n_conflicts:
            parts.append(f"⚡ {n_conflicts} potential conflict(s) detected (heuristic).")

        if not n_assigned:
            # If nothing matched, give a more actionable hint.
            with session_scope() as db:
                group_asmt = db.query(Assignment).filter(Assignment.target_type == "group").count()
                mcount = db.query(DeviceGroupMembership).filter(
                    DeviceGroupMembership.device_id == explanation.device_id
                ).count()

            if group_asmt and mcount == 0:
                parts.append(
                    "No matching assignments found — group memberships are missing in the local cache. "
                    "If your tenant uses group-based targeting (common), add delegated 'Device.Read.All' "
                    "to the app registration, grant admin consent, then run a full sync."
                )
            else:
                parts.append(
                    "No matching assignments found — group memberships may not be synced yet. Run a full sync."
                )
        return " ".join(parts)


    def _assess_completeness(self, explanation: DeviceExplanation) -> str:
        graph_direct = sum(1 for r in explanation.results if r.source == "graph_direct")
        total = len(explanation.results)
        if total == 0:
            return "minimal"
        if graph_direct / total >= 0.7:
            return "full"
        if graph_direct > 0:
            return "partial"
        return "minimal"
