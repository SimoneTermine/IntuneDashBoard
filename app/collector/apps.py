"""
app/collector/apps.py  —  v1.2.5

Collector for Intune managed apps and per-device install status.

Key changes in v1.2.5:
  - mobileApps synced via BETA API (v1.0 silently excludes winGetApp /
    officeSuiteApp / windowsMicrosoftEdgeApp in some tenant configurations).
  - Verbose per-app logging: every app returned by Graph is logged with its
    OData type BEFORE upsert, so missing types are visible in app_ops.log.
  - win32LobApp /deviceInstallStates 400 → automatic fallback to /deviceStatuses.
  - HTTP 400 on install status endpoints downgraded to INFO (expected for
    newly deployed apps or devices that haven't checked in yet).
  - Per-record session_scope so FK violations never roll back the whole batch.
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
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Supported app type sets
# ─────────────────────────────────────────────────────────────────────────────

# Types fetched via /deviceStatuses (beta)
DEVICE_STATUS_SUPPORTED_TYPES = {
    "winGetApp",
    "windowsMicrosoftEdgeApp",
    "windowsMicrosoftEdgeAppChannel",
    "win32CatalogApp",
    "iosLobApp",
    "androidLobApp",
    "managedIOSStoreApp",
    "managedAndroidStoreApp",
    "managedIOSLobApp",
    "managedAndroidLobApp",
    "microsoftStoreForBusinessApp",
    "microsoftStoreForBusinessContainedApp",
    "windowsUniversalAppX",
    "windowsAppX",
    "windowsStoreApp",
    "officeSuiteApp",
    "webApp",
    "windowsWebApp",
}

# Types that try /deviceInstallStates first, fall back to /deviceStatuses on 400
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

    # ─────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────────

    def sync_apps(self) -> int:
        """
        Sync all mobileApps from Graph using the BETA endpoint.

        Why beta?
          The v1.0 /mobileApps collection silently drops certain modern app types
          (winGetApp, officeSuiteApp, windowsMicrosoftEdgeApp) in some tenant
          configurations. The beta endpoint returns the full polymorphic collection.

        Why no $select?
          Using $select on a polymorphic collection causes Graph to silently omit
          any app type whose OData derived schema does not declare all requested
          fields. No $select = all app types guaranteed.
        """
        logger.info("Syncing apps — BETA API, no $select (all types)...")
        count = 0
        type_counts: dict[str, int] = {}

        for raw in self.client.get_paged(MOBILE_APPS, api_version="beta"):
            app_id   = raw.get("id", "?")
            odata    = raw.get("@odata.type", "unknown")
            app_type = odata.split(".")[-1].replace("#", "") if odata else "unknown"
            name     = raw.get("displayName", "?")

            # Verbose: log every app received from Graph so missing types are visible
            logger.info(f"  Graph app: [{app_type}] {name!r} ({app_id[:8]}...)")

            try:
                self._upsert_app(raw)
                count += 1
                type_counts[app_type] = type_counts.get(app_type, 0) + 1
            except Exception as e:
                logger.error(f"  Failed to upsert {app_id} ({app_type}): {e}", exc_info=True)

        logger.info(
            f"Apps synced: {count} — types: "
            + (", ".join(f"{t}={n}" for t, n in sorted(type_counts.items())) or "none")
        )
        self._sync_install_statuses()
        return count

    # ─────────────────────────────────────────────────────────────────────────
    # App metadata upsert
    # ─────────────────────────────────────────────────────────────────────────

    def _upsert_app(self, raw: dict):
        app_id = raw.get("id", "")
        if not app_id:
            return
        with session_scope() as db:
            app = db.get(App, app_id) or App(id=app_id)
            odata = raw.get("@odata.type", "")
            app.app_type               = odata.split(".")[-1].replace("#", "") if odata else (app.app_type or "unknown")
            app.display_name           = raw.get("displayName", "")
            app.publisher              = raw.get("publisher", "")
            app.description            = raw.get("description", "")
            app.version                = str(raw.get("version", raw.get("displayVersion", "")))
            app.last_modified_datetime = _parse_dt(raw.get("lastModifiedDateTime"))
            app.is_assigned            = True
            app.raw_json               = json.dumps(raw)
            app.synced_at              = datetime.utcnow()
            db.merge(app)

    # ─────────────────────────────────────────────────────────────────────────
    # Install status sync orchestrator
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_install_statuses(self):
        """
        Best-effort: fetch per-device install status for all supported app types.

        HTTP 400 on all status endpoints means Graph has no tracking data yet —
        typical for newly deployed apps where devices have not yet checked in.

        Each record is committed in its own session_scope so a single FK
        violation (deviceId not yet in devices table) never rolls back the
        entire batch for an app.
        """
        logger.info("Syncing app device install statuses (best-effort)...")

        with session_scope() as db:
            apps = [(a.id, a.app_type or "") for a in db.query(App).all()]

        attempted    = 0
        no_data_apps: list[str] = []
        skipped_types: set[str] = set()

        for app_id, app_type in apps:
            if app_type in WIN32_INSTALL_STATE_TYPES:
                had_data = self._sync_win32_statuses(app_id, app_type)
                attempted += 1
                if not had_data:
                    no_data_apps.append(f"{app_type}:{app_id[:8]}")
            elif app_type in DEVICE_STATUS_SUPPORTED_TYPES:
                had_data = self._sync_device_statuses(app_id, app_type)
                attempted += 1
                if not had_data:
                    no_data_apps.append(f"{app_type}:{app_id[:8]}")
            else:
                skipped_types.add(app_type)

        if no_data_apps:
            logger.info(
                f"App install statuses: {attempted} attempted — "
                f"no data from Graph for: {', '.join(no_data_apps)}. "
                f"Devices may not have checked in yet since last app deployment."
            )
        else:
            logger.info(f"App install statuses: {attempted} attempted, all returned data")

        if skipped_types:
            logger.info(f"Skipped unsupported app types: {sorted(skipped_types)}")

    # ─────────────────────────────────────────────────────────────────────────
    # Per-app fetch helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_device_statuses(self, app_id: str, app_type: str) -> bool:
        """
        Fetch per-device install status via /deviceStatuses (beta).
        Returns True if Graph returned any records, False otherwise.
        """
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

            if not statuses:
                logger.debug(f"  {app_type} {app_id[:8]}: /deviceStatuses returned 0 records")
                return False

            saved = failed = 0
            for raw in statuses:
                if self._save_device_app_status(raw, app_id):
                    saved += 1
                else:
                    failed += 1
            logger.info(f"  {app_type} {app_id[:8]}: {saved} saved, {failed} skipped")
            return True

        except GraphError as e:
            if e.status_code in (400, 404):
                logger.info(
                    f"  {app_type} {app_id[:8]}: /deviceStatuses HTTP {e.status_code} "
                    f"(no install data — device check-in pending)"
                )
            else:
                logger.warning(
                    f"  {app_type} {app_id[:8]}: /deviceStatuses HTTP {e.status_code}: {e}"
                )
            return False
        except Exception as e:
            logger.warning(f"  {app_type} {app_id[:8]}: /deviceStatuses failed: {e}")
            return False

    def _sync_win32_statuses(self, app_id: str, app_type: str) -> bool:
        """
        Fetch via /deviceInstallStates (Win32/MSI).
        Falls back to /deviceStatuses on HTTP 400 (known Graph inconsistency).
        Returns True if any records were received, False otherwise.
        """
        try:
            endpoint = APP_WIN32_INSTALL_STATES.format(app_id=app_id)
            statuses = self.client.get_all(
                endpoint,
                params={
                    "$select": "id,deviceId,deviceName,installState,errorCode,lastSyncDateTime"
                },
                api_version="beta",
            )

            if not statuses:
                logger.debug(f"  {app_type} {app_id[:8]}: /deviceInstallStates returned 0 records")
                return False

            saved = failed = 0
            for raw in statuses:
                if self._save_device_app_status(raw, app_id):
                    saved += 1
                else:
                    failed += 1
            logger.info(f"  {app_type} {app_id[:8]}: {saved} saved via /deviceInstallStates, {failed} skipped")
            return True

        except GraphError as e:
            if e.status_code == 400:
                logger.info(
                    f"  {app_type} {app_id[:8]}: /deviceInstallStates 400 — "
                    f"falling back to /deviceStatuses"
                )
                return self._sync_device_statuses(app_id, app_type)
            else:
                logger.warning(
                    f"  {app_type} {app_id[:8]}: /deviceInstallStates HTTP {e.status_code}: {e}"
                )
                return False
        except Exception as e:
            logger.warning(f"  {app_type} {app_id[:8]}: /deviceInstallStates failed: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Per-record DB write (own transaction — FK-safe)
    # ─────────────────────────────────────────────────────────────────────────

    def _save_device_app_status(self, raw: dict, app_id: str) -> bool:
        """
        Persist one device-app status record in its own session_scope.
        Returns True on success, False on any error.
        Each record is independent — a FK violation on one device never
        rolls back the rest of the batch.
        """
        device_id = raw.get("deviceId", "")
        if not device_id:
            logger.debug(f"  App {app_id}: skipping record with no deviceId: {raw}")
            return False

        try:
            with session_scope() as db:
                existing = db.query(DeviceAppStatus).filter(
                    DeviceAppStatus.device_id == device_id,
                    DeviceAppStatus.app_id    == app_id,
                ).first()

                s = existing or DeviceAppStatus()
                s.device_id           = device_id
                s.app_id              = app_id
                s.install_state       = raw.get("installState", "unknown")
                s.error_code          = raw.get("errorCode")
                s.last_sync_date_time = _parse_dt(raw.get("lastSyncDateTime"))
                s.device_name         = raw.get("deviceName", "")
                s.user_name           = raw.get("userName", raw.get("userPrincipalName", ""))
                s.raw_json            = json.dumps(raw)
                s.synced_at           = datetime.utcnow()

                if not existing:
                    db.add(s)
            return True

        except Exception as e:
            logger.debug(
                f"  App {app_id}: could not save status for device {device_id}: "
                f"{type(e).__name__}: {e}"
            )
            return False
