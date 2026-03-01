"""
CSV and JSON export utilities.
"""

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppConfig

logger = logging.getLogger(__name__)


def _export_path(filename: str) -> str:
    export_dir = Path(AppConfig().export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    return str(export_dir / filename)


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def export_csv(data: list[dict], filename: str) -> str:
    """Export list of dicts to CSV. Returns file path."""
    if not data:
        raise ValueError("No data to export")

    path = _export_path(filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        for row in data:
            writer.writerow({k: _serialize(v) for k, v in row.items()})

    logger.info(f"CSV exported: {path} ({len(data)} rows)")
    return path


def export_json(data: Any, filename: str) -> str:
    """Export data to JSON. Returns file path."""
    path = _export_path(filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=_serialize)

    logger.info(f"JSON exported: {path}")
    return path


def export_devices_csv() -> str:
    from app.analytics.queries import get_devices
    data = get_devices(limit=10000)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return export_csv(data, f"devices_{ts}.csv")


def export_controls_csv() -> str:
    from app.analytics.queries import get_controls
    data = get_controls(limit=10000)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return export_csv(data, f"policies_{ts}.csv")


def export_drift_report_json(report: dict) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return export_json(report, f"drift_report_{ts}.json")


def export_drift_report_csv(report: dict) -> str:
    """Flatten drift report to CSV."""
    rows = []
    for item in report.get("added", []):
        rows.append({**item, "change_type": "ADDED"})
    for item in report.get("removed", []):
        rows.append({**item, "change_type": "REMOVED"})
    for item in report.get("modified", []):
        rows.append({
            **{k: v for k, v in item.items() if k != "changed_fields"},
            "changed_fields": ", ".join(item.get("changed_fields", [])),
            "change_type": "MODIFIED",
        })
    if not rows:
        rows = [{"message": "No changes detected"}]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return export_csv(rows, f"drift_report_{ts}.csv")
