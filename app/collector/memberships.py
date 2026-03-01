"""
Collector for device → group memberships.

Why this exists:
- Intune assignments are most commonly scoped to Entra ID groups (device groups and/or user groups).
- To explain "why a policy applies", we need the group IDs a device is effectively targeted through.

Strategy (best-effort):
1) DEVICE memberships (preferred):  GET /devices/{azureADDeviceId}/transitiveMemberOf
   - Accurate for device-group assignments.
   - Requires delegated permission: Device.Read.All (admin consent).
   - The signed-in user also needs an Entra role that can read directory device memberships.

2) USER memberships (fallback/complement): GET /users/{id|upn}/transitiveMemberOf
   - Useful when policies are assigned to user groups.
   - Requires delegated permissions: User.Read.All + Group.Read.All.

We store *both* sets as "effective memberships" for the device.
"""

import logging
from datetime import datetime
from typing import Optional

from app.db.database import session_scope
from app.db.models import Device, Group, DeviceGroupMembership
from app.graph.client import GraphClient, GraphError

logger = logging.getLogger(__name__)


class MembershipCollector:

    def __init__(self, client: GraphClient):
        self.client = client
        self._logged_device_perm_hint = False

    def sync_all_memberships(self, max_devices: int = 500) -> int:
        """
        Sync effective group memberships for all devices.
        Returns total membership records written.
        """
        logger.info("Syncing device/user group memberships...")

        with session_scope() as db:
            devices = db.query(Device).limit(max_devices).all()
            device_data = [
                {
                    "id": d.id,
                    "aad_device_id": d.azure_ad_device_id,
                    "user_id": d.user_id,
                    "upn": d.user_principal_name,
                }
                for d in devices
            ]

        total = 0
        for d in device_data:
            count = 0

            # 1) Device memberships (most accurate for device-targeted assignments)
            if d.get("aad_device_id"):
                count += self._sync_by_aad_device(d["id"], d["aad_device_id"]) or 0

            # 2) User memberships (useful for user-targeted assignments)
            if d.get("user_id"):
                count += self._sync_by_user_id(d["id"], d["user_id"]) or 0
            elif d.get("upn"):
                count += self._sync_by_upn(d["id"], d["upn"]) or 0
            else:
                logger.debug(f"Device {d['id'][:8]}…: no userId or UPN — skipping user membership sync")

            if count:
                logger.debug(f"Device {d['id'][:8]}…: {count} effective group memberships synced")
            total += count

        logger.info(f"Group memberships synced: {total} across {len(device_data)} devices")
        return total


    def _sync_by_aad_device(self, device_id: str, aad_device_id: str) -> int:
        """
        Sync group memberships for a device.

        IMPORTANT: Intune's managedDevice.azureADDeviceId is not always the Entra device *object id*.
        In many tenants it maps to the Entra device "deviceId" property.

        Graph supports both addressing modes:
        - /devices/{id}                    -> Entra device object id
        - /devices(deviceId='{deviceId}')  -> Entra device deviceId

        We try the object-id form first (fast path) and fall back to deviceId addressing on 404.
        """

        def _fetch(endpoint: str) -> list:
            items = self.client.get_all(
                endpoint,
                params={"$select": "id,displayName"},
            )
            return [i for i in items if "group" in i.get("@odata.type", "").lower()]
        # In practice, Intune managedDevice.azureADDeviceId maps to Entra 'deviceId' (not object id).
        # To avoid noisy 404s, try deviceId addressing first, then fall back to object-id addressing.
        try:
            items = _fetch(f"devices(deviceId='{aad_device_id}')/transitiveMemberOf")
            return self._store(device_id, items)
        except GraphError as e:
            if e.status_code == 404:
                try:
                    items = _fetch(f"devices/{aad_device_id}/transitiveMemberOf")
                    return self._store(device_id, items)
                except GraphError as e2:
                    e = e2

            # Typical: missing Device.Read.All or missing Entra role for the signed-in user
            if e.status_code == 403 and not self._logged_device_perm_hint:
                self._logged_device_perm_hint = True
                logger.warning(
                    "Device group membership lookup is not permitted (403). "
                    "If your policies are assigned to DEVICE groups (common), add delegated 'Device.Read.All' "
                    "to the app registration, grant admin consent, and ensure the signed-in user has a "
                    "role like Directory Readers / Global Reader / Intune Administrator."
                )
            else:
                logger.debug(f"Device membership lookup failed for aadDeviceId={aad_device_id}: {e}")
            return 0
        except Exception as e:
            logger.debug(f"Device membership lookup failed for aadDeviceId={aad_device_id}: {e}")
            return 0

    def _sync_by_user_id(self, device_id: str, user_id: str) -> int:
        try:
            # Attempt with $filter (faster, not all tenants support it on transitiveMemberOf)
            try:
                items = self.client.get_all(
                    f"users/{user_id}/transitiveMemberOf",
                    params={
                        "$select": "id,displayName",
                        "$filter": "isof('microsoft.graph.group')",
                    },
                )
            except Exception:
                # Fallback: fetch all and filter locally
                items = self.client.get_all(
                    f"users/{user_id}/transitiveMemberOf",
                    params={"$select": "id,displayName"},
                )
                items = [i for i in items if "group" in i.get("@odata.type", "").lower()]

            return self._store(device_id, items)
        except Exception as e:
            logger.debug(f"User membership lookup failed for userId={user_id}: {e}")
            return 0

    def _sync_by_upn(self, device_id: str, upn: str) -> int:
        try:
            items = self.client.get_all(
                f"users/{upn}/transitiveMemberOf",
                params={"$select": "id,displayName"},
            )
            items = [i for i in items if "group" in i.get("@odata.type", "").lower()]
            return self._store(device_id, items)
        except Exception as e:
            logger.debug(f"User membership lookup failed for UPN={upn}: {e}")
            return 0

    def _store(self, device_id: str, items: list) -> int:
        """Persist memberships.

        NOTE: DeviceGroupMembership has FK references to both devices and groups.
        Some SQLAlchemy flush orders can attempt to insert memberships before the
        referenced Group rows unless we flush explicitly. We therefore:
          1) ensure the Device exists
          2) insert missing Group stubs
          3) flush
          4) upsert memberships
        """

        if not items:
            return 0

        with session_scope() as db:
            # Defensive: if the device isn't in DB (shouldn't happen), skip to avoid FK errors
            if not db.get(Device, device_id):
                logger.debug(f"Device {device_id} not found in local DB — skipping membership store")
                return 0

            # Collect unique group IDs
            group_ids: list[str] = []
            seen: set[str] = set()
            for item in items:
                gid = (item.get("id") or "").strip()
                if not gid or gid in seen:
                    continue
                seen.add(gid)
                group_ids.append(gid)

                # Create a minimal group stub if missing
                if not db.get(Group, gid):
                    db.add(
                        Group(
                            id=gid,
                            display_name=item.get("displayName", ""),
                            synced_at=datetime.utcnow(),
                            raw_json="{}",
                        )
                    )

            # Important: flush group inserts BEFORE inserting memberships to satisfy FK constraints
            db.flush()

            # Upsert memberships
            inserted = 0
            for gid in group_ids:
                existing = db.query(DeviceGroupMembership).filter_by(
                    device_id=device_id, group_id=gid
                ).first()
                if existing:
                    # keep timestamp fresh
                    existing.synced_at = datetime.utcnow()
                    continue
                db.add(
                    DeviceGroupMembership(
                        device_id=device_id,
                        group_id=gid,
                        synced_at=datetime.utcnow(),
                    )
                )
                inserted += 1

            return inserted
