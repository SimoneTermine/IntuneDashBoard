"""
Collector for Intune compliance policies, configuration policies,
endpoint security policies, and their assignments.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.db.database import session_scope
from app.db.models import Control, Assignment, DeviceComplianceStatus
from app.graph.client import GraphClient
from app.graph.endpoints import (
    DEVICE_COMPLIANCE_POLICIES, DEVICE_COMPLIANCE_ASSIGNMENTS,
    DEVICE_CONFIGURATIONS, DEVICE_CONFIG_ASSIGNMENTS,
    SETTINGS_CATALOG_POLICIES, SETTINGS_CATALOG_ASSIGNMENTS,
    COMPLIANCE_POLICY_SELECT_FIELDS, DEVICE_CONFIG_SELECT_FIELDS,
    DEVICE_COMPLIANCE_DEVICE_STATUS,
)

logger = logging.getLogger(__name__)


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


class PolicyCollector:
    """Downloads compliance and configuration policies."""

    def __init__(self, client: GraphClient):
        self.client = client

    # ------------------------------------------------------------------
    # Compliance Policies
    # ------------------------------------------------------------------
    def sync_compliance_policies(self) -> int:
        logger.info("Syncing compliance policies...")
        count = 0
        params = {"$select": COMPLIANCE_POLICY_SELECT_FIELDS}

        for raw in self.client.get_paged(DEVICE_COMPLIANCE_POLICIES, params=params):
            try:
                self._upsert_control(raw, "compliance_policy", "v1.0")
                count += 1
            except Exception as e:
                logger.error(f"Error processing compliance policy {raw.get('id')}: {e}")

        logger.info(f"Compliance policies synced: {count}")
        return count

    def sync_compliance_device_statuses(self, policy_id: str) -> list:
        """
        Fetch per-device compliance status for a specific policy.
        Returns list of raw status dicts.
        Used lazily from device detail view.
        """
        endpoint = DEVICE_COMPLIANCE_DEVICE_STATUS.format(policy_id=policy_id)
        try:
            statuses = self.client.get_all(endpoint, api_version="v1.0")
            with session_scope() as db:
                for raw in statuses:
                    sid = raw.get("id", "")
                    device_id = raw.get("managedDeviceId", "")
                    if not sid or not device_id:
                        continue
                    s = db.get(DeviceComplianceStatus, sid) or DeviceComplianceStatus(id=sid)
                    s.device_id = device_id
                    s.policy_id = policy_id
                    s.policy_display_name = raw.get("policyDisplayName", "")
                    s.status = raw.get("status", "")
                    s.last_report_datetime = _parse_dt(raw.get("lastReportedDateTime"))
                    s.user_name = raw.get("userName", "")
                    s.user_principal_name = raw.get("userPrincipalName", "")
                    s.raw_json = json.dumps(raw)
                    s.synced_at = datetime.utcnow()
                    db.merge(s)
            return statuses
        except Exception as e:
            logger.error(f"Error fetching compliance statuses for policy {policy_id}: {e}")
            return []

    # ------------------------------------------------------------------
    # Device Configuration Policies (classic)
    # ------------------------------------------------------------------
    def sync_config_policies(self) -> int:
        logger.info("Syncing device configurations...")
        count = 0
        params = {"$select": DEVICE_CONFIG_SELECT_FIELDS}

        for raw in self.client.get_paged(DEVICE_CONFIGURATIONS, params=params):
            try:
                # Determine platform from OData type
                odata_type = raw.get("@odata.type", "")
                platform = _infer_platform(odata_type)
                self._upsert_control(raw, "config_policy", "v1.0", platform=platform)
                count += 1
            except Exception as e:
                logger.error(f"Error processing config policy {raw.get('id')}: {e}")

        # Also sync settings catalog (endpoint security, settings catalog) — beta
        try:
            count += self.sync_settings_catalog_policies()
        except Exception as e:
            logger.warning(f"Settings catalog sync partial failure: {e}")

        logger.info(f"Config policies synced: {count}")
        return count

    def sync_settings_catalog_policies(self) -> int:
        """Sync settings catalog / endpoint security policies (beta API)."""
        logger.info("Syncing settings catalog policies (beta)...")
        count = 0
        params = {"$select": "id,name,description,createdDateTime,lastModifiedDateTime,settingCount,platforms,technologies"}

        for raw in self.client.get_paged(SETTINGS_CATALOG_POLICIES, params=params, api_version="beta"):
            try:
                # Rename 'name' to 'displayName' for consistency
                raw["displayName"] = raw.pop("name", raw.get("displayName", ""))
                technologies = raw.get("technologies", "")
                ctrl_type = "endpoint_security" if "endpointSecurity" in technologies.lower() else "settings_catalog"
                self._upsert_control(raw, ctrl_type, "beta")
                count += 1
            except Exception as e:
                logger.error(f"Error processing settings catalog policy {raw.get('id')}: {e}")

        return count

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def sync_all_assignments(self) -> int:
        """Sync assignments for all controls in DB."""
        logger.info("Syncing assignments for all controls...")
        total = 0
        with session_scope() as db:
            controls = db.query(Control).all()
            control_ids = [(c.id, c.control_type, c.api_source) for c in controls]

        for ctrl_id, ctrl_type, api_source in control_ids:
            try:
                count = self._sync_assignments_for(ctrl_id, ctrl_type, api_source or "v1.0")
                total += count
            except Exception as e:
                logger.warning(f"Could not sync assignments for {ctrl_id}: {e}")

        logger.info(f"Total assignments synced: {total}")
        return total

    def _sync_assignments_for(self, ctrl_id: str, ctrl_type: str, api_version: str) -> int:
        if ctrl_type == "compliance_policy":
            endpoint = DEVICE_COMPLIANCE_ASSIGNMENTS.format(policy_id=ctrl_id)
        elif ctrl_type in ("config_policy",):
            endpoint = DEVICE_CONFIG_ASSIGNMENTS.format(config_id=ctrl_id)
        elif ctrl_type in ("settings_catalog", "endpoint_security"):
            endpoint = SETTINGS_CATALOG_ASSIGNMENTS.format(policy_id=ctrl_id)
        else:
            return 0

        try:
            items = self.client.get_all(endpoint, api_version=api_version)
        except Exception as e:
            logger.debug(f"Assignment fetch skipped for {ctrl_id}: {e}")
            return 0

        count = 0
        with session_scope() as db:
            for raw in items:
                a = self._parse_assignment(raw, ctrl_id)
                if a:
                    existing = db.get(Assignment, a.id)
                    if existing:
                        existing.target_type = a.target_type
                        existing.target_id = a.target_id
                        existing.intent = a.intent
                        existing.filter_id = a.filter_id
                        existing.filter_type = a.filter_type
                        existing.raw_json = a.raw_json
                        existing.synced_at = datetime.utcnow()
                    else:
                        db.add(a)
                    count += 1

        # Update assignment count on control
        with session_scope() as db:
            ctrl = db.get(Control, ctrl_id)
            if ctrl:
                ctrl.assignment_count = count
                ctrl.is_assigned = count > 0

        return count

    def _parse_assignment(self, raw: dict, ctrl_id: str) -> Optional[Assignment]:
        target = raw.get("target", {})
        odata = target.get("@odata.type", "")
        assignment_id = raw.get("id", "")
        if not assignment_id:
            return None

        target_type = "unknown"
        target_id = ""
        intent = "include"
        filter_id = None
        filter_type = None

        if "allDevicesAssignmentTarget" in odata:
            target_type = "allDevices"
            target_id = "allDevices"
        elif "allLicensedUsersAssignmentTarget" in odata:
            target_type = "allUsers"
            target_id = "allUsers"
        elif "groupAssignmentTarget" in odata or "exclusionGroupAssignmentTarget" in odata:
            target_type = "group"
            target_id = target.get("groupId", "")
            if "exclusion" in odata.lower():
                intent = "exclude"
        elif "configManagerCollectionAssignmentTarget" in odata:
            target_type = "configManagerCollection"
            target_id = target.get("collectionId", "")

        # Filter
        filter_id = target.get("deviceAndAppManagementAssignmentFilterId")
        filter_type = target.get("deviceAndAppManagementAssignmentFilterType")

        return Assignment(
            id=assignment_id,
            control_id=ctrl_id,
            target_type=target_type,
            target_id=target_id,
            intent=intent,
            filter_id=filter_id,
            filter_type=filter_type,
            raw_json=json.dumps(raw),
            synced_at=datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    def _upsert_control(self, raw: dict, ctrl_type: str, api_source: str, platform: str | None = None):
        ctrl_id = raw.get("id", "")
        if not ctrl_id:
            return
        with session_scope() as db:
            ctrl = db.get(Control, ctrl_id) or Control(id=ctrl_id)
            ctrl.display_name = raw.get("displayName", raw.get("name", ""))
            ctrl.control_type = ctrl_type
            ctrl.platform = platform or raw.get("platforms", "")
            ctrl.description = raw.get("description", "")
            ctrl.last_modified_datetime = _parse_dt(raw.get("lastModifiedDateTime"))
            ctrl.created_datetime = _parse_dt(raw.get("createdDateTime"))
            ctrl.version = str(raw.get("version", ""))
            ctrl.api_source = api_source
            ctrl.raw_json = json.dumps(raw)
            ctrl.synced_at = datetime.utcnow()
            db.merge(ctrl)


def _infer_platform(odata_type: str) -> str:
    mapping = {
        "windows": "windows",
        "ios": "ios",
        "android": "android",
        "macOS": "macOS",
        "osx": "macOS",
    }
    lower = odata_type.lower()
    for key, val in mapping.items():
        if key in lower:
            return val
    return "unknown"
