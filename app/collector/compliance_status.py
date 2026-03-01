"""
Collector for per-device compliance policy status.

Uses: deviceManagement/managedDevices/{managedDeviceId}/deviceCompliancePolicyStates
  - Called once per device (not per policy)
  - Returns all compliance policy states for that device in one call
  - Fields: id (=deviceCompliancePolicyStateId), displayName, state, settingCount, platformType
  - No invalid $select fields — this endpoint works cleanly

Advantages over the per-policy approach:
  - Single call per device instead of one call per policy
  - Has the device context already — no need for managedDeviceId in response
  - Richer data: platformType, settingCount

Permissions: DeviceManagementManagedDevices.Read.All (already in scope)
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.db.database import session_scope
from app.db.models import Control, Device, DeviceComplianceStatus, Outcome
from app.graph.client import GraphClient

logger = logging.getLogger(__name__)

DEVICE_COMPLIANCE_POLICY_STATES = (
    "deviceManagement/managedDevices/{device_id}/deviceCompliancePolicyStates"
)

STATUS_TO_REASON = {
    # Graph complianceStatus enum values are not consistently cased in the wild.
    # We normalise to lower-case before lookup.
    "compliant":       ("STATUS_COMPLIANT",      "Device meets all requirements for this policy"),
    "noncompliant":    ("STATUS_NONCOMPLIANT",   "Device does not meet one or more requirements"),
    "conflict":        ("CONFLICT_SETTING",      "Conflicting compliance policies detected"),
    "error":           ("STATUS_ERROR",          "Error evaluating compliance — check device/Intune logs"),
    "notapplicable":   ("STATUS_NOT_APPLICABLE", "Policy does not apply to this device OS/type"),
    "unknown":         ("STATUS_UNKNOWN",        "Compliance not yet evaluated"),
    "ingraceperiod":   ("STATUS_GRACE_PERIOD",   "Non-compliant but within the policy grace period"),
    "notassigned":     ("STATUS_NOT_ASSIGNED",   "Policy not assigned to this device"),
    "remediated":      ("STATUS_REMEDIATED",     "Previously non-compliant but remediated"),
}


def _norm(val: str | None) -> str:
    return (val or "").strip().lower()


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


class ComplianceStatusCollector:

    def __init__(self, client: GraphClient):
        self.client = client

    def sync_all(self) -> int:
        """
        For each device, fetch all its compliance policy states in one call.
        Much more efficient than the per-policy approach.
        """
        logger.info("Syncing per-device compliance policy statuses...")

        # We keep devices keyed by managedDeviceId.
        # NOTE: /managedDevices/{id}/deviceCompliancePolicyStates returns deviceCompliancePolicyState objects,
        # whose "id" is a *state* id (deviceCompliancePolicyStateId), not the compliance policy object id.
        # To link outcomes back to real compliance policies, we map by displayName.
        with session_scope() as db:
            devices = db.query(Device).all()
            device_ids = [d.id for d in devices]

            compliance_controls = (
                db.query(Control)
                .filter(Control.control_type == "compliance_policy")
                .all()
            )
            name_to_control_id = {
                _norm(c.display_name): c.id
                for c in compliance_controls
                if c.display_name
            }

        if not device_ids:
            logger.info("No devices in DB — skipping compliance status sync")
            return 0

        total = 0
        for device_id in device_ids:
            try:
                count = self._sync_device_states(device_id, name_to_control_id)
                total += count
                if count:
                    logger.debug(f"Device {device_id[:8]}…: {count} policy states synced")
            except Exception as e:
                logger.debug(f"Compliance policy states failed for device {device_id[:8]}…: {e}")

        self._build_outcomes()
        logger.info(f"Compliance policy states synced: {total} records")
        return total

    def _sync_device_states(self, device_id: str, name_to_control_id: dict[str, str]) -> int:
        endpoint = DEVICE_COMPLIANCE_POLICY_STATES.format(device_id=device_id)
        # No $select needed — all fields are useful and the endpoint is simple
        states = self.client.get_all(endpoint, api_version="v1.0")

        # Graph can occasionally return duplicate entries for the same policy/state id.
        # De-duplicate by id (keep last occurrence) to avoid SQLite UNIQUE constraint failures.
        if states:
            by_id = {}
            for r in states:
                sid = r.get("id")
                if sid:
                    by_id[sid] = r
            states = list(by_id.values())

        count = 0
        with session_scope() as db:
            for raw in states:
                state_id = raw.get("id", "")
                if not state_id:
                    continue

                display_name = raw.get("displayName", "")
                mapped_control_id = name_to_control_id.get(_norm(display_name))
                # Fallback: keep the state id (we will create a placeholder control later if needed)
                control_id = mapped_control_id or state_id

                # Build a composite record ID
                record_id = f"{device_id}_{state_id}"
                s = db.get(DeviceComplianceStatus, record_id)
                if not s:
                    s = DeviceComplianceStatus(id=record_id)
                    db.add(s)
                s.device_id = device_id
                # Store the *real* control id we can join to (best-effort). The raw state id is still in record_id/raw_json.
                s.policy_id = control_id
                s.policy_display_name = display_name
                # field is 'state' not 'status' — normalise to lower-case for stable reason mapping
                s.status = _norm(str(raw.get("state", "unknown"))) or "unknown"
                s.last_report_datetime = _parse_dt(raw.get("lastReportedDateTime"))
                s.user_name = ""
                s.user_principal_name = ""
                s.raw_json = json.dumps(raw)
                s.synced_at = datetime.utcnow()
                count += 1

        return count

    def _build_outcomes(self):
        """
        Build Outcome records from DeviceComplianceStatus data so the
        explainability engine sees real Graph data (source='graph_direct').
        """
        with session_scope() as db:
            # Build a name->id map to repair any legacy rows where policy_id held the *state id*.
            compliance_controls = (
                db.query(Control)
                .filter(Control.control_type == "compliance_policy")
                .all()
            )
            name_to_control_id = {
                _norm(c.display_name): c.id
                for c in compliance_controls
                if c.display_name
            }

            known_device_ids = {d[0] for d in db.query(Device.id).all()}
            known_control_ids = {c[0] for c in db.query(Control.id).all()}

            statuses = db.query(DeviceComplianceStatus).all()
            for cs in statuses:
                # If the device was removed/purged since we cached statuses, skip safely.
                if cs.device_id not in known_device_ids:
                    continue

                # Repair mapping if needed.
                control_id = cs.policy_id
                if control_id not in known_control_ids:
                    mapped = name_to_control_id.get(_norm(cs.policy_display_name))
                    if mapped:
                        cs.policy_id = mapped
                        control_id = mapped
                    else:
                        # Last resort: create a placeholder control so FK constraints don't break the sync.
                        placeholder = Control(
                            id=control_id,
                            display_name=cs.policy_display_name or control_id,
                            control_type="compliance_policy",
                            api_source="inferred",
                            synced_at=datetime.utcnow(),
                        )
                        db.merge(placeholder)
                        known_control_ids.add(control_id)

                reason_code, reason_detail = STATUS_TO_REASON.get(
                    _norm(cs.status), ("STATUS_UNKNOWN", "Status not recognised")
                )

                existing = db.query(Outcome).filter_by(
                    device_id=cs.device_id,
                    control_id=control_id,
                ).first()

                if existing:
                    existing.status = cs.status
                    existing.reason_code = reason_code
                    existing.reason_detail = reason_detail
                    existing.source = "graph_direct"
                    existing.synced_at = datetime.utcnow()
                else:
                    db.add(Outcome(
                        control_id=control_id,
                        device_id=cs.device_id,
                        status=cs.status,
                        reason_code=reason_code,
                        reason_detail=reason_detail,
                        source="graph_direct",
                        synced_at=datetime.utcnow(),
                    ))
