"""
Drift detection - snapshot and diff comparison for governance.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from app.db.database import session_scope
from app.db.models import (
    Snapshot, SnapshotItem, DriftReport,
    Device, Control, Assignment,
)

logger = logging.getLogger(__name__)


def _checksum(data: dict) -> str:
    """SHA256 of a stable subset of object fields."""
    stable = {k: str(v) for k, v in sorted(data.items()) if v is not None}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:16]


def create_snapshot(name: str | None = None) -> int:
    """
    Create a new snapshot of all controls, assignments, and device counts.
    Returns snapshot id.
    """
    if not name:
        name = f"Snapshot {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"

    logger.info(f"Creating snapshot: {name}")

    with session_scope() as db:
        # Count entities
        device_count = db.query(Device).count()
        control_count = db.query(Control).count()
        assignment_count = db.query(Assignment).count()

        snapshot = Snapshot(
            name=name,
            created_at=datetime.utcnow(),
            device_count=device_count,
            control_count=control_count,
            assignment_count=assignment_count,
        )
        db.add(snapshot)
        db.flush()
        snap_id = snapshot.id

        # Snapshot controls
        for ctrl in db.query(Control).all():
            item = SnapshotItem(
                snapshot_id=snap_id,
                entity_type="control",
                entity_id=ctrl.id,
                display_name=ctrl.display_name or "",
                checksum=_checksum({
                    "display_name": ctrl.display_name,
                    "control_type": ctrl.control_type,
                    "platform": ctrl.platform,
                    "assignment_count": ctrl.assignment_count,
                }),
                last_modified=ctrl.last_modified_datetime,
                raw_snapshot_json=json.dumps({
                    "id": ctrl.id,
                    "display_name": ctrl.display_name,
                    "control_type": ctrl.control_type,
                    "platform": ctrl.platform,
                }),
            )
            db.add(item)

        # Snapshot assignments
        for asmt in db.query(Assignment).all():
            item = SnapshotItem(
                snapshot_id=snap_id,
                entity_type="assignment",
                entity_id=asmt.id,
                display_name=f"{asmt.control_id} → {asmt.target_id}",
                checksum=_checksum({
                    "control_id": asmt.control_id,
                    "target_id": asmt.target_id,
                    "intent": asmt.intent,
                }),
                raw_snapshot_json=json.dumps({
                    "control_id": asmt.control_id,
                    "target_id": asmt.target_id,
                    "target_type": asmt.target_type,
                    "intent": asmt.intent,
                }),
            )
            db.add(item)

    logger.info(f"Snapshot created: id={snap_id}, controls={control_count}, assignments={assignment_count}")
    return snap_id


def compare_snapshots(baseline_id: int, current_id: int) -> dict:
    """
    Compare two snapshots and return a drift report dict.
    """
    with session_scope() as db:
        baseline_items = {
            item.entity_id: item
            for item in db.query(SnapshotItem).filter(SnapshotItem.snapshot_id == baseline_id).all()
        }
        current_items = {
            item.entity_id: item
            for item in db.query(SnapshotItem).filter(SnapshotItem.snapshot_id == current_id).all()
        }

    baseline_ids = set(baseline_items.keys())
    current_ids = set(current_items.keys())

    added_ids = current_ids - baseline_ids
    removed_ids = baseline_ids - current_ids
    common_ids = baseline_ids & current_ids
    modified_ids = {
        eid for eid in common_ids
        if baseline_items[eid].checksum != current_items[eid].checksum
    }

    added = [
        {
            "entity_id": eid,
            "display_name": current_items[eid].display_name,
            "entity_type": current_items[eid].entity_type,
        }
        for eid in sorted(added_ids)
    ]
    removed = [
        {
            "entity_id": eid,
            "display_name": baseline_items[eid].display_name,
            "entity_type": baseline_items[eid].entity_type,
        }
        for eid in sorted(removed_ids)
    ]
    modified = []
    for eid in sorted(modified_ids):
        base = baseline_items[eid]
        curr = current_items[eid]
        try:
            base_data = json.loads(base.raw_snapshot_json or "{}")
            curr_data = json.loads(curr.raw_snapshot_json or "{}")
        except Exception:
            base_data, curr_data = {}, {}

        changed_fields = [
            k for k in set(list(base_data.keys()) + list(curr_data.keys()))
            if base_data.get(k) != curr_data.get(k)
        ]
        modified.append({
            "entity_id": eid,
            "display_name": curr.display_name,
            "entity_type": curr.entity_type,
            "changed_fields": changed_fields,
            "baseline_checksum": base.checksum,
            "current_checksum": curr.checksum,
        })

    report = {
        "baseline_id": baseline_id,
        "current_id": current_id,
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "total_baseline": len(baseline_ids),
            "total_current": len(current_ids),
        },
        "added": added,
        "removed": removed,
        "modified": modified,
    }

    # Save to DB
    with session_scope() as db:
        dr = DriftReport(
            created_at=datetime.utcnow(),
            baseline_snapshot_id=baseline_id,
            current_snapshot_id=current_id,
            added_count=len(added),
            removed_count=len(removed),
            modified_count=len(modified),
            report_json=json.dumps(report),
        )
        db.add(dr)

    return report


def get_snapshots() -> list[dict]:
    with session_scope() as db:
        snaps = db.query(Snapshot).order_by(Snapshot.created_at.desc()).all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "created_at": s.created_at,
                "device_count": s.device_count,
                "control_count": s.control_count,
                "assignment_count": s.assignment_count,
            }
            for s in snaps
        ]


def get_blast_radius(control_id: str) -> dict:
    """
    Estimate how many devices/users are targeted by a control's assignments.
    """
    with session_scope() as db:
        assignments = db.query(Assignment).filter(
            Assignment.control_id == control_id
        ).all()

        total_device_estimate = 0
        groups_targeted = []
        all_devices = False
        all_users = False

        for asmt in assignments:
            if asmt.intent == "exclude":
                continue
            if asmt.target_type == "allDevices":
                all_devices = True
                total_devices_db = db.query(Device).count()
                total_device_estimate = max(total_device_estimate, total_devices_db)
            elif asmt.target_type == "allUsers":
                all_users = True
                total_devices_db = db.query(Device).count()
                total_device_estimate = max(total_device_estimate, total_devices_db)
            elif asmt.target_type == "group":
                from app.db.models import Group, DeviceGroupMembership
                group = db.get(Group, asmt.target_id)
                gname = group.display_name if group else asmt.target_id
                groups_targeted.append({"id": asmt.target_id, "name": gname, "member_count": group.member_count if group else None})
                # Count devices in this group from local DB
                dev_count = db.query(DeviceGroupMembership).filter(
                    DeviceGroupMembership.group_id == asmt.target_id
                ).count()
                total_device_estimate += dev_count

        return {
            "control_id": control_id,
            "all_devices": all_devices,
            "all_users": all_users,
            "groups_targeted": groups_targeted,
            "estimated_device_impact": total_device_estimate,
            "note": "Estimate based on locally cached data. Group membership cache may be incomplete.",
        }
