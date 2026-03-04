"""
app/analytics/app_monitoring_queries.py

Dedicated query layer for the App Monitoring page.
All functions return plain dicts/lists — no SQLAlchemy objects exposed to UI.

Queries:
  get_app_monitoring_kpis()        — top-level KPI cards
  get_app_install_summary()        — per-app aggregated state counts
  get_all_install_records()        — flat table: device x app x state
  get_device_installs_for_app()    — drill-down: all devices for one app
  get_app_error_analysis()         — error code clustering with descriptions
  get_install_state_distribution() — state distribution across all apps

v1.3.0:
  get_all_install_records() and get_device_installs_for_app() now fall back
  to synthetic rows derived from App.raw_json["_install_overview"] when
  DeviceAppStatus is empty (i.e. getDeviceInstallStatusReport is unavailable
  for this tenant). Synthetic rows carry "_source": "overview" to let the UI
  show an appropriate banner.

v1.2.9:
  get_app_install_summary() and get_app_monitoring_kpis() now use
  App.raw_json["_install_overview"] (saved by AppCollector.sync_apps via
  getAppStatusOverviewReport) as the primary source for install counts.
  DeviceAppStatus is used for per-device drill-down and install log only.

  This ensures the App Catalog shows correct numbers immediately after sync,
  even before getDeviceInstallStatusReport populates DeviceAppStatus.

  Overview keys from Graph:
    InstalledDeviceCount, FailedDeviceCount, PendingInstallDeviceCount,
    NotInstalledDeviceCount, NotApplicableDeviceCount

v1.2.2:
  State comparisons case-insensitive; Graph variant spellings handled:
    "success" -> installed, "installfailed" -> failed, etc.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, desc, case, and_, or_

from app.db.database import session_scope
from app.db.models import App, DeviceAppStatus, Device

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Canonical state buckets (lower-case; matched via func.lower() in queries)
# ─────────────────────────────────────────────────────────────────────────────

_INSTALLED_STATES     = ["installed", "success"]
_FAILED_STATES        = ["failed", "installfailed", "uninstallfailed"]
_PENDING_STATES       = ["pendinginstall", "pending", "downloading", "installing"]
_NOT_INSTALLED_STATES = ["notinstalled", "not installed", "notapplicable", "excluded"]


# ─────────────────────────────────────────────────────────────────────────────
# Win32 / Intune error code catalogue
# ─────────────────────────────────────────────────────────────────────────────

ERROR_CATALOGUE: dict[int, str] = {
    0:           "Success",
    87:          "Invalid parameter passed to installer",
    1460:        "Timeout waiting for install",
    1602:        "User cancelled installation",
    1603:        "Fatal error during installation (MSI)",
    1618:        "Another installation already in progress",
    1633:        "Platform not supported by installer",
    1638:        "Another version of this product is already installed",
    1641:        "Installer initiated reboot — success after restart",
    2147500053:  "Application blocked by policy",
    2147942405:  "Access denied — insufficient privileges",
    2147942487:  "Not enough disk space",
    2147946279:  "Dependency not met",
    2147946280:  "Content download failed",
    2147946281:  "Detection rule did not match after install",
    2147946282:  "Install command failed (non-zero exit code)",
    2147946283:  "Timeout — device did not check in within window",
    2147946284:  "Script execution failed",
    2147946285:  "Reboot pending — install blocked",
    2149842944:  "App marked as superseded — skipped",
    3010:        "Success — reboot required to complete",
    -2016281112: "MDM enrollment or policy issue affecting app delivery",
    -2016330008: "Sync failed — device offline or unreachable",
    -2147024891: "Access denied (0x80070005)",
    -2147024773: "File not found (0x8007007B)",
    -2147024809: "The parameter is incorrect (0x80070057)",
    -2016345106: "Content not found — check app content / supersedence",
    -2016330860: "Application not applicable to this device",
}


def _err_desc(code: int | None) -> str:
    if code is None:
        return "—"
    try:
        val = int(code)
        if val in ERROR_CATALOGUE:
            return ERROR_CATALOGUE[val]
        unsigned = val & 0xFFFFFFFF
        if unsigned in ERROR_CATALOGUE:
            return ERROR_CATALOGUE[unsigned]
        return "Unknown error code"
    except Exception:
        return "—"


def _hex(code: int | None) -> str:
    if code is None:
        return "—"
    try:
        return f"0x{int(code) & 0xFFFFFFFF:08X}"
    except Exception:
        return str(code)


def _fmt_dt(val) -> str:
    if val is None:
        return "—"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M")
    return str(val)[:19]


def _read_overview(raw_json: str | None) -> dict:
    """
    Extract _install_overview from App.raw_json.
    Returns empty dict if not present.
    """
    if not raw_json:
        return {}
    try:
        return json.loads(raw_json).get("_install_overview") or {}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# KPI summary
# ─────────────────────────────────────────────────────────────────────────────

def get_app_monitoring_kpis() -> dict[str, Any]:
    """
    Top-level KPI numbers for the App Monitoring overview.

    Primary source: App.raw_json["_install_overview"] (from Reports API).
    This is always populated after sync, even if DeviceAppStatus is empty.
    """
    with session_scope() as db:
        apps = db.query(App).all()
        total_apps = len(apps)

        installed = failed = pending = not_installed = 0
        devices_with_failures: set[str] = set()

        for app in apps:
            ov = _read_overview(app.raw_json)
            if ov:
                installed     += ov.get("InstalledDeviceCount", 0) or 0
                f              = ov.get("FailedDeviceCount", 0) or 0
                failed        += f
                pending       += ov.get("PendingInstallDeviceCount", 0) or 0
                not_installed += ov.get("NotInstalledDeviceCount", 0) or 0
                if f > 0:
                    devices_with_failures.add(app.id)

        total_tracked = installed + failed + pending + not_installed
        install_rate = (
            round(100 * installed / total_tracked)
            if total_tracked > 0
            else 0
        )

        return {
            "total_apps":           total_apps,
            "installed":            installed,
            "failed":               failed,
            "pending":              pending,
            "not_installed":        not_installed,
            "install_rate":         install_rate,
            "devices_with_failures": len(devices_with_failures),
        }


# ─────────────────────────────────────────────────────────────────────────────
# App Catalog: per-app aggregated counts
# ─────────────────────────────────────────────────────────────────────────────

def get_app_install_summary() -> list[dict]:
    """
    One row per app with aggregated install state counts.

    Primary source: App.raw_json["_install_overview"].
    Falls back to DeviceAppStatus aggregation for backwards compat / demo mode.
    """
    with session_scope() as db:
        apps = db.query(App).order_by(App.display_name).all()
        result = []

        for app in apps:
            ov = _read_overview(app.raw_json)

            if ov:
                installed     = ov.get("InstalledDeviceCount",     0) or 0
                failed        = ov.get("FailedDeviceCount",         0) or 0
                pending       = ov.get("PendingInstallDeviceCount", 0) or 0
                not_installed = ov.get("NotInstalledDeviceCount",   0) or 0
                not_applicable = ov.get("NotApplicableDeviceCount", 0) or 0
                total = installed + failed + pending + not_installed + not_applicable
            else:
                # Fallback: aggregate DeviceAppStatus
                rows = (
                    db.query(
                        func.lower(DeviceAppStatus.install_state).label("state"),
                        func.count(DeviceAppStatus.id).label("cnt"),
                    )
                    .filter(DeviceAppStatus.app_id == app.id)
                    .group_by(func.lower(DeviceAppStatus.install_state))
                    .all()
                )
                counts: dict[str, int] = {}
                for state, cnt in rows:
                    counts[state or "unknown"] = cnt
                installed     = sum(counts.get(s, 0) for s in _INSTALLED_STATES)
                failed        = sum(counts.get(s, 0) for s in _FAILED_STATES)
                pending       = sum(counts.get(s, 0) for s in _PENDING_STATES)
                not_installed = sum(counts.get(s, 0) for s in _NOT_INSTALLED_STATES)
                total = sum(counts.values())

            total_devices = installed + failed + pending + not_installed
            success_rate  = (
                f"{round(100 * installed / total_devices)}%"
                if total_devices > 0
                else "—"
            )

            try:
                rj = json.loads(app.raw_json) if app.raw_json else {}
            except Exception:
                rj = {}

            result.append({
                "id":           app.id,
                "display_name": app.display_name or "—",
                "app_type":     app.app_type     or "—",
                "publisher":    rj.get("publisher") or "—",
                "installed":    installed,
                "failed":       failed,
                "pending":      pending,
                "not_installed": not_installed,
                "success_rate": success_rate,
                "total_devices": total_devices,
                "is_assigned":  "Yes" if rj.get("isAssigned") else "No",
                "last_modified": _fmt_dt(app.last_modified_datetime),
            })

        return result


# ─────────────────────────────────────────────────────────────────────────────
# Install Log: flat device × app × state table
# ─────────────────────────────────────────────────────────────────────────────

def get_all_install_records(
    state_filter: str = "",
    app_id_filter: str = "",
    limit: int = 2000,
) -> list[dict]:
    """
    Flat install log.

    Primary source: DeviceAppStatus (populated by getDeviceInstallStatusReport).
    Fallback: synthesize rows from App.raw_json["_install_overview"] when
    DeviceAppStatus is empty (Reports API beta endpoint unavailable for tenant).

    Synthetic rows carry "_source": "overview" and "_synthetic": True so the
    UI can display an appropriate banner.
    """
    logger.info(
        f"Install log query: state_filter={state_filter!r} "
        f"app_id_filter={app_id_filter!r} limit={limit}"
    )
    with session_scope() as db:
        q = (
            db.query(DeviceAppStatus, App, Device)
            .join(App,    App.id    == DeviceAppStatus.app_id,    isouter=True)
            .join(Device, Device.id == DeviceAppStatus.device_id, isouter=True)
        )
        if state_filter:
            q = q.filter(DeviceAppStatus.install_state.ilike(f"%{state_filter}%"))
        if app_id_filter:
            q = q.filter(DeviceAppStatus.app_id == app_id_filter)

        q = q.order_by(DeviceAppStatus.install_state, App.display_name).limit(limit)
        rows = q.all()

        result = []
        for das, app, dev in rows:
            result.append({
                "app_name":        (app.display_name if app else None) or "—",
                "app_type":        (app.app_type     if app else None) or "—",
                "device_name":     das.device_name or (dev.device_name if dev else None) or "—",
                "user":            das.user_name  or (dev.user_principal_name if dev else None) or "—",
                "os":              (dev.operating_system if dev else None) or "—",
                "install_state":   das.install_state or "unknown",
                "error_code":      _hex(das.error_code),
                "error_desc":      _err_desc(das.error_code),
                "last_sync":       _fmt_dt(das.last_sync_date_time),
                "_app_id":         das.app_id,
                "_device_id":      das.device_id,
                "_error_code_raw": das.error_code,
                "_source":         "per-device",
                "_synthetic":      False,
            })
        logger.info(f"Install log query: {len(result)} records returned")

    # ── Fallback to overview when DeviceAppStatus is empty ────────────────────
    if not result:
        logger.info("Install log: DeviceAppStatus empty — falling back to overview data")
        result = _get_install_records_from_overview(state_filter, app_id_filter)

    return result


def _get_install_records_from_overview(
    state_filter: str = "",
    app_id_filter: str = "",
) -> list[dict]:
    """
    Synthesize install-log rows from App.raw_json["_install_overview"].

    Each (app, state bucket) with count > 0 produces one row.
    The "device_name" column shows the bucket count (e.g. "3 devices").
    All rows carry _synthetic=True so the UI can show a data-source banner.
    """
    _BUCKET_MAP = [
        ("InstalledDeviceCount",        "installed"),
        ("FailedDeviceCount",           "failed"),
        ("PendingInstallDeviceCount",   "pendingInstall"),
        ("NotInstalledDeviceCount",     "notInstalled"),
        ("NotApplicableDeviceCount",    "notApplicable"),
    ]

    result = []
    with session_scope() as db:
        apps = db.query(App).order_by(App.display_name).all()
        for app in apps:
            if app_id_filter and app.id != app_id_filter:
                continue
            ov = _read_overview(app.raw_json)
            if not ov:
                continue
            for graph_key, state_label in _BUCKET_MAP:
                count = ov.get(graph_key, 0) or 0
                if count == 0:
                    continue
                if state_filter and state_filter.lower() not in state_label.lower():
                    continue
                result.append({
                    "app_name":    app.display_name or "—",
                    "app_type":    app.app_type     or "—",
                    "device_name": f"{count} device{'s' if count != 1 else ''}",
                    "user":        "—",
                    "os":          "—",
                    "install_state": state_label,
                    "error_code":  "—",
                    "error_desc":  "Per-device data unavailable (Reports API beta endpoint not supported by tenant)",
                    "last_sync":   "—",
                    "_app_id":     app.id,
                    "_device_id":  None,
                    "_error_code_raw": None,
                    "_source":     "overview",
                    "_synthetic":  True,
                })

    logger.info(f"Install log fallback: {len(result)} synthetic rows from overview")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Drill-down: all device records for one app
# ─────────────────────────────────────────────────────────────────────────────

def get_device_installs_for_app(app_id: str) -> list[dict]:
    """
    All device install records for a specific app, with device metadata.

    Primary source: DeviceAppStatus.
    Fallback: synthesize from _install_overview when DeviceAppStatus is empty.
    Synthetic rows carry "_synthetic": True.
    """
    logger.info(f"Drill-down: loading device installs for app_id={app_id}")
    with session_scope() as db:
        rows = (
            db.query(DeviceAppStatus, Device)
            .join(Device, Device.id == DeviceAppStatus.device_id, isouter=True)
            .filter(DeviceAppStatus.app_id == app_id)
            .order_by(DeviceAppStatus.install_state, Device.device_name)
            .all()
        )
        result = []
        for das, dev in rows:
            result.append({
                "device_name":     das.device_name or (dev.device_name if dev else None) or "—",
                "user":            das.user_name  or (dev.user_principal_name if dev else None) or "—",
                "os":              (dev.operating_system if dev else None) or "—",
                "os_version":      (dev.os_version       if dev else None) or "—",
                "ownership":       (dev.ownership        if dev else None) or "—",
                "compliance":      (dev.compliance_state  if dev else None) or "—",
                "install_state":   das.install_state or "unknown",
                "error_code":      _hex(das.error_code),
                "error_desc":      _err_desc(das.error_code),
                "last_sync":       _fmt_dt(das.last_sync_date_time),
                "_device_id":      das.device_id,
                "_error_code_raw": das.error_code,
                "_synthetic":      False,
            })
    logger.info(f"Drill-down: {len(result)} records returned for app_id={app_id}")

    # ── Fallback ──────────────────────────────────────────────────────────────
    if not result:
        logger.info(f"Drill-down: no DeviceAppStatus rows — falling back to overview for {app_id}")
        result = _get_device_overview_for_app(app_id)

    return result


def _get_device_overview_for_app(app_id: str) -> list[dict]:
    """
    Synthesize drill-down rows from _install_overview for one app.
    One row per non-zero state bucket.
    """
    _BUCKET_MAP = [
        ("InstalledDeviceCount",        "installed"),
        ("FailedDeviceCount",           "failed"),
        ("PendingInstallDeviceCount",   "pendingInstall"),
        ("NotInstalledDeviceCount",     "notInstalled"),
        ("NotApplicableDeviceCount",    "notApplicable"),
    ]

    with session_scope() as db:
        app = db.query(App).filter(App.id == app_id).first()
        if not app:
            return []
        ov = _read_overview(app.raw_json)
        if not ov:
            return []

        result = []
        for graph_key, state_label in _BUCKET_MAP:
            count = ov.get(graph_key, 0) or 0
            if count == 0:
                continue
            result.append({
                "device_name":   f"{count} device{'s' if count != 1 else ''}",
                "user":          "—",
                "os":            "—",
                "os_version":    "—",
                "ownership":     "—",
                "compliance":    "—",
                "install_state": state_label,
                "error_code":    "—",
                "error_desc":    "Aggregated overview only — per-device data unavailable",
                "last_sync":     "—",
                "_device_id":    None,
                "_error_code_raw": None,
                "_synthetic":    True,
            })
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Error analysis
# ─────────────────────────────────────────────────────────────────────────────

def get_app_error_analysis() -> list[dict]:
    """
    Error codes ranked by frequency, with human-readable descriptions
    and the list of affected apps and devices.

    Returns empty list when DeviceAppStatus has no failed records (e.g. when
    getDeviceInstallStatusReport is not available for the tenant).
    """
    with session_scope() as db:
        rows = (
            db.query(
                DeviceAppStatus.error_code,
                func.count(DeviceAppStatus.id).label("device_count"),
                func.count(func.distinct(DeviceAppStatus.app_id)).label("app_count"),
            )
            .filter(
                DeviceAppStatus.error_code.isnot(None),
                DeviceAppStatus.error_code != 0,
            )
            .group_by(DeviceAppStatus.error_code)
            .order_by(desc("device_count"))
            .limit(50)
            .all()
        )

        result = []
        for error_code, device_count, app_count in rows:
            desc_str = _err_desc(error_code)
            hex_code = _hex(error_code)

            # Top affected apps
            affected = (
                db.query(App.display_name)
                .join(DeviceAppStatus, DeviceAppStatus.app_id == App.id)
                .filter(DeviceAppStatus.error_code == error_code)
                .group_by(App.id, App.display_name)
                .order_by(desc(func.count(DeviceAppStatus.id)))
                .limit(3)
                .all()
            )
            affected_str = ", ".join(a[0] or "—" for a in affected)

            severity = (
                "high"   if device_count >= 5 else
                "medium" if device_count >= 2 else
                "ok"
            )

            result.append({
                "error_code":    hex_code,
                "description":   desc_str,
                "device_count":  device_count,
                "app_count":     app_count,
                "severity":      severity,
                "affected_apps": affected_str,
                "_error_code_raw": error_code,
            })

        return result


# ─────────────────────────────────────────────────────────────────────────────
# Install state distribution (for Overview bar)
# ─────────────────────────────────────────────────────────────────────────────

def get_install_state_distribution() -> list[dict]:
    """
    Aggregate install state counts across all apps for the state bar.

    Primary source: App.raw_json["_install_overview"].
    """
    _BUCKET_MAP = [
        ("InstalledDeviceCount",        "installed"),
        ("FailedDeviceCount",           "failed"),
        ("PendingInstallDeviceCount",   "pendingInstall"),
        ("NotInstalledDeviceCount",     "notInstalled"),
        ("NotApplicableDeviceCount",    "notApplicable"),
    ]

    totals: dict[str, int] = {label: 0 for _, label in _BUCKET_MAP}

    with session_scope() as db:
        apps = db.query(App).all()
        has_overview = False

        for app in apps:
            ov = _read_overview(app.raw_json)
            if ov:
                has_overview = True
                for graph_key, label in _BUCKET_MAP:
                    totals[label] += ov.get(graph_key, 0) or 0

        # Fallback to DeviceAppStatus if no overview data at all
        if not has_overview:
            rows = (
                db.query(
                    func.lower(DeviceAppStatus.install_state).label("state"),
                    func.count(DeviceAppStatus.id).label("cnt"),
                )
                .group_by(func.lower(DeviceAppStatus.install_state))
                .all()
            )
            for state, cnt in rows:
                if state in _INSTALLED_STATES:
                    totals["installed"] += cnt
                elif state in _FAILED_STATES:
                    totals["failed"] += cnt
                elif state in _PENDING_STATES:
                    totals["pendingInstall"] += cnt
                else:
                    totals["notInstalled"] += cnt

    return [
        {"state": label, "count": count}
        for _, label in _BUCKET_MAP
        for count in [totals[label]]
        if count > 0
    ]
