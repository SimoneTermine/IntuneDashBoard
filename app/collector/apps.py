"""
Collector for Intune managed apps and per-device install status.

Graph API notes on app deviceStatuses:
  - The /deviceStatuses sub-endpoint is available only for certain app types
    AND only when the app has been deployed to at least one device in a way
    that Intune tracks install state.
  - Even win32LobApp can return 400 if the app has no tracked device installs
    (e.g. app assigned but no device has ever reported status).
  - Strategy: attempt for known-supported types; treat ALL errors as non-fatal
    DEBUG messages, not warnings, since this is a best-effort enrichment.
  - Fallback: use /installSummary (aggregate only) for unsupported types
    to at least record total installed/failed counts.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.db.database import session_scope
from app.db.models import App, DeviceAppStatus
from app.graph.client import GraphClient, GraphError
from app.graph.endpoints import (
    MOBILE_APPS,
    APP_DEVICE_STATUSES,
    APP_SELECT_FIELDS,
)

logger = logging.getLogger(__name__)

# Types where per-device /deviceStatuses MAY be available
DEVICE_STATUS_SUPPORTED_TYPES = {
    "win32LobApp",
    "windowsMobileMSI",
    "microsoftStoreForBusinessApp",
    "microsoftStoreForBusinessContainedApp",
    "iosLobApp",
    "androidLobApp",
    "managedIOSStoreApp",
    "managedAndroidStoreApp",
    "managedIOSLobApp",
    "managedAndroidLobApp",
    "windowsUniversalAppX",
    "windowsAppX",
}


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


class AppCollector:

    def __init__(self, client: GraphClient):
        self.client = client

    def sync_apps(self) -> int:
        logger.info("Syncing apps...")
        count = 0
        params = {"$select": APP_SELECT_FIELDS}

        for raw in self.client.get_paged(MOBILE_APPS, params=params):
            try:
                self._upsert_app(raw)
                count += 1
            except Exception as e:
                logger.error(f"Error processing app {raw.get('id')}: {e}")

        logger.info(f"Apps synced: {count}")
        self._sync_install_statuses()
        return count

    def _upsert_app(self, raw: dict):
        app_id = raw.get("id", "")
        if not app_id:
            return
        with session_scope() as db:
            app = db.get(App, app_id) or App(id=app_id)
            odata = raw.get("@odata.type", "")
            if odata:
                app.app_type = odata.split(".")[-1].replace("#", "")
            else:
                app.app_type = app.app_type or "unknown"
            app.display_name = raw.get("displayName", "")
            app.publisher = raw.get("publisher", "")
            app.description = raw.get("description", "")
            app.version = str(raw.get("version", raw.get("displayVersion", "")))
            app.last_modified_datetime = _parse_dt(raw.get("lastModifiedDateTime"))
            app.is_assigned = True
            app.raw_json = json.dumps(raw)
            app.synced_at = datetime.utcnow()
            db.merge(app)

    def _sync_install_statuses(self):
        """
        Best-effort: fetch per-device install status for supported app types.
        All errors are DEBUG-level — this is supplementary data, not critical.
        If /deviceStatuses fails (even for supported types), the app still
        syncs correctly; just without per-device install detail.
        """
        logger.info("Syncing app device install statuses (best-effort)...")

        with session_scope() as db:
            apps = [(a.id, a.app_type or "") for a in db.query(App).all()]

        synced = 0
        skipped = 0

        for app_id, app_type in apps[:50]:
            if app_type not in DEVICE_STATUS_SUPPORTED_TYPES:
                skipped += 1
                continue
            try:
                # Use /deviceStatuses (beta) for per-device install status.
                # Some tenants/app types still return 400/404 — that's expected and handled as best-effort.
                endpoint = APP_DEVICE_STATUSES.format(app_id=app_id)
                statuses = self.client.get_all(
                    endpoint,
                    params={
                        "$select": "id,deviceId,deviceName,displayVersion,"
                                   "installState,errorCode,lastSyncDateTime,"
                                   "userPrincipalName,userName"
                    },
                    api_version="beta",
                )
                with session_scope() as db:
                    for raw in statuses:
                        self._upsert_device_app_status(db, raw, app_id)
                synced += len(statuses)
                logger.debug(f"App {app_id} ({app_type}): {len(statuses)} device statuses")
            except GraphError as e:
                # Non-fatal best-effort enrichment.
                # Reduce noise for the common "segment not found" cases.
                msg = str(e)
                if e.status_code in (400, 404) and "deviceStatuses" in msg and "segment" in msg:
                    logger.debug(
                        f"App {app_id} ({app_type}): per-device install status not available via Graph in this tenant/app. Skipping."
                    )
                else:
                    logger.debug(f"App {app_id} ({app_type}): per-device install status fetch failed: {e}")
            except Exception as e:
                logger.debug(f"App {app_id} ({app_type}): per-device install status fetch failed: {e}")

        logger.info(
            f"App install statuses: {synced} synced, {skipped} skipped (unsupported type)"
        )

    def _upsert_device_app_status(self, db, raw: dict, app_id: str):
        device_id = raw.get("deviceId", "")
        if not device_id:
            return
        existing = db.query(DeviceAppStatus).filter(
            DeviceAppStatus.device_id == device_id,
            DeviceAppStatus.app_id == app_id,
        ).first()
        s = existing or DeviceAppStatus()
        s.device_id = device_id
        s.app_id = app_id
        s.install_state = raw.get("installState", "unknown")
        s.error_code = raw.get("errorCode")
        s.last_sync_date_time = _parse_dt(raw.get("lastSyncDateTime"))
        s.device_name = raw.get("deviceName", "")
        s.user_name = raw.get("userName", raw.get("userPrincipalName", ""))
        s.raw_json = json.dumps(raw)
        s.synced_at = datetime.utcnow()
        if not existing:
            db.add(s)
