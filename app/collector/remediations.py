"""
app/collector/remediations.py

Collector for Intune Proactive Remediations (deviceHealthScripts).

Graph API:
  GET  beta/deviceManagement/deviceHealthScripts
  POST beta/deviceManagement/managedDevices/{id}/initiateOnDemandProactiveRemediation

Permissions:
  DeviceManagementConfiguration.Read.All       — list / read scripts
  DeviceManagementConfiguration.ReadWrite.All  — run on-demand (write)

Notes:
  - On-demand run is supported only for USER-created scripts (isGlobalScript = false).
  - Microsoft-managed (global) scripts cannot be triggered on-demand.
  - The run endpoint triggers the script on the *next* device check-in;
    it does NOT wait for completion.
  - Response is HTTP 204 No Content on success.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.db.database import session_scope
from app.db.models import Remediation
from app.graph.client import GraphClient, GraphError
from app.graph.endpoints import (
    DEVICE_HEALTH_SCRIPTS,
    DEVICE_REMEDIATION_RUN,
    REMEDIATION_SELECT_FIELDS,
)

logger = logging.getLogger(__name__)


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


class RemediationCollector:

    def __init__(self, client: GraphClient):
        self.client = client

    # ─────────────────────────────────────────────────────────────────────────
    # Sync
    # ─────────────────────────────────────────────────────────────────────────

    def sync_remediations(self) -> int:
        """
        Fetch all device health scripts and persist them in the local DB.
        Uses the beta endpoint (v1.0 does not expose deviceHealthScripts).
        Returns the number of remediations synced.
        """
        logger.info("Syncing proactive remediations (deviceHealthScripts)…")
        count = 0

        try:
            items = self.client.get_all(
                DEVICE_HEALTH_SCRIPTS,
                params={"$select": REMEDIATION_SELECT_FIELDS},
                api_version="beta",
            )
        except GraphError as e:
            if e.status_code == 403:
                logger.warning(
                    "Remediations sync: 403 Forbidden — "
                    "DeviceManagementConfiguration.Read.All permission required."
                )
            else:
                logger.error(f"Remediations sync failed: {e}")
            return 0
        except Exception as e:
            logger.error(f"Remediations sync failed: {e}", exc_info=True)
            return 0

        for raw in items:
            try:
                self._upsert(raw)
                count += 1
            except Exception as e:
                logger.error(f"Remediation upsert failed for {raw.get('id')}: {e}")

        logger.info(f"Remediations synced: {count}")
        return count

    def _upsert(self, raw: dict) -> None:
        script_id = raw.get("id", "")
        if not script_id:
            return

        with session_scope() as db:
            obj = db.get(Remediation, script_id) or Remediation(id=script_id)
            obj.display_name = raw.get("displayName", "")
            obj.description = raw.get("description", "")
            obj.publisher = raw.get("publisher", "")
            obj.is_global_script = bool(raw.get("isGlobalScript", False))
            obj.highest_available_version = raw.get("highestAvailableVersion", "")
            obj.last_modified_datetime = _parse_dt(raw.get("lastModifiedDateTime"))
            obj.created_datetime = _parse_dt(raw.get("createdDateTime"))
            obj.raw_json = json.dumps(raw)
            obj.synced_at = datetime.utcnow()
            db.merge(obj)

    # ─────────────────────────────────────────────────────────────────────────
    # Run on-demand
    # ─────────────────────────────────────────────────────────────────────────

    def run_on_device(self, script_id: str, device_id: str) -> dict:
        """
        Trigger an on-demand remediation run for a specific device.

        Returns a result dict:
          {"success": True}                            — HTTP 204 received
          {"success": False, "error": "<reason>",
           "user_message": "<human-readable text>"}   — failure

        Constraints (enforced here to avoid confusing Graph errors):
          - Only user-created scripts (isGlobalScript = False) can be run on-demand.
          - Requires DeviceManagementConfiguration.ReadWrite.All.
        """
        # Guard: is_global_script check
        try:
            with session_scope() as db:
                rem = db.get(Remediation, script_id)
                if rem and rem.is_global_script:
                    return {
                        "success": False,
                        "error": "global_script",
                        "user_message": (
                            "This is a Microsoft-managed (global) remediation script. "
                            "On-demand run is not supported for global scripts."
                        ),
                    }
        except Exception as e:
            logger.debug(f"Remediation DB check failed: {e} — proceeding anyway")

        endpoint = DEVICE_REMEDIATION_RUN.format(device_id=device_id)
        payload = {"scriptPolicyId": script_id}

        try:
            self.client.post(
                endpoint,
                json=payload,
                api_version="beta",
                expected_status=204,
            )
            logger.info(
                f"On-demand remediation triggered: script={script_id} device={device_id}"
            )
            return {"success": True}

        except GraphError as e:
            status = e.status_code or 0
            logger.error(
                f"Remediation run failed: script={script_id} device={device_id} "
                f"status={status} error={e}"
            )
            if status == 403:
                msg = (
                    "Permission denied (403). "
                    "The app registration needs 'DeviceManagementConfiguration.ReadWrite.All' "
                    "with admin consent to run remediations on-demand."
                )
            elif status == 404:
                msg = (
                    "Script or device not found (404). "
                    "Verify both the script ID and the device ID are correct."
                )
            elif status == 400:
                msg = (
                    f"Bad request (400): {e}. "
                    "The device may not support on-demand remediation, or the "
                    "script may not be assigned to this device."
                )
            else:
                msg = f"Graph API error ({status}): {e}"
            return {"success": False, "error": str(e), "user_message": msg}

        except Exception as e:
            logger.error(f"Remediation run unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "user_message": f"Unexpected error: {e}",
            }
