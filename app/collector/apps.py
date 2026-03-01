"""
app/collector/apps.py

Collector for Intune managed apps and per-device install status.

Graph API notes on app deviceStatuses:
  - The /deviceStatuses sub-endpoint is available for most app types via the beta API.
    Errors (400/404) are silenced at DEBUG level — this is best-effort enrichment.
  - win32LobApp and windowsMobileMSI use /deviceInstallStates (different endpoint).
  - winGetApp, officeSuiteApp, and most store/LOB types use /deviceStatuses.
  - Even supported types can 400 if the app has no tracked device installs yet.
  - No hard cap on number of apps processed — all synced apps are attempted.
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
    APP_WIN32_INSTALL_STATES,
    APP_SELECT_FIELDS,
)

logger = logging.getLogger(__name__)

# Types where per-device status is fetched via /deviceStatuses (beta)
DEVICE_STATUS_SUPPORTED_TYPES = {
    # WinGet (modern Windows package manager — most common in current tenants)
    "winGetApp",
    # iOS / Android LOB and Store
    "iosLobApp",
    "androidLobApp",
    "managedIOSStoreApp",
    "managedAndroidStoreApp",
    "managedIOSLobApp",
    "managedAndroidLobApp",
    # Windows Store apps
    "microsoftStoreForBusinessApp",
    "microsoftStoreForBusinessContainedApp",
    "windowsUniversalAppX",
    "windowsAppX",
    "windowsStoreApp",
    # Office suite
    "officeSuiteApp",
    # Web apps (install state tracked by Intune)
    "webApp",
}

# Types that use /deviceInstallStates instead of /deviceStatuses
WIN32_INSTALL_STATE_TYPES = {
    "win32LobApp",
    "windowsMobileMSI",
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
        Best-effort: fetch per-device install status for all supported app types.

        Uses two endpoints depending on app type:
          - /deviceStatuses      → winGetApp, LOB, Store apps
          - /deviceInstallStates → win32LobApp, windowsMobileMSI

        All errors are DEBUG-level only — failures here do not affect app metadata sync.
        No cap on number of apps processed.
        """
        logger.info("Syncing app device install statuses (best-effort)...")

        with session_scope() as db:
            apps = [(a.id, a.app_type or "") for a in db.query(App).all()]

        synced = 0
        skipped = 0

        for app_id, app_type in apps:
            if app_type in WIN32_INSTALL_STATE_TYPES:
                # Win32/MSI apps use a different endpoint
                self._sync_win32_statuses(app_id, app_type)
                synced += 1
            elif app_type in DEVICE_STATUS_SUPPORTED_TYPES:
                self._sync_device_statuses(app_id, app_type)
                synced += 1
            else:
                skipped += 1

        logger.info(
            f"App install statuses: {synced} attempted, {skipped} skipped (unsupported type)"
        )

    def _sync_device_statuses(self, app_id: str, app_type: str):
        """Fetch per-device install status via /deviceStatuses (beta)."""
        try:
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
            if statuses:
                logger.debug(f"App {app_id} ({app_type}): {len(statuses)} device statuses")
        except GraphError as e:
            msg = str(e)
            if e.status_code in (400, 404) and ("deviceStatuses" in msg or "segment" in msg):
                logger.debug(
                    f"App {app_id} ({app_type}): /deviceStatuses not available — skipping"
                )
            else:
                logger.debug(f"App {app_id} ({app_type}): /deviceStatuses failed: {e}")
        except Exception as e:
            logger.debug(f"App {app_id} ({app_type}): install status fetch failed: {e}")

    def _sync_win32_statuses(self, app_id: str, app_type: str):
        """Fetch per-device install status via /deviceInstallStates (Win32/MSI)."""
        try:
            endpoint = APP_WIN32_INSTALL_STATES.format(app_id=app_id)
            statuses = self.client.get_all(
                endpoint,
                params={
                    "$select": "id,deviceId,deviceName,installState,errorCode,lastSyncDateTime"
                },
                api_version="beta",
            )
            with session_scope() as db:
                for raw in statuses:
                    # /deviceInstallStates uses "deviceId" field same as /deviceStatuses
                    self._upsert_device_app_status(db, raw, app_id)
            if statuses:
                logger.debug(f"App {app_id} ({app_type}): {len(statuses)} win32 install states")
        except GraphError as e:
            logger.debug(f"App {app_id} ({app_type}): /deviceInstallStates failed: {e}")
        except Exception as e:
            logger.debug(f"App {app_id} ({app_type}): win32 install state fetch failed: {e}")

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
