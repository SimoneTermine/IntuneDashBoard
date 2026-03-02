"""
app/ui/pages/remediations_page.py

Proactive Remediations page.

Lists all deviceHealthScripts synced from the tenant, with:
  - Open in Intune Portal  (deep-link via intune_links.remediation_url)
  - Run Remediation        (on-demand run for a selected device)
  - Export

Graph permissions required:
  Read:  DeviceManagementConfiguration.Read.All
  Write: DeviceManagementConfiguration.ReadWrite.All  (Run action only)
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QTextEdit,
)

from app.ui.widgets.filterable_table import FilterableTable

logger = logging.getLogger(__name__)

REMEDIATION_COLUMNS = [
    ("display_name",          "Name",          280),
    ("publisher",             "Publisher",      140),
    ("is_global_script",      "Type",            80),
    ("last_modified",         "Last Modified",  140),
    ("description",           "Description",    300),
]


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


class RemediationsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Remediations")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Proactive Remediations (Device Health Scripts) — list, inspect, and run on-demand."
        )
        subtitle.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(subtitle)

        # ── Toolbar ────────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setMaximumWidth(90)
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        self._open_portal_btn = QPushButton("🌐  Open in Intune")
        self._open_portal_btn.setMaximumWidth(160)
        self._open_portal_btn.setEnabled(False)
        self._open_portal_btn.clicked.connect(self._open_portal)
        toolbar.addWidget(self._open_portal_btn)

        self._run_btn = QPushButton("▶  Run Remediation…")
        self._run_btn.setMaximumWidth(180)
        self._run_btn.setEnabled(False)
        self._run_btn.setToolTip(
            "Select a remediation and a target device, then trigger an on-demand run.\n"
            "Requires DeviceManagementConfiguration.ReadWrite.All permission."
        )
        self._run_btn.clicked.connect(self._run_remediation)
        toolbar.addWidget(self._run_btn)

        toolbar.addStretch()

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        toolbar.addWidget(self._status_lbl)

        layout.addLayout(toolbar)

        # ── Table ──────────────────────────────────────────────────────────────
        self._table = FilterableTable(REMEDIATION_COLUMNS)
        self._table.row_selected.connect(self._on_row_selected)
        self._table.set_context_menu_handler(self._on_context_menu)
        layout.addWidget(self._table)

        self._detail_label = QLabel("")
        self._detail_label.setWordWrap(True)
        self._detail_label.setStyleSheet(
            "color: #a6adc8; font-size: 12px; padding: 6px; "
            "background: #181825; border-radius: 6px;"
        )
        self._detail_label.setMaximumHeight(60)
        layout.addWidget(self._detail_label)

        self._selected_row: dict | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # Data
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self):
        try:
            from app.db.database import session_scope
            from app.db.models import Remediation

            with session_scope() as db:
                items = db.query(Remediation).order_by(Remediation.display_name).all()
                rows = []
                for r in items:
                    rows.append({
                        "id": r.id,
                        "display_name": r.display_name or "—",
                        "publisher": r.publisher or "—",
                        "is_global_script": "Microsoft" if r.is_global_script else "Custom",
                        "last_modified": _fmt_dt(r.last_modified_datetime),
                        "description": (r.description or "")[:200],
                    })

            self._table.load_data(rows)
            self._status_lbl.setText(f"{len(rows)} remediation(s)")

        except Exception as e:
            logger.error(f"RemediationsPage.refresh failed: {e}", exc_info=True)
            self._status_lbl.setText("Error loading data")

    def _on_row_selected(self, row_idx: int, row_data: dict):
        self._selected_row = row_data
        self._open_portal_btn.setEnabled(bool(row_data.get("id")))
        self._run_btn.setEnabled(bool(row_data.get("id")))
        desc = row_data.get("description", "")
        name = row_data.get("display_name", "")
        self._detail_label.setText(
            f"<b>{name}</b>  —  {desc}" if desc else f"<b>{name}</b>"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────

    def _open_portal(self):
        if not self._selected_row:
            return
        script_id = self._selected_row.get("id", "")
        if script_id:
            from app.utils.intune_links import open_remediation_portal
            open_remediation_portal(script_id)

    def _run_remediation(self):
        if not self._selected_row:
            return
        script_id = self._selected_row.get("id", "")
        script_name = self._selected_row.get("display_name", "this script")
        if not script_id:
            return

        dialog = RunRemediationDialog(script_id, script_name, self)
        dialog.exec()

    def _on_context_menu(self, row_data: dict, global_pos):
        from app.ui.widgets.context_menus import _styled_menu, _add_copy, _section_header
        from app.utils.intune_links import open_remediation_portal
        import json

        name = row_data.get("display_name", "Unknown")
        script_id = row_data.get("id", "")

        menu = _styled_menu(self)
        _section_header(menu, f"💊  {name}")
        menu.addSeparator()

        if script_id:
            act_portal = QAction("🌐  Open in Intune Portal", menu)
            act_portal.triggered.connect(lambda: open_remediation_portal(script_id))
            menu.addAction(act_portal)

            act_run = QAction("▶  Run Remediation…", menu)
            act_run.triggered.connect(lambda: RunRemediationDialog(script_id, name, self).exec())
            menu.addAction(act_run)

            menu.addSeparator()

        copy_menu = _styled_menu(self)
        copy_menu.setTitle("📋  Copy…")
        _add_copy(copy_menu, f"Name    {name}", name)
        if script_id:
            _add_copy(copy_menu, "Script ID", script_id)
        copy_menu.addSeparator()
        _add_copy(copy_menu, "Full Row as JSON", json.dumps(row_data, default=str, indent=2))
        menu.addMenu(copy_menu)

        menu.exec(global_pos)


# ─────────────────────────────────────────────────────────────────────────────
# Dialog: select device + trigger run
# ─────────────────────────────────────────────────────────────────────────────

class _RunWorker(QThread):
    """Background thread for the on-demand remediation POST call."""
    finished = Signal(dict)  # result dict from RemediationCollector.run_on_device

    def __init__(self, script_id: str, device_id: str):
        super().__init__()
        self._script_id = script_id
        self._device_id = device_id

    def run(self):
        try:
            from app.config import AppConfig
            if AppConfig().demo_mode:
                import time; time.sleep(1)
                self.finished.emit({"success": False, "user_message":
                    "Run Remediation is not available in Demo Mode."})
                return

            from app.graph.client import get_client
            from app.collector.remediations import RemediationCollector
            client = get_client()
            collector = RemediationCollector(client)
            result = collector.run_on_device(self._script_id, self._device_id)
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit({
                "success": False,
                "error": str(e),
                "user_message": f"Unexpected error: {e}",
            })


class RunRemediationDialog(QDialog):
    """
    Dialog to pick a target device and trigger an on-demand remediation run.
    """

    def __init__(self, script_id: str, script_name: str, parent=None):
        super().__init__(parent)
        self._script_id = script_id
        self._script_name = script_name
        self._worker: _RunWorker | None = None
        self.setWindowTitle(f"Run Remediation — {script_name}")
        self.resize(620, 460)
        self._setup_ui()
        self._load_devices()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        hdr = QLabel(
            f"Run  <b style='color:#cba6f7'>{self._script_name}</b>  on a target device."
        )
        hdr.setTextFormat(Qt.RichText)
        hdr.setWordWrap(True)
        lay.addWidget(hdr)

        note = QLabel(
            "⚠️  This triggers an on-demand run at the device's next check-in. "
            "The script must already be assigned to the device's group.  "
            "Microsoft-managed (global) scripts cannot be run on-demand."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "color: #f9e2af; font-size: 11px; padding: 6px; "
            "background: #313244; border-radius: 6px;"
        )
        lay.addWidget(note)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self._search = QComboBox()
        self._search.setEditable(True)
        self._search.setPlaceholderText("Type to filter devices…")
        self._search.setMinimumWidth(300)
        search_row.addWidget(self._search, 1)
        lay.addLayout(search_row)

        self._device_table = QTableWidget()
        self._device_table.setColumnCount(3)
        self._device_table.setHorizontalHeaderLabels(["Device Name", "OS", "User"])
        self._device_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._device_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._device_table.setAlternatingRowColors(True)
        self._device_table.verticalHeader().setVisible(False)
        self._device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._device_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._device_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._device_table.itemSelectionChanged.connect(self._on_selection_changed)
        lay.addWidget(self._device_table)

        self._result_lbl = QLabel("")
        self._result_lbl.setWordWrap(True)
        self._result_lbl.setStyleSheet("font-size: 12px; padding: 4px;")
        lay.addWidget(self._result_lbl)

        self._btns = QDialogButtonBox()
        self._run_btn = self._btns.addButton("▶  Run", QDialogButtonBox.AcceptRole)
        self._run_btn.setEnabled(False)
        self._btns.addButton(QDialogButtonBox.Close)
        self._btns.accepted.connect(self._do_run)
        self._btns.rejected.connect(self.reject)
        lay.addWidget(self._btns)

        self._all_rows: list[dict] = []
        self._search.currentTextChanged.connect(self._filter_table)

    def _load_devices(self):
        try:
            from app.db.database import session_scope
            from app.db.models import Device

            with session_scope() as db:
                devs = db.query(Device).order_by(Device.device_name).all()
                self._all_rows = [
                    {
                        "id": d.id,
                        "name": d.device_name or d.id,
                        "os": d.operating_system or "—",
                        "user": d.user_principal_name or "—",
                    }
                    for d in devs
                ]
            self._populate_table(self._all_rows)
        except Exception as e:
            self._result_lbl.setText(f"Failed to load devices: {e}")
            self._result_lbl.setStyleSheet("color: #f38ba8; font-size: 12px;")

    def _populate_table(self, rows: list[dict]):
        self._device_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._device_table.setItem(i, 0, QTableWidgetItem(r["name"]))
            self._device_table.setItem(i, 1, QTableWidgetItem(r["os"]))
            self._device_table.setItem(i, 2, QTableWidgetItem(r["user"]))
            # Store device_id in hidden data
            self._device_table.item(i, 0).setData(Qt.UserRole, r["id"])

    def _filter_table(self, text: str):
        text = text.strip().lower()
        if not text:
            self._populate_table(self._all_rows)
            return
        filtered = [
            r for r in self._all_rows
            if text in r["name"].lower()
            or text in r["user"].lower()
            or text in r["os"].lower()
        ]
        self._populate_table(filtered)

    def _on_selection_changed(self):
        has_selection = bool(self._device_table.selectedItems())
        self._run_btn.setEnabled(has_selection)

    def _get_selected_device_id(self) -> str | None:
        rows = self._device_table.selectedItems()
        if not rows:
            return None
        row_idx = self._device_table.currentRow()
        item = self._device_table.item(row_idx, 0)
        return item.data(Qt.UserRole) if item else None

    def _do_run(self):
        device_id = self._get_selected_device_id()
        if not device_id:
            return

        self._run_btn.setEnabled(False)
        self._result_lbl.setText("Sending request…")
        self._result_lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")

        self._worker = _RunWorker(self._script_id, device_id)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.start()

    def _on_run_finished(self, result: dict):
        self._run_btn.setEnabled(True)
        if result.get("success"):
            self._result_lbl.setText(
                "✅  Remediation queued successfully. "
                "The script will run on the device's next check-in."
            )
            self._result_lbl.setStyleSheet("color: #a6e3a1; font-size: 12px; padding: 4px;")
            logger.info(
                f"On-demand remediation queued: script={self._script_id} "
                f"device={self._get_selected_device_id()}"
            )
        else:
            msg = result.get("user_message") or result.get("error", "Unknown error")
            self._result_lbl.setText(f"❌  {msg}")
            self._result_lbl.setStyleSheet("color: #f38ba8; font-size: 12px; padding: 4px;")
            logger.error(
                f"On-demand remediation failed: script={self._script_id} "
                f"error={result.get('error')}"
            )
