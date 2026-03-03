"""
app/collector/apps.py  —  v1.2.7

Collector for Intune managed apps and per-device install status.

v1.2.7:
  - Removed $select from /deviceStatuses and /deviceInstallStates calls.
    Same root cause as the mobileApps $select fix (v1.2.4/1.2.5): these
    are polymorphic sub-resources and Graph returns HTTP 400
    "InvalidQueryParameter" / "Bad request" when any requested field is not
    declared in the OData derived type schema for that app type.
    Requesting all fields (no $select) works for every app type.
  - 400 responses now log e.raw (the actual Graph error message) so the real
    reason is visible in app_ops.log instead of the generic
    "device check-in pending" assumption.

Previous fixes (kept):
  - mobileApps synced via BETA API (v1.2.5)
  - win32LobApp /deviceInstallStates 400 -> fallback to /deviceStatuses (v1.2.4)
  - per-record session_scope for FK-safe writes (v1.2.3)
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
    APP_STATUS_OVERVIEW_REPORT,
    APP_DEVICE_INSTALL_STATUS_REPORT,
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
          The v1.0 /mobileApps collection silently drops certain modern app
          types (winGetApp, officeSuiteApp, windowsMicrosoftEdgeApp) in some
          tenant configurations.

        Why no $select?
          Using $select on a polymorphic collection causes Graph to silently
          omit app types whose OData derived schema does not declare all
          requested fields.
        """
        logger.info("Syncing apps — BETA API, no $select (all types)...")
        count = 0
        type_counts: dict[str, int] = {}

        for raw in self.client.get_paged(MOBILE_APPS, api_version="beta"):
            app_id   = raw.get("id", "?")
            odata    = raw.get("@odata.type", "unknown")
            app_type = odata.split(".")[-1].replace("#", "") if odata else "unknown"
            name     = raw.get("displayName", "?")

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

        No $select is used on either endpoint — the sub-resources are polymorphic
        too and $select causes 400 "InvalidQueryParameter" when a field is not
        declared in the derived type schema.
        """
        logger.info("Syncing app install statuses (type-cast URLs, beta)...")

        with session_scope() as db:
            apps = [(a.id, a.app_type or "") for a in db.query(App).all()]

        attempted     = 0
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
                f"no records from Graph for: {', '.join(no_data_apps)}."
            )
        else:
            logger.info(f"App install statuses: {attempted} apps, all returned data")

        if skipped_types:
            logger.info(f"Skipped unsupported app types: {sorted(skipped_types)}")

    # ─────────────────────────────────────────────────────────────────────────
    # Per-app fetch helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _sync_device_statuses(self, app_id: str, app_type: str) -> bool:
        """
        Fetch per-device install status via /deviceStatuses (beta).

        No $select: the /deviceStatuses sub-resource is polymorphic across app
        types. Requesting specific fields (e.g. displayVersion, userPrincipalName)
        causes Graph to return HTTP 400 "InvalidQueryParameter" for types that
        don't declare those fields in their OData schema.

        Returns True if Graph returned any records, False otherwise.
        """
        try:
            endpoint = APP_DEVICE_STATUSES_TYPED.format(app_id=app_id, app_type=app_type)
            logger.info(f"  {app_type} {app_id[:8]}: GET beta/{endpoint}")

            # No params / no $select — same reason as mobileApps (polymorphic schema)
            statuses = self.client.get_all(endpoint, api_version="beta")

            if not statuses:
                logger.debug(f"  {app_type} {app_id[:8]}: /deviceStatuses — 0 records")
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
                raw_detail = f" — Graph: {e.raw}" if e.raw else ""
                logger.info(
                    f"  {app_type} {app_id[:8]}: /deviceStatuses HTTP {e.status_code}{raw_detail}"
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
        Fetch via /deviceInstallStates (Win32/MSI), no $select.
        Falls back to /deviceStatuses on HTTP 400.
        Returns True if any records were received, False otherwise.
        """
        try:
            endpoint = APP_WIN32_INSTALL_STATES_TYPED.format(app_id=app_id, app_type=app_type)
            logger.info(f"  {app_type} {app_id[:8]}: GET beta/{endpoint}")

            # No $select — see _sync_device_statuses docstring
            statuses = self.client.get_all(endpoint, api_version="beta")

            if not statuses:
                logger.debug(f"  {app_type} {app_id[:8]}: /deviceInstallStates — 0 records")
                return False

            saved = failed = 0
            for raw in statuses:
                if self._save_device_app_status(raw, app_id):
                    saved += 1
                else:
                    failed += 1
            logger.info(f"  {app_type} {app_id[:8]}: {saved} saved via /deviceInstallStates")
            return True

        except GraphError as e:
            if e.status_code == 400:
                raw_detail = f" — Graph: {e.raw}" if e.raw else ""
                logger.info(
                    f"  {app_type} {app_id[:8]}: /deviceInstallStates 400{raw_detail} — "
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
