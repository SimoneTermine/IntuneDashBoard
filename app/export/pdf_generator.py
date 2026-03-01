"""
PDF evidence pack generator for a single device.
Generates a tamper-evident PDF with SHA256 hash.
Uses reportlab (no external services).
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppConfig

logger = logging.getLogger(__name__)


def generate_device_evidence_pdf(device_id: str) -> str:
    """
    Generate a PDF evidence pack for a device.
    Returns file path.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.colors import HexColor, black, white
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table,
            TableStyle, HRFlowable, PageBreak,
        )
        from reportlab.lib import colors
    except ImportError:
        raise ImportError("reportlab is required for PDF generation. Run: pip install reportlab")

    from app.analytics.queries import (
        get_device_by_id, get_device_app_statuses,
        get_assignments_for_control, get_controls,
        get_last_sync_info,
    )
    from app.analytics.explainability import ExplainabilityEngine

    device = get_device_by_id(device_id)
    if not device:
        raise ValueError(f"Device {device_id} not found")

    export_dir = Path(AppConfig().export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = (device.get("device_name") or device_id).replace(" ", "_").replace("/", "-")
    pdf_path = str(export_dir / f"evidence_{safe_name}_{ts}.pdf")

    styles = getSampleStyleSheet()
    PURPLE = HexColor("#7c3aed")
    DARK = HexColor("#1e1e2e")
    LIGHT_BG = HexColor("#f3f4f6")

    title_style = ParagraphStyle("Title", parent=styles["Heading1"], textColor=PURPLE, fontSize=18, spaceAfter=6)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], textColor=DARK, fontSize=13, spaceBefore=12, spaceAfter=4)
    body_style = styles["BodyText"]
    meta_style = ParagraphStyle("Meta", parent=styles["BodyText"], fontSize=9, textColor=HexColor("#6c7086"))

    story = []

    # Header
    story.append(Paragraph("INTUNE DEVICE EVIDENCE PACK", title_style))
    story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", meta_style))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", color=PURPLE))
    story.append(Spacer(1, 0.3 * cm))

    # Device Summary
    story.append(Paragraph("Device Summary", h2_style))
    sync_info = get_last_sync_info()

    summary_data = [
        ["Device Name", device.get("device_name", "N/A")],
        ["Device ID", device_id],
        ["Serial Number", device.get("serial_number", "N/A")],
        ["Operating System", f"{device.get('os', '')} {device.get('os_version', '')}".strip() or "N/A"],
        ["Compliance State", device.get("compliance_state", "unknown").upper()],
        ["Ownership", device.get("ownership", "N/A")],
        ["Manufacturer / Model", f"{device.get('manufacturer', '')} {device.get('model', '')}".strip() or "N/A"],
        ["Primary User", device.get("user_upn", "N/A")],
        ["Last Sync to Intune", _fmt_dt(device.get("last_sync"))],
        ["Data Last Collected", _fmt_dt(device.get("synced_at"))],
        ["Encrypted", str(device.get("encrypted", "unknown"))],
    ]

    t = Table(summary_data, colWidths=[5 * cm, 12 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [white, LIGHT_BG]),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))

    # Compliance & Policy State
    story.append(Paragraph("Compliance & Policy Assessment", h2_style))
    try:
        engine = ExplainabilityEngine()
        explanation = engine.explain_device(device_id)
        story.append(Paragraph(explanation.summary, body_style))
        story.append(Spacer(1, 0.3 * cm))

        if explanation.results:
            policy_headers = ["Policy Name", "Type", "Status", "Reason Code", "Source"]
            policy_rows = [policy_headers]
            for r in explanation.results[:50]:
                policy_rows.append([
                    r.control_name[:40],
                    r.control_type,
                    r.status,
                    r.reason_code,
                    r.source,
                ])
            pt = Table(policy_rows, colWidths=[5.5 * cm, 3 * cm, 2.5 * cm, 3.5 * cm, 2.5 * cm])
            pt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
                ("TEXTCOLOR", (0, 0), (-1, 0), white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            story.append(pt)
        else:
            story.append(Paragraph("No policy data available. Run a sync to collect data.", body_style))
    except Exception as e:
        story.append(Paragraph(f"Policy analysis unavailable: {e}", body_style))

    story.append(Spacer(1, 0.5 * cm))

    # App Status
    story.append(Paragraph("Application Status", h2_style))
    try:
        app_statuses = get_device_app_statuses(device_id)
        if app_statuses:
            app_headers = ["Application", "Install State", "Error Code"]
            app_rows = [app_headers] + [
                [a.get("app_name", "")[:40], a.get("install_state", ""), str(a.get("error_code") or "")]
                for a in app_statuses[:30]
            ]
            at = Table(app_rows, colWidths=[9 * cm, 4 * cm, 4 * cm])
            at.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), PURPLE),
                ("TEXTCOLOR", (0, 0), (-1, 0), white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
            ]))
            story.append(at)
        else:
            story.append(Paragraph("No app status data available for this device.", body_style))
    except Exception as e:
        story.append(Paragraph(f"App status unavailable: {e}", body_style))

    story.append(Spacer(1, 0.5 * cm))

    # Sync metadata
    story.append(Paragraph("Data Collection Metadata", h2_style))
    meta_data = [
        ["Sync Status", sync_info.get("status", "unknown")],
        ["Last Sync Completed", _fmt_dt(sync_info.get("time"))],
        ["Tool Version", "Intune Dashboard 1.0.0"],
        ["Data Source", "Microsoft Graph API (local cache)"],
    ]
    mt = Table(meta_data, colWidths=[5 * cm, 12 * cm])
    mt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(mt)
    story.append(Spacer(1, 0.5 * cm))

    # Disclaimer
    story.append(HRFlowable(width="100%", color=colors.grey))
    story.append(Paragraph(
        "DISCLAIMER: This evidence pack is generated from locally cached data collected via Microsoft Graph API. "
        "It represents the state at the time of last data sync. Some data may be incomplete (marked as best-effort). "
        "For authoritative compliance data, refer to the Microsoft Intune portal.",
        meta_style
    ))

    # Build PDF
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    doc.build(story)

    # Compute SHA256 and append to filename or create sidecar
    sha256 = _file_sha256(pdf_path)
    hash_file = pdf_path.replace(".pdf", ".sha256")
    with open(hash_file, "w") as f:
        f.write(f"{sha256}  {os.path.basename(pdf_path)}\n")

    logger.info(f"Evidence PDF generated: {pdf_path} (SHA256: {sha256})")
    return pdf_path


def _fmt_dt(dt) -> str:
    if dt is None:
        return "N/A"
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(dt)


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
