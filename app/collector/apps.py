"""
app/collector/apps.py  --  v1.2.9

v1.2.9 fix:
    getDeviceInstallStatusReport: api_version changed from "v1.0" to "beta".
    The endpoint is beta-only; v1.0 returned:
      HTTP 400 "Resource not found for the segment 'getDeviceInstallStatusReport'"

v1.2.8 architecture (kept):
    Replaced deprecated /deviceStatuses and /deviceInstallStates (removed from
    Graph in May 2023, MC531735) with the Intune Reports API:
      POST /beta/deviceManagement/reports/getAppStatusOverviewReport
           -> KPI aggregates per app stored in App.raw_json["_install_overview"]
      POST /beta/deviceManagement/reports/getDeviceInstallStatusReport
           -> per-device rows stored in DeviceAppStatus table

    Both require DeviceManagementApps.Read.All (already in DEFAULT_SCOPES).

Previous fixes kept:
    v1.2.5  mobileApps via BETA API (all types visible)
    v1.2.4  $select removed from mobileApps (polymorphic collection)
    v1.2.3  per-record session_scope for FK-safe writes
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

    # -------------------------------------------------------------------------
    # Main sync entry point
    # -------------------------------------------------------------------------

    def sync_apps(self) -> int:
        logger.info("Syncing apps -- BETA API, no $select (all types)...")
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
                logger.error(f"  upsert failed {app_id}: {e}", exc_info=True)

        logger.info(
            f"Apps synced: {count} -- types: "
            + (", ".join(f"{t}={n}" for t, n in sorted(type_counts.items())) or "none")
        )
        self._sync_install_statuses_via_reports()
        return count

    # -------------------------------------------------------------------------
    # App metadata upsert
    # -------------------------------------------------------------------------

    def _upsert_app(self, raw: dict):
        app_id = raw.get("id", "")
        if not app_id:
            return
        with session_scope() as db:
            app = db.get(App, app_id) or App(id=app_id)
            odata = raw.get("@odata.type", "")
            app.app_type               = (odata.split(".")[-1].replace("#", "")
                                          if odata else (app.app_type or "unknown"))
            app.display_name           = raw.get("displayName", "")
            app.publisher              = raw.get("publisher", "")
            app.description            = raw.get("description", "")
            app.version                = str(raw.get("version", raw.get("displayVersion", "")))
            app.last_modified_datetime = _parse_dt(raw.get("lastModifiedDateTime"))
            app.is_assigned            = True
            app.raw_json               = json.dumps(raw)
            app.synced_at              = datetime.utcnow()
            db.merge(app)

    # -------------------------------------------------------------------------
    # Reports API orchestration
    # -------------------------------------------------------------------------

    def _sync_install_statuses_via_reports(self):
        """
        Fetch install status for every app via the Intune Reports API (beta).

        Step 1: getAppStatusOverviewReport -> KPI counts saved to App.raw_json
                Used as primary source for UI counters (always works per log).
        Step 2: getDeviceInstallStatusReport -> per-device rows to DeviceAppStatus
                Provides drill-down data and install log.
        """
        logger.info("Syncing app install statuses via Reports API (beta)...")

        with session_scope() as db:
            apps = [
                (a.id, a.app_type or "", a.display_name or "")
                for a in db.query(App).all()
            ]

        synced  = 0
        no_data = 0

        for app_id, app_type, app_name in apps:
            logger.info(f"  [{app_type}] {app_name!r} ({app_id[:8]}...)")

            overview = self._fetch_app_status_overview(app_id, app_type)
            if overview:
                self._save_app_overview(app_id, overview)

            rows = self._fetch_device_install_status(app_id, app_type)
            if rows:
                saved = sum(
                    1 for row in rows
                    if self._save_device_app_status(row, app_id)
                )
                logger.info(f"    per-device: {saved}/{len(rows)} saved")
                synced += 1
            else:
                no_data += 1

        logger.info(
            f"Reports API sync: {synced} apps with per-device data, "
            f"{no_data} with overview only or no data yet"
        )

    # -------------------------------------------------------------------------
    # Individual report calls
    # -------------------------------------------------------------------------

    def _call_report(self, endpoint: str, body: dict, api_version: str,
                     app_id: str, label: str) -> Optional[dict]:
        """
        POST to a Reports API endpoint and return the parsed response dict.
        The API responds with Content-Type: application/octet-stream even when
        the body is JSON; GraphClient.post() handles this transparently.
        """
        try:
            return self.client.post(endpoint, json=body, api_version=api_version)
        except GraphError as e:
            logger.warning(
                f"    {label} {app_id[:8]}: HTTP {e.status_code}: {e.raw or e}"
            )
            return None
        except Exception as e:
            logger.warning(f"    {label} {app_id[:8]}: error: {e}")
            return None

    def _fetch_app_status_overview(self, app_id: str, app_type: str) -> Optional[dict]:
        """
        POST /beta/deviceManagement/reports/getAppStatusOverviewReport
        {"filter": "(ApplicationId eq '{app_id}')"}

        Returns flat dict: ApplicationId, InstalledDeviceCount, FailedDeviceCount,
        PendingInstallDeviceCount, NotInstalledDeviceCount, NotApplicableDeviceCount
        """
        body = {"filter": f"(ApplicationId eq '{app_id}')"}
        resp = self._call_report(
            APP_STATUS_OVERVIEW_REPORT, body, "beta",
            app_id, "getAppStatusOverviewReport"
        )
        if resp is None:
            return None

        schema = resp.get("Schema", [])
        values = resp.get("Values", [])
        if not values:
            logger.info(f"    overview: no data yet for {app_id[:8]}")
            return None

        cols = [s["Column"] for s in schema]
        data = dict(zip(cols, values[0]))
        logger.info(
            f"    overview: "
            f"installed={data.get('InstalledDeviceCount', 0)} "
            f"failed={data.get('FailedDeviceCount', 0)} "
            f"pending={data.get('PendingInstallDeviceCount', 0)} "
            f"notInstalled={data.get('NotInstalledDeviceCount', 0)} "
            f"notApplicable={data.get('NotApplicableDeviceCount', 0)}"
        )
        return data

    def _fetch_device_install_status(self, app_id: str, app_type: str) -> list:
        """
        POST /beta/deviceManagement/reports/getDeviceInstallStatusReport
        {"filter": "(ApplicationId eq '{app_id}')", "top": 500}

        IMPORTANT: api_version="beta" — this endpoint does NOT exist on v1.0.

        Returns list of dicts with PascalCase columns:
            DeviceId, DeviceName, InstallState, ErrorCode,
            LastModifiedDateTime, UserName, UPN, Platform, AppVersion, ...
        """
        body = {
            "filter":  f"(ApplicationId eq '{app_id}')",
            "top":     500,
            "orderBy": [],
        }
        resp = self._call_report(
            APP_DEVICE_INSTALL_STATUS_REPORT, body, "beta",   # beta, NOT v1.0
            app_id, "getDeviceInstallStatusReport"
        )
        if resp is None:
            return []

        schema = resp.get("Schema", [])
        values = resp.get("Values", [])
        if not values:
            logger.info(f"    per-device: no rows for {app_id[:8]}")
            return []

        cols = [s["Column"] for s in schema]
        rows = [dict(zip(cols, row)) for row in values]
        logger.info(f"    per-device: {len(rows)} rows")
        return rows

    # -------------------------------------------------------------------------
    # DB writes
    # -------------------------------------------------------------------------

    def _save_app_overview(self, app_id: str, data: dict):
        """
        Store KPI counts in App.raw_json["_install_overview"].
        app_monitoring_queries reads this as primary source for UI counters,
        allowing the App Catalog to show numbers even before per-device sync.
        """
        try:
            with session_scope() as db:
                app = db.get(App, app_id)
                if app:
                    existing = json.loads(app.raw_json or "{}")
                    existing["_install_overview"] = data
                    app.raw_json  = json.dumps(existing)
                    app.synced_at = datetime.utcnow()
                    db.merge(app)
        except Exception as e:
            logger.debug(f"  App {app_id}: could not save overview: {e}")

    def _save_device_app_status(self, row: dict, app_id: str) -> bool:
        """
        Persist one device-app row from getDeviceInstallStatusReport.
        Own session_scope per record: FK errors don't abort the batch.

        Column mapping (Reports API PascalCase -> model):
            DeviceId              -> device_id
            DeviceName            -> device_name
            InstallState          -> install_state
            ErrorCode             -> error_code
            LastModifiedDateTime  -> last_sync_date_time
            UserName / UPN        -> user_name
        """
        device_id = row.get("DeviceId") or row.get("deviceId", "")
        if not device_id:
            logger.debug(f"  App {app_id}: row has no DeviceId: {row}")
            return False
        try:
            with session_scope() as db:
                existing = db.query(DeviceAppStatus).filter(
                    DeviceAppStatus.device_id == device_id,
                    DeviceAppStatus.app_id    == app_id,
                ).first()

                s = existing or DeviceAppStatus()
                s.device_id  = device_id
                s.app_id     = app_id
                s.install_state = (
                    row.get("InstallState")
                    or row.get("installState")
                    or "unknown"
                )
                s.error_code = row.get("ErrorCode") or row.get("errorCode")
                s.last_sync_date_time = _parse_dt(
                    row.get("LastModifiedDateTime")
                    or row.get("lastSyncDateTime")
                )
                s.device_name = row.get("DeviceName") or row.get("deviceName", "")
                s.user_name   = (
                    row.get("UserName")
                    or row.get("UPN")
                    or row.get("userName", "")
                )
                s.raw_json  = json.dumps(row)
                s.synced_at = datetime.utcnow()
                if not existing:
                    db.add(s)
            return True
        except Exception as e:
            logger.debug(
                f"  App {app_id}: cannot save {device_id}: "
                f"{type(e).__name__}: {e}"
            )
            return False
