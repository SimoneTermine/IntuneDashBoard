"""
Collector for Intune compliance policies, configuration policies,
endpoint security policies, and their assignments.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.db.database import session_scope
from app.db.models import Control, Assignment
from app.graph.client import GraphClient
from app.graph.endpoints import (
    DEVICE_COMPLIANCE_POLICIES, DEVICE_COMPLIANCE_ASSIGNMENTS,
    DEVICE_CONFIGURATIONS, DEVICE_CONFIG_ASSIGNMENTS,
    SETTINGS_CATALOG_POLICIES, SETTINGS_CATALOG_ASSIGNMENTS,
    COMPLIANCE_POLICY_SELECT_FIELDS, DEVICE_CONFIG_SELECT_FIELDS,
    DEVICE_COMPLIANCE_DEVICE_STATUS,
)

logger = logging.getLogger(__name__)


class PolicySyncError(Exception):
    """Sanitized summary of records or requests that made a policy sync incomplete."""

    def __init__(
        self,
        operation: str,
        succeeded_count: int,
        failed_count: int,
        error_counts: dict[str, int],
    ):
        super().__init__(f"{operation} collection was incomplete")
        self.operation = operation
        self.succeeded_count = succeeded_count
        self.failed_count = failed_count
        self.error_counts = error_counts


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

    @staticmethod
    def _record_error(error_counts: dict[str, int], operation: str, error: Exception) -> None:
        key = f"{operation}:{type(error).__name__}"
        error_counts[key] = error_counts.get(key, 0) + 1

    @staticmethod
    def _merge_error_counts(target: dict[str, int], source: dict[str, int]) -> None:
        for key, count in source.items():
            target[key] = target.get(key, 0) + count

    @staticmethod
    def _raise_if_incomplete(
        operation: str,
        succeeded_count: int,
        failed_count: int,
        error_counts: dict[str, int],
    ) -> None:
        if failed_count:
            raise PolicySyncError(operation, succeeded_count, failed_count, error_counts)

    # ------------------------------------------------------------------
    # Compliance Policies
    # ------------------------------------------------------------------
    def sync_compliance_policies(self) -> int:
        logger.info("Syncing compliance policies...")
        count = 0
        failed_count = 0
        error_counts: dict[str, int] = {}
        params = {"$select": COMPLIANCE_POLICY_SELECT_FIELDS}

        try:
            for raw in self.client.get_paged(DEVICE_COMPLIANCE_POLICIES, params=params):
                try:
                    self._upsert_control(raw, "compliance_policy", "v1.0")
                    count += 1
                except Exception as e:
                    failed_count += 1
                    self._record_error(error_counts, "compliance_policy_record", e)
                    logger.error("Failed to process compliance policy record (%s)", type(e).__name__)
        except Exception as e:
            failed_count += 1
            self._record_error(error_counts, "compliance_policy_request", e)
            logger.error("Compliance policy request failed (%s)", type(e).__name__)

        logger.info("Compliance policies processed: %d succeeded, %d failed", count, failed_count)
        self._raise_if_incomplete("compliance policies", count, failed_count, error_counts)
        return count

    def sync_compliance_device_statuses(self, policy_id: str) -> list:
        """
        Fetch per-device compliance status for a specific policy.
        Returns list of raw status dicts.
        The Graph response does not provide managedDeviceId, so these rows
        cannot be safely persisted as per-device statuses.
        """
        endpoint = DEVICE_COMPLIANCE_DEVICE_STATUS.format(policy_id=policy_id)
        try:
            return self.client.get_all(endpoint, api_version="v1.0")
        except Exception as e:
            error_type = type(e).__name__
            logger.error("Compliance device status request failed (%s)", error_type)
            raise PolicySyncError(
                "compliance device statuses",
                succeeded_count=0,
                failed_count=1,
                error_counts={f"compliance_device_status_request:{error_type}": 1},
            ) from e

    # ------------------------------------------------------------------
    # Device Configuration Policies (classic)
    # ------------------------------------------------------------------
    def sync_config_policies(self) -> int:
        logger.info("Syncing device configurations...")
        count = 0
        failed_count = 0
        error_counts: dict[str, int] = {}
        params = {"$select": DEVICE_CONFIG_SELECT_FIELDS}

        try:
            for raw in self.client.get_paged(DEVICE_CONFIGURATIONS, params=params):
                try:
                    odata_type = raw.get("@odata.type", "")
                    platform = _infer_platform(odata_type)
                    self._upsert_control(raw, "config_policy", "v1.0", platform=platform)
                    count += 1
                except Exception as e:
                    failed_count += 1
                    self._record_error(error_counts, "config_policy_record", e)
                    logger.error("Failed to process configuration policy record (%s)", type(e).__name__)
        except Exception as e:
            failed_count += 1
            self._record_error(error_counts, "config_policy_request", e)
            logger.error("Configuration policy request failed (%s)", type(e).__name__)

        # Also sync settings catalog (endpoint security, settings catalog) — beta
        try:
            count += self.sync_settings_catalog_policies()
        except PolicySyncError as e:
            count += e.succeeded_count
            failed_count += e.failed_count
            self._merge_error_counts(error_counts, e.error_counts)

        logger.info("Configuration policies processed: %d succeeded, %d failed", count, failed_count)
        self._raise_if_incomplete("configuration policies", count, failed_count, error_counts)
        return count

    def sync_settings_catalog_policies(self) -> int:
        """Sync settings catalog / endpoint security policies (beta API)."""
        logger.info("Syncing settings catalog policies (beta)...")
        count = 0
        failed_count = 0
        error_counts: dict[str, int] = {}
        params = {"$select": "id,name,description,createdDateTime,lastModifiedDateTime,settingCount,platforms,technologies"}

        try:
            for raw in self.client.get_paged(SETTINGS_CATALOG_POLICIES, params=params, api_version="beta"):
                try:
                    raw["displayName"] = raw.pop("name", raw.get("displayName", ""))
                    technologies = raw.get("technologies", "")
                    ctrl_type = "endpoint_security" if "endpointSecurity" in technologies.lower() else "settings_catalog"
                    self._upsert_control(raw, ctrl_type, "beta")
                    count += 1
                except Exception as e:
                    failed_count += 1
                    self._record_error(error_counts, "settings_catalog_record", e)
                    logger.error("Failed to process settings catalog policy record (%s)", type(e).__name__)
        except Exception as e:
            failed_count += 1
            self._record_error(error_counts, "settings_catalog_request", e)
            logger.error("Settings catalog request failed (%s)", type(e).__name__)

        logger.info("Settings catalog policies processed: %d succeeded, %d failed", count, failed_count)
        self._raise_if_incomplete("settings catalog policies", count, failed_count, error_counts)
        return count

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------
    def sync_all_assignments(self) -> int:
        """Sync assignments for all controls in DB."""
        logger.info("Syncing assignments for all controls...")
        total = 0
        failed_count = 0
        error_counts: dict[str, int] = {}
        with session_scope() as db:
            controls = db.query(Control).all()
            control_ids = [(c.id, c.control_type, c.api_source) for c in controls]

        for ctrl_id, ctrl_type, api_source in control_ids:
            try:
                count = self._sync_assignments_for(ctrl_id, ctrl_type, api_source or "v1.0")
                total += count
            except PolicySyncError as e:
                total += e.succeeded_count
                failed_count += e.failed_count
                self._merge_error_counts(error_counts, e.error_counts)
            except Exception as e:
                failed_count += 1
                self._record_error(error_counts, "assignment_persistence", e)
                logger.error("Assignment sync failed (%s)", type(e).__name__)

        logger.info("Assignments processed: %d succeeded, %d failed", total, failed_count)
        self._raise_if_incomplete("assignments", total, failed_count, error_counts)
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
            error_type = type(e).__name__
            logger.error("Assignment request failed (%s)", error_type)
            raise PolicySyncError(
                "assignment fetch",
                succeeded_count=0,
                failed_count=1,
                error_counts={f"assignment_request:{error_type}": 1},
            ) from e

        parsed = []
        failed_count = 0
        error_counts: dict[str, int] = {}
        for raw in items:
            try:
                assignment = self._parse_assignment(raw, ctrl_id)
            except Exception as e:
                failed_count += 1
                self._record_error(error_counts, "assignment_record", e)
                continue
            if assignment is None:
                failed_count += 1
                key = "assignment_record:InvalidRecord"
                error_counts[key] = error_counts.get(key, 0) + 1
            else:
                parsed.append(assignment)

        current_ids = {assignment.id for assignment in parsed}
        with session_scope() as db:
            if not failed_count:
                stale_query = db.query(Assignment).filter(Assignment.control_id == ctrl_id)
                if current_ids:
                    stale_query = stale_query.filter(~Assignment.id.in_(current_ids))
                stale_query.delete(synchronize_session=False)

            for assignment in parsed:
                existing = db.get(Assignment, assignment.id)
                if existing:
                    existing.control_id = ctrl_id
                    existing.target_type = assignment.target_type
                    existing.target_id = assignment.target_id
                    existing.target_display_name = assignment.target_display_name
                    existing.intent = assignment.intent
                    existing.filter_id = assignment.filter_id
                    existing.filter_type = assignment.filter_type
                    existing.raw_json = assignment.raw_json
                    existing.synced_at = assignment.synced_at
                else:
                    db.add(assignment)

            db.flush()
            ctrl = db.get(Control, ctrl_id)
            if ctrl:
                ctrl.assignment_count = db.query(Assignment).filter(
                    Assignment.control_id == ctrl_id
                ).count()
                ctrl.is_assigned = ctrl.assignment_count > 0

        if failed_count:
            raise PolicySyncError(
                "assignment records",
                succeeded_count=len(parsed),
                failed_count=failed_count,
                error_counts=error_counts,
            )
        return len(current_ids)

    def _parse_assignment(self, raw: dict, ctrl_id: str) -> Optional[Assignment]:
        if not isinstance(raw, dict):
            return None
        target = raw.get("target", {})
        if not isinstance(target, dict):
            return None
        odata = target.get("@odata.type", "")
        if not isinstance(odata, str):
            return None
        assignment_id = raw.get("id", "")
        if not isinstance(assignment_id, str) or not assignment_id:
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
            raise ValueError("Policy record has no identifier")
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
        "macos": "macOS",
        "osx": "macOS",
    }
    lower = odata_type.lower()
    for key, val in mapping.items():
        if key in lower:
            return val
    return "unknown"
