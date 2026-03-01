"""
Query/analytics layer - provides high-level data access functions.
The UI calls these functions; it never accesses the DB directly.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, and_, or_, desc, text
from sqlalchemy.orm import Session

from app.db.database import session_scope, get_session
from app.db.models import (
    Device, Control, Assignment, Outcome, App, DeviceAppStatus,
    Group, SyncLog, DeviceComplianceStatus, Snapshot, DriftReport,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Overview KPIs
# ---------------------------------------------------------------------------
def get_overview_kpis() -> dict[str, Any]:
    with session_scope() as db:
        total_devices = db.query(func.count(Device.id)).scalar() or 0
        compliant = db.query(func.count(Device.id)).filter(Device.compliance_state == "compliant").scalar() or 0
        noncompliant = db.query(func.count(Device.id)).filter(Device.compliance_state == "noncompliant").scalar() or 0
        unknown = total_devices - compliant - noncompliant

        total_controls = db.query(func.count(Control.id)).scalar() or 0
        total_apps = db.query(func.count(App.id)).scalar() or 0
        failed_apps = db.query(func.count(DeviceAppStatus.id)).filter(
            DeviceAppStatus.install_state == "failed"
        ).scalar() or 0

        last_sync = db.query(SyncLog).order_by(desc(SyncLog.finished_at)).first()
        last_sync_time = last_sync.finished_at if last_sync else None
        last_sync_status = last_sync.status if last_sync else "never"

        return {
            "total_devices": total_devices,
            "compliant": compliant,
            "noncompliant": noncompliant,
            "unknown": unknown,
            "total_controls": total_controls,
            "total_apps": total_apps,
            "failed_apps": failed_apps,
            "last_sync_time": last_sync_time,
            "last_sync_status": last_sync_status,
        }


def get_compliance_breakdown() -> list[dict]:
    """Returns list of {state, count} for pie chart."""
    with session_scope() as db:
        rows = db.query(Device.compliance_state, func.count(Device.id)).group_by(Device.compliance_state).all()
        return [{"state": r[0] or "unknown", "count": r[1]} for r in rows]


def get_os_breakdown() -> list[dict]:
    with session_scope() as db:
        rows = db.query(Device.operating_system, func.count(Device.id)).group_by(Device.operating_system).all()
        return [{"os": r[0] or "unknown", "count": r[1]} for r in rows]


# ---------------------------------------------------------------------------
# Device queries
# ---------------------------------------------------------------------------
def get_devices(
    search: str = "",
    compliance_filter: str = "",
    os_filter: str = "",
    ownership_filter: str = "",
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    with session_scope() as db:
        q = db.query(Device)
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                Device.device_name.ilike(like),
                Device.serial_number.ilike(like),
                Device.user_principal_name.ilike(like),
                Device.id.ilike(like),
            ))
        if compliance_filter:
            q = q.filter(Device.compliance_state == compliance_filter)
        if os_filter:
            q = q.filter(Device.operating_system.ilike(f"%{os_filter}%"))
        if ownership_filter:
            q = q.filter(Device.ownership == ownership_filter)

        q = q.order_by(Device.device_name).limit(limit).offset(offset)
        return [_device_to_dict(d) for d in q.all()]


def get_device_by_id(device_id: str) -> dict | None:
    with session_scope() as db:
        d = db.get(Device, device_id)
        return _device_to_dict(d) if d else None


def get_device_count(search: str = "", compliance_filter: str = "", os_filter: str = "") -> int:
    with session_scope() as db:
        q = db.query(func.count(Device.id))
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                Device.device_name.ilike(like),
                Device.serial_number.ilike(like),
                Device.user_principal_name.ilike(like),
            ))
        if compliance_filter:
            q = q.filter(Device.compliance_state == compliance_filter)
        if os_filter:
            q = q.filter(Device.operating_system.ilike(f"%{os_filter}%"))
        return q.scalar() or 0


# ---------------------------------------------------------------------------
# Control/Policy queries
# ---------------------------------------------------------------------------
def get_controls(
    search: str = "",
    control_type: str = "",
    platform: str = "",
    limit: int = 500,
) -> list[dict]:
    with session_scope() as db:
        q = db.query(Control)
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                Control.display_name.ilike(like),
                Control.id.ilike(like),
            ))
        if control_type:
            q = q.filter(Control.control_type == control_type)
        if platform:
            q = q.filter(Control.platform.ilike(f"%{platform}%"))
        q = q.order_by(Control.display_name).limit(limit)
        return [_control_to_dict(c) for c in q.all()]


def get_control_by_id(control_id: str) -> dict | None:
    with session_scope() as db:
        c = db.get(Control, control_id)
        return _control_to_dict(c) if c else None


def get_assignments_for_control(control_id: str) -> list[dict]:
    with session_scope() as db:
        rows = db.query(Assignment).filter(Assignment.control_id == control_id).all()
        return [_assignment_to_dict(a) for a in rows]


def get_controls_for_group(group_id: str) -> list[dict]:
    """Find all controls assigned to a specific group."""
    with session_scope() as db:
        rows = db.query(Control).join(
            Assignment, Assignment.control_id == Control.id
        ).filter(
            Assignment.target_id == group_id,
            Assignment.target_type == "group",
        ).all()
        return [_control_to_dict(c) for c in rows]


# ---------------------------------------------------------------------------
# App queries
# ---------------------------------------------------------------------------
def get_apps(search: str = "", limit: int = 200) -> list[dict]:
    with session_scope() as db:
        q = db.query(App)
        if search:
            like = f"%{search}%"
            q = q.filter(or_(App.display_name.ilike(like), App.publisher.ilike(like)))
        q = q.order_by(App.display_name).limit(limit)
        return [_app_to_dict(a) for a in q.all()]


def get_app_failures_summary(limit: int = 20) -> list[dict]:
    """Top apps with failed installs."""
    with session_scope() as db:
        rows = db.query(
            App.display_name,
            App.id,
            func.count(DeviceAppStatus.id).label("fail_count")
        ).join(
            DeviceAppStatus, DeviceAppStatus.app_id == App.id
        ).filter(
            DeviceAppStatus.install_state == "failed"
        ).group_by(App.id, App.display_name).order_by(
            desc("fail_count")
        ).limit(limit).all()
        return [{"name": r[0], "app_id": r[1], "fail_count": r[2]} for r in rows]


def get_device_app_statuses(device_id: str) -> list[dict]:
    with session_scope() as db:
        rows = db.query(DeviceAppStatus, App).join(
            App, App.id == DeviceAppStatus.app_id
        ).filter(DeviceAppStatus.device_id == device_id).all()
        result = []
        for das, app in rows:
            result.append({
                "app_id": app.id,
                "app_name": app.display_name,
                "install_state": das.install_state,
                "error_code": das.error_code,
                "last_sync": das.last_sync_date_time,
            })
        return result


# ---------------------------------------------------------------------------
# Group queries
# ---------------------------------------------------------------------------
def get_groups(search: str = "", limit: int = 200) -> list[dict]:
    with session_scope() as db:
        q = db.query(Group)
        if search:
            q = q.filter(Group.display_name.ilike(f"%{search}%"))
        q = q.order_by(Group.display_name).limit(limit)
        return [_group_to_dict(g) for g in q.all()]


def get_group_controls(group_id: str) -> list[dict]:
    """All controls assigned to or excluding this group."""
    with session_scope() as db:
        rows = db.query(Control, Assignment).join(
            Assignment, Assignment.control_id == Control.id
        ).filter(Assignment.target_id == group_id).all()
        result = []
        for ctrl, asmt in rows:
            d = _control_to_dict(ctrl)
            d["assignment_intent"] = asmt.intent
            d["filter_id"] = asmt.filter_id
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Sync log queries
# ---------------------------------------------------------------------------
def get_recent_sync_logs(limit: int = 10) -> list[dict]:
    with session_scope() as db:
        logs = db.query(SyncLog).order_by(desc(SyncLog.started_at)).limit(limit).all()
        return [
            {
                "id": l.id,
                "started_at": l.started_at,
                "finished_at": l.finished_at,
                "status": l.status,
                "devices_synced": l.devices_synced,
                "error_message": l.error_message,
            }
            for l in logs
        ]


def get_last_sync_info() -> dict:
    with session_scope() as db:
        log = db.query(SyncLog).order_by(desc(SyncLog.started_at)).first()
        if not log:
            return {"status": "never", "time": None, "error": None}
        return {
            "status": log.status,
            "time": log.finished_at or log.started_at,
            "error": log.error_message,
        }


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------
def global_search(query: str, limit: int = 30) -> dict[str, list[dict]]:
    """Search across devices, controls, and apps."""
    like = f"%{query}%"
    with session_scope() as db:
        devices = db.query(Device).filter(or_(
            Device.device_name.ilike(like),
            Device.serial_number.ilike(like),
            Device.user_principal_name.ilike(like),
        )).limit(limit).all()

        controls = db.query(Control).filter(Control.display_name.ilike(like)).limit(limit).all()

        apps = db.query(App).filter(or_(
            App.display_name.ilike(like), App.publisher.ilike(like)
        )).limit(limit).all()

        return {
            "devices": [_device_to_dict(d) for d in devices],
            "controls": [_control_to_dict(c) for c in controls],
            "apps": [_app_to_dict(a) for a in apps],
        }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _device_to_dict(d: Device) -> dict:
    return {
        "id": d.id,
        "device_name": d.device_name or "",
        "serial_number": d.serial_number or "",
        "os": d.operating_system or "",
        "os_version": d.os_version or "",
        "compliance_state": d.compliance_state or "unknown",
        "ownership": d.ownership or "",
        "last_sync": d.last_sync_date_time,
        "enrolled": d.enrolled_date_time,
        "user_upn": d.user_principal_name or "",
        "user_name": d.user_display_name or "",
        "model": d.model or "",
        "manufacturer": d.manufacturer or "",
        "management_state": d.management_state or "",
        "encrypted": d.encrypted,
        "synced_at": d.synced_at,
    }


def _control_to_dict(c: Control) -> dict:
    return {
        "id": c.id,
        "display_name": c.display_name or "",
        "control_type": c.control_type or "",
        "platform": c.platform or "",
        "description": c.description or "",
        "last_modified": c.last_modified_datetime,
        "is_assigned": c.is_assigned,
        "assignment_count": c.assignment_count or 0,
        "api_source": c.api_source or "",
    }


def _assignment_to_dict(a: Assignment) -> dict:
    return {
        "id": a.id,
        "control_id": a.control_id,
        "target_type": a.target_type or "",
        "target_id": a.target_id or "",
        "target_display_name": a.target_display_name or "",
        "intent": a.intent or "include",
        "filter_id": a.filter_id,
        "filter_type": a.filter_type,
    }


def _app_to_dict(a: App) -> dict:
    return {
        "id": a.id,
        "display_name": a.display_name or "",
        "app_type": a.app_type or "",
        "publisher": a.publisher or "",
        "is_assigned": a.is_assigned,
        "last_modified": a.last_modified_datetime,
        "failed_device_count": a.failed_device_count,
    }


def _group_to_dict(g: Group) -> dict:
    return {
        "id": g.id,
        "display_name": g.display_name or "",
        "description": g.description or "",
        "is_dynamic": g.is_dynamic,
        "member_count": g.member_count,
        "mail": g.mail or "",
    }
