"""
app/analytics/app_monitoring_queries.py

Dedicated query layer for the App Monitoring page.
All functions return plain dicts/lists — no SQLAlchemy objects exposed to UI.

Queries:
  get_app_monitoring_kpis()       — top-level KPI cards
  get_app_install_summary()       — per-app aggregated state counts
  get_all_install_records()       — flat table: device × app × state
  get_device_installs_for_app()   — drill-down: all devices for one app
  get_app_error_analysis()        — error code clustering with descriptions
  get_install_trend_by_state()    — state distribution across all apps
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, desc, case, and_, or_

from app.db.database import session_scope
from app.db.models import App, DeviceAppStatus, Device

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Win32 / Intune error code catalogue
# Source: Microsoft docs + common field observations
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
    -2016281112: "MDM enrollment issue affecting app delivery",
    -2016330008: "Sync failed — device offline or unreachable",
    -2147024891: "Access denied (0x80070005)",
    -2147024773: "File not found (0x8007007B)",
    -2147024809: "Invalid data / corrupted download",
}


def _hex(code: int | None) -> str:
    if code is None:
        return "—"
    try:
        val = int(code)
        # Normalise to unsigned 32-bit for display
        if val < 0:
            val = val & 0xFFFFFFFF
        return f"0x{val:08X}"
    except Exception:
        return str(code)


def _err_desc(code: int | None) -> str:
    if code is None:
        return ""
    try:
        val = int(code)
    except Exception:
        return ""
    return ERROR_CATALOGUE.get(val, ERROR_CATALOGUE.get(val & 0xFFFFFFFF, "Unknown error"))


def _fmt_dt(val) -> str:
    if val is None:
        return "—"
    if isinstance(val, str):
        try:
            val = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return val
    try:
        return val.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(val)


# ─────────────────────────────────────────────────────────────────────────────
# KPI cards
# ─────────────────────────────────────────────────────────────────────────────

def get_app_monitoring_kpis() -> dict[str, Any]:
    """
    Returns top-level counters for the KPI cards.
    """
    with session_scope() as db:
        total_apps = db.query(func.count(App.id)).scalar() or 0

        # Apps that have at least one install record
        apps_with_data = db.query(func.count(DeviceAppStatus.app_id.distinct())).scalar() or 0

        installed = (
            db.query(func.count(DeviceAppStatus.id))
            .filter(DeviceAppStatus.install_state == "installed")
            .scalar() or 0
        )
        failed = (
            db.query(func.count(DeviceAppStatus.id))
            .filter(DeviceAppStatus.install_state == "failed")
            .scalar() or 0
        )
        pending = (
            db.query(func.count(DeviceAppStatus.id))
            .filter(DeviceAppStatus.install_state.in_(["pendingInstall", "pendinginstall"]))
            .scalar() or 0
        )
        not_installed = (
            db.query(func.count(DeviceAppStatus.id))
            .filter(DeviceAppStatus.install_state.in_(["notInstalled", "notinstalled"]))
            .scalar() or 0
        )
        total_records = (
            db.query(func.count(DeviceAppStatus.id)).scalar() or 0
        )

        # Apps with ≥1 failure
        apps_with_failures = (
            db.query(func.count(DeviceAppStatus.app_id.distinct()))
            .filter(DeviceAppStatus.install_state == "failed")
            .scalar() or 0
        )

        # Devices with ≥1 failure
        devices_with_failures = (
            db.query(func.count(DeviceAppStatus.device_id.distinct()))
            .filter(DeviceAppStatus.install_state == "failed")
            .scalar() or 0
        )

        install_rate = round((installed / total_records * 100), 1) if total_records else 0

    return {
        "total_apps": total_apps,
        "apps_with_data": apps_with_data,
        "total_records": total_records,
        "installed": installed,
        "failed": failed,
        "pending": pending,
        "not_installed": not_installed,
        "apps_with_failures": apps_with_failures,
        "devices_with_failures": devices_with_failures,
        "install_rate": install_rate,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-app aggregated summary
# ─────────────────────────────────────────────────────────────────────────────

def get_app_install_summary() -> list[dict]:
    """
    One row per app showing installed / failed / pending / not_installed counts
    and a success rate percentage.
    """
    with session_scope() as db:
        apps = db.query(App).order_by(App.display_name).all()
        result = []

        for app in apps:
            statuses = (
                db.query(DeviceAppStatus.install_state, func.count(DeviceAppStatus.id))
                .filter(DeviceAppStatus.app_id == app.id)
                .group_by(DeviceAppStatus.install_state)
                .all()
            )
            counts: dict[str, int] = {}
            for state, cnt in statuses:
                counts[str(state).lower()] = cnt

            installed    = counts.get("installed", 0)
            failed       = counts.get("failed", 0)
            pending      = counts.get("pendinginstall", 0) + counts.get("pending", 0)
            not_inst     = counts.get("notinstalled", 0) + counts.get("not installed", 0)
            total        = sum(counts.values())
            success_rate = round(installed / total * 100, 1) if total else None

            result.append({
                "id":           app.id,
                "display_name": app.display_name or "—",
                "app_type":     app.app_type or "—",
                "publisher":    app.publisher or "—",
                "installed":    installed,
                "failed":       failed,
                "pending":      pending,
                "not_installed": not_inst,
                "total_devices": total,
                "success_rate": f"{success_rate}%" if success_rate is not None else "—",
                "last_modified": _fmt_dt(app.last_modified_datetime),
                "is_assigned":  "Yes" if app.is_assigned else "No",
            })

        return result


# ─────────────────────────────────────────────────────────────────────────────
# Flat install records table
# ─────────────────────────────────────────────────────────────────────────────

def get_all_install_records(
    state_filter: str = "",
    app_id_filter: str = "",
    limit: int = 2000,
) -> list[dict]:
    """
    Flat device × app × state table.
    Optional filters: state_filter='failed', app_id_filter='<guid>'.
    """
    with session_scope() as db:
        q = (
            db.query(DeviceAppStatus, App, Device)
            .join(App, App.id == DeviceAppStatus.app_id, isouter=True)
            .join(Device, Device.id == DeviceAppStatus.device_id, isouter=True)
        )
        if state_filter:
            q = q.filter(DeviceAppStatus.install_state.ilike(f"%{state_filter}%"))
        if app_id_filter:
            q = q.filter(DeviceAppStatus.app_id == app_id_filter)

        q = q.order_by(
            DeviceAppStatus.install_state,
            App.display_name,
        ).limit(limit)

        rows = q.all()
        result = []
        for das, app, dev in rows:
            result.append({
                "app_name":     (app.display_name if app else None) or "—",
                "app_type":     (app.app_type if app else None) or "—",
                "device_name":  das.device_name or (dev.device_name if dev else None) or "—",
                "user":         das.user_name or (dev.user_principal_name if dev else None) or "—",
                "os":           (dev.operating_system if dev else None) or "—",
                "install_state": das.install_state or "unknown",
                "error_code":   _hex(das.error_code),
                "error_desc":   _err_desc(das.error_code),
                "last_sync":    _fmt_dt(das.last_sync_date_time),
                # hidden keys for export / drill-down
                "_app_id":      das.app_id,
                "_device_id":   das.device_id,
                "_error_code_raw": das.error_code,
            })
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Drill-down: all device records for one app
# ─────────────────────────────────────────────────────────────────────────────

def get_device_installs_for_app(app_id: str) -> list[dict]:
    """All device install records for a specific app, with device metadata."""
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
                "device_name":   das.device_name or (dev.device_name if dev else None) or "—",
                "user":          das.user_name or (dev.user_principal_name if dev else None) or "—",
                "os":            (dev.operating_system if dev else None) or "—",
                "os_version":    (dev.os_version if dev else None) or "—",
                "ownership":     (dev.ownership if dev else None) or "—",
                "compliance":    (dev.compliance_state if dev else None) or "—",
                "install_state": das.install_state or "unknown",
                "error_code":    _hex(das.error_code),
                "error_desc":    _err_desc(das.error_code),
                "last_sync":     _fmt_dt(das.last_sync_date_time),
                "_device_id":    das.device_id,
                "_error_code_raw": das.error_code,
            })
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Error analysis
# ─────────────────────────────────────────────────────────────────────────────

def get_app_error_analysis() -> list[dict]:
    """
    Error codes ranked by frequency, with human-readable descriptions
    and the list of affected apps and devices.
    """
    with session_scope() as db:
        rows = (
            db.query(
                DeviceAppStatus.error_code,
                func.count(DeviceAppStatus.device_id.distinct()).label("device_count"),
                func.count(DeviceAppStatus.app_id.distinct()).label("app_count"),
            )
            .filter(
                DeviceAppStatus.install_state == "failed",
                DeviceAppStatus.error_code.isnot(None),
                DeviceAppStatus.error_code != 0,
            )
            .group_by(DeviceAppStatus.error_code)
            .order_by(desc("device_count"))
            .limit(50)
            .all()
        )

        result = []
        for code, device_count, app_count in rows:
            # Get top 3 affected apps for this error
            affected_apps = (
                db.query(App.display_name)
                .join(DeviceAppStatus, DeviceAppStatus.app_id == App.id)
                .filter(
                    DeviceAppStatus.error_code == code,
                    DeviceAppStatus.install_state == "failed",
                )
                .group_by(App.id)
                .order_by(desc(func.count(DeviceAppStatus.id)))
                .limit(3)
                .all()
            )
            app_names = ", ".join(r[0] for r in affected_apps if r[0])

            result.append({
                "error_code":    _hex(code),
                "description":   _err_desc(code),
                "device_count":  device_count,
                "app_count":     app_count,
                "affected_apps": app_names or "—",
                "severity":      _severity(code),
                "_error_code_raw": code,
            })
        return result


def _severity(code: int | None) -> str:
    """Rough severity bucket for colour coding."""
    if code is None:
        return "unknown"
    try:
        val = int(code) & 0xFFFFFFFF
    except Exception:
        return "unknown"
    known_ok   = {0, 3010, 1641}
    known_high = {1603, 2147942405, 2147946280, 2147946281, 2147946282, 2147946284}
    if val in known_ok:
        return "ok"
    if val in known_high:
        return "high"
    return "medium"


# ─────────────────────────────────────────────────────────────────────────────
# State distribution (for overview bar)
# ─────────────────────────────────────────────────────────────────────────────

def get_install_state_distribution() -> list[dict]:
    """Returns [{state, count}] sorted descending — used for the overview bar."""
    with session_scope() as db:
        rows = (
            db.query(DeviceAppStatus.install_state, func.count(DeviceAppStatus.id))
            .group_by(DeviceAppStatus.install_state)
            .order_by(desc(func.count(DeviceAppStatus.id)))
            .all()
        )
        return [{"state": (r[0] or "unknown"), "count": r[1]} for r in rows]
