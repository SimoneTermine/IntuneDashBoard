"""
Collector for Intune managed devices.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.db.database import session_scope
from app.db.models import Device
from app.graph.client import GraphClient
from app.graph.endpoints import MANAGED_DEVICES, DEVICE_SELECT_FIELDS

logger = logging.getLogger(__name__)


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


class DeviceCollector:
    """Downloads and persists managed devices from Intune."""

    def __init__(self, client: GraphClient):
        self.client = client

    def sync_all(self) -> int:
        """Sync all managed devices. Returns count of processed devices."""
        logger.info("Starting device sync...")
        count = 0

        params = {"$select": DEVICE_SELECT_FIELDS}

        for raw in self.client.get_paged(MANAGED_DEVICES, params=params):
            try:
                self._upsert_device(raw)
                count += 1
                if count % 100 == 0:
                    logger.info(f"  Devices processed: {count}")
            except Exception as e:
                logger.error(f"Failed to process device {raw.get('id', '?')}: {e}")

        # Sync compliance statuses
        self._sync_compliance_statuses()

        logger.info(f"Device sync complete: {count} devices")
        return count

    def _upsert_device(self, raw: dict):
        """Insert or update a device record."""
        device_id = raw["id"]
        with session_scope() as db:
            device = db.get(Device, device_id) or Device(id=device_id)
            device.device_name = raw.get("deviceName", "")
            device.serial_number = raw.get("serialNumber", "")
            # deviceType is not a valid $select field — derive from operatingSystem
            os_name = raw.get("operatingSystem", "")
            device.device_type = os_name.lower() if os_name else "unknown"
            device.operating_system = raw.get("operatingSystem", "")
            device.os_version = raw.get("osVersion", "")
            device.compliance_state = raw.get("complianceState", "unknown")
            device.management_state = raw.get("managementState", "")
            device.ownership = raw.get("managedDeviceOwnerType", raw.get("ownerType", ""))
            device.enrolled_date_time = _parse_dt(raw.get("enrolledDateTime"))
            device.last_sync_date_time = _parse_dt(raw.get("lastSyncDateTime"))
            device.user_principal_name = raw.get("userPrincipalName", "")
            device.user_display_name = raw.get("userDisplayName", "")
            device.user_id = raw.get("userId", "")
            device.azure_ad_device_id = raw.get("azureADDeviceId", "")
            device.enroll_profile = raw.get("enrollmentProfileName", "")
            device.model = raw.get("model", "")
            device.manufacturer = raw.get("manufacturer", "")
            device.imei = raw.get("imei", "")
            device.total_storage_space_in_bytes = raw.get("totalStorageSpaceInBytes")
            device.free_storage_space_in_bytes = raw.get("freeStorageSpaceInBytes")
            device.jail_broken = raw.get("jailBroken", "")
            device.encrypted = raw.get("isEncrypted")
            device.synced_at = datetime.utcnow()
            device.raw_json = json.dumps(raw)
            db.merge(device)

    def _sync_compliance_statuses(self):
        """
        Sync per-device compliance status for each compliance policy.
        NOTE: This is expensive as it requires one call per policy.
        We sync a summary instead from managedDevices compliance state.
        Detailed per-policy compliance is fetched lazily in device detail view.
        """
        logger.info("Device compliance states already captured in device sync")
