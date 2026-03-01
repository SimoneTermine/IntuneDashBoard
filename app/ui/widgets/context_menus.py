"""
app/ui/widgets/context_menus.py

Context menu builders + inline dialogs for:
  - Device Explorer  (right-click on device rows)
  - Policy Explorer  (right-click on policy / app rows)
  - Governance       (right-click on snapshot rows + drift rows)

Each builder receives the row data dict, the global QPoint for positioning,
the parent widget, and optional callbacks for inter-page navigation.
"""

from __future__ import annotations

import csv
import json
import logging
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QPoint, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QProgressDialog,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared stylesheet
# ─────────────────────────────────────────────────────────────────────────────

_MENU_STYLE = """
QMenu {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 2px;
}
QMenu::item {
    padding: 6px 22px 6px 14px;
    border-radius: 4px;
    margin: 1px 4px;
}
QMenu::item:selected {
    background-color: #313244;
    color: #cba6f7;
}
QMenu::item:disabled {
    color: #6c7086;
}
QMenu::separator {
    height: 1px;
    background: #45475a;
    margin: 4px 10px;
}
QMenu::icon {
    padding-left: 6px;
}
"""


def _styled_menu(parent) -> QMenu:
    m = QMenu(parent)
    m.setStyleSheet(_MENU_STYLE)
    return m


def _section_header(menu: QMenu, text: str):
    """Non-clickable bold label used as visual section header."""
    act = QAction(text, menu)
    act.setEnabled(False)
    f = act.font()
    f.setBold(True)
    act.setFont(f)
    menu.addAction(act)


# ─────────────────────────────────────────────────────────────────────────────
# Clipboard & file helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clip(text: str):
    QApplication.clipboard().setText(str(text))


def _export_json(data: dict, parent=None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export as JSON", f"export_{ts}.json", "JSON Files (*.json)"
    )
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        QMessageBox.information(parent, "Export Complete", f"Saved to:\n{path}")


def _export_csv(data: dict, parent=None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export as CSV", f"export_{ts}.csv", "CSV Files (*.csv)"
    )
    if path:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=data.keys())
            writer.writeheader()
            writer.writerow({k: str(v) for k, v in data.items()})
        QMessageBox.information(parent, "Export Complete", f"Saved to:\n{path}")


# ─────────────────────────────────────────────────────────────────────────────
# Intune / Entra portal URL builders
# ─────────────────────────────────────────────────────────────────────────────

def _url_device_intune(device_id: str) -> str:
    return (
        "https://intune.microsoft.com/#view/Microsoft_Intune_Devices"
        f"/DeviceSettingsMenuBlade/~/overview/mdmDeviceId/{device_id}"
    )


def _url_device_entra(device_id: str) -> str:
    # Entra uses the Entra object ID, not Intune device ID.
    # We open the Entra devices search as best-effort fallback.
    return (
        "https://entra.microsoft.com/#view/Microsoft_AAD_Devices"
        "/DevicesMenuBlade/~/AllDevices"
    )


def _url_policy_intune(policy_id: str, policy_type: str = "") -> str:
    pt = policy_type.lower()
    if "compliance" in pt:
        return (
            "https://intune.microsoft.com/#view/Microsoft_Intune_DeviceSettings"
            f"/DevicesCompliancePolicyOverview.ReactView/policyId/{policy_id}"
        )
    elif "settings_catalog" in pt or "settings catalog" in pt:
        return (
            "https://intune.microsoft.com/#view/Microsoft_Intune_DeviceSettings"
            f"/PolicySummaryBlade/policyId/{policy_id}/policyType/configurationPolicy"
        )
    else:
        return (
            "https://intune.microsoft.com/#view/Microsoft_Intune_DeviceSettings"
            f"/PolicySummaryBlade/policyId/{policy_id}/policyType/deviceConfiguration"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Background worker: single-device refresh
# ─────────────────────────────────────────────────────────────────────────────

class _DeviceSyncWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, device_id: str):
        super().__init__()
        self._device_id = device_id

    def run(self):
        try:
            from app.config import AppConfig
            from app.db.database import session_scope
            from app.db.models import ManagedDevice
            from app.graph.auth import get_token
            from app.graph.client import GraphClient

            cfg = AppConfig()
            if cfg.demo_mode:
                self.done.emit(False, "demo_mode")
                return

            token = get_token()
            if not token:
                self.done.emit(False, "no_token")
                return

            client = GraphClient(token)
            dev_data = client.get(
                f"deviceManagement/managedDevices/{self._device_id}"
            )
            if not dev_data:
                self.done.emit(False, "not_found")
                return

            with session_scope() as db:
                dev = (
                    db.query(ManagedDevice)
                    .filter(ManagedDevice.device_id == self._device_id)
                    .first()
                )
                if dev:
                    dev.device_name = dev_data.get("deviceName", dev.device_name)
                    dev.compliance_state = dev_data.get(
                        "complianceState", dev.compliance_state
                    )
                    dev.last_sync_datetime = dev_data.get("lastSyncDateTime")
                    dev.os_version = dev_data.get("osVersion", dev.os_version)
                    dev.last_updated = datetime.utcnow()

            name = dev_data.get("deviceName", self._device_id)
            self.done.emit(True, name)
        except Exception as e:
            self.done.emit(False, str(e))


def _force_sync_device(device_id: str, device_name: str, parent, on_done=None):
    from app.config import AppConfig
    if AppConfig().demo_mode:
        QMessageBox.information(
            parent, "Demo Mode", "Force sync is not available in demo mode."
        )
        return

    progress = QProgressDialog(
        f"Refreshing '{device_name}' from Graph…", None, 0, 0, parent
    )
    progress.setWindowTitle("Syncing Device")
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    progress.show()

    worker = _DeviceSyncWorker(device_id)
    # Keep alive
    parent._sync_worker_ref = worker  # type: ignore[attr-defined]

    def _finish(success: bool, msg: str):
        progress.close()
        if success:
            QMessageBox.information(
                parent, "Sync Complete",
                f"Device '{msg}' refreshed successfully from Microsoft Graph."
            )
            if on_done:
                on_done()
        elif msg == "demo_mode":
            QMessageBox.information(
                parent, "Demo Mode", "Force sync is not available in demo mode."
            )
        elif msg == "no_token":
            QMessageBox.warning(
                parent, "Auth Error",
                "Could not obtain access token.\nPlease re-authenticate in Settings."
            )
        elif msg == "not_found":
            QMessageBox.warning(
                parent, "Not Found",
                f"Device '{device_id}' was not found in Microsoft Graph.\n"
                "It may have been deleted or unenrolled."
            )
        else:
            QMessageBox.warning(parent, "Sync Failed", f"Error: {msg}")

    worker.done.connect(_finish)
    worker.start()


# ─────────────────────────────────────────────────────────────────────────────
# Dialog: Policy Diff
# ─────────────────────────────────────────────────────────────────────────────

class PolicyDiffDialog(QDialog):
    """Side-by-side flat comparison of two policies."""

    def __init__(self, policy_a: dict, policy_b: dict, parent=None):
        super().__init__(parent)
        self._pa = policy_a
        self._pb = policy_b
        self._diff_data: dict = {}
        name_a = policy_a.get("display_name", "Policy A")
        name_b = policy_b.get("display_name", "Policy B")
        self.setWindowTitle(f"Policy Diff — {name_a}  vs  {name_b}")
        self.resize(1150, 680)
        self._setup_ui()
        self._populate()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        # Header row
        hdr = QHBoxLayout()
        lbl_a = QLabel(f"◀  {self._pa.get('display_name', 'Policy A')}")
        lbl_a.setStyleSheet("font-size: 14px; font-weight: bold; color: #89dceb;")
        lbl_b = QLabel(f"▶  {self._pb.get('display_name', 'Policy B')}")
        lbl_b.setStyleSheet("font-size: 14px; font-weight: bold; color: #f9e2af;")
        lbl_b.setAlignment(Qt.AlignRight)
        hdr.addWidget(lbl_a)
        hdr.addStretch()
        hdr.addWidget(lbl_b)
        lay.addLayout(hdr)

        # Legend
        legend = QLabel(
            "  🟦 Only in A   🟧 Only in B   🔴 Different values   ✅ Identical"
        )
        legend.setStyleSheet(
            "color: #a6adc8; font-size: 12px; padding: 4px 0; border-bottom: 1px solid #45475a;"
        )
        lay.addWidget(legend)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Setting / Key", "Policy A", "Policy B"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setSortingEnabled(True)
        lay.addWidget(self._tree)

        # Summary
        self._summary = QLabel()
        self._summary.setStyleSheet(
            "color: #a6adc8; font-size: 12px; padding: 4px; border-top: 1px solid #45475a;"
        )
        lay.addWidget(self._summary)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        exp_btn = QPushButton("📤  Export Diff as JSON")
        exp_btn.clicked.connect(self._export)
        btns.addButton(exp_btn, QDialogButtonBox.ActionRole)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _flatten(self, d: dict, prefix: str = "") -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(self._flatten(v, key))
            elif isinstance(v, list):
                out[key] = json.dumps(v, default=str)
            else:
                out[key] = "" if v is None else str(v)
        return out

    def _populate(self):
        # Skip noisy metadata keys
        _SKIP = {
            "id", "createdDateTime", "lastModifiedDateTime",
            "version", "settingCount",
        }
        flat_a = {k: v for k, v in self._flatten(self._pa).items() if k not in _SKIP}
        flat_b = {k: v for k, v in self._flatten(self._pb).items() if k not in _SKIP}

        all_keys = sorted(set(flat_a) | set(flat_b))
        identical = different = only_a = only_b = 0

        for key in all_keys:
            va = flat_a.get(key)
            vb = flat_b.get(key)
            item = QTreeWidgetItem([key, va or "—", vb or "—"])

            if va is None:
                # Only in B
                for col in (0, 2):
                    item.setForeground(col, QColor("#f9e2af"))
                only_b += 1
            elif vb is None:
                # Only in A
                for col in (0, 1):
                    item.setForeground(col, QColor("#89dceb"))
                only_a += 1
            elif va != vb:
                for col in range(3):
                    item.setForeground(col, QColor("#f38ba8"))
                different += 1
            else:
                item.setForeground(0, QColor("#6c7086"))
                for col in (1, 2):
                    item.setForeground(col, QColor("#a6e3a1"))
                identical += 1

            self._tree.addTopLevelItem(item)

        self._summary.setText(
            f"Total settings: {len(all_keys)}   |   "
            f"✅ Identical: {identical}   "
            f"🔴 Different: {different}   "
            f"🟦 Only in A: {only_a}   "
            f"🟧 Only in B: {only_b}"
        )
        self._diff_data = {
            "compared_at": datetime.now().isoformat(),
            "policy_a": self._pa.get("display_name"),
            "policy_b": self._pb.get("display_name"),
            "summary": {
                "total": len(all_keys),
                "identical": identical,
                "different": different,
                "only_in_a": only_a,
                "only_in_b": only_b,
            },
            "differences": [
                {"key": k, "policy_a": flat_a.get(k), "policy_b": flat_b.get(k)}
                for k in all_keys
                if flat_a.get(k) != flat_b.get(k)
            ],
        }

    def _export(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Policy Diff",
            f"policy_diff_{ts}.json", "JSON Files (*.json)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._diff_data, f, indent=2, default=str)
            QMessageBox.information(self, "Export Complete", f"Diff exported to:\n{path}")


# ─────────────────────────────────────────────────────────────────────────────
# Dialog: Drift Before / After Detail
# ─────────────────────────────────────────────────────────────────────────────

class DriftDetailDialog(QDialog):
    """Shows before/after snapshot JSON for a single drift change row."""

    def __init__(
        self,
        row_data: dict,
        baseline_id: int,
        current_id: int,
        parent=None,
    ):
        super().__init__(parent)
        self._row = row_data
        self._baseline_id = baseline_id
        self._current_id = current_id

        change_type = str(row_data.get("change_type", "")).upper()
        entity_name = row_data.get("display_name", row_data.get("entity_name", "Unknown"))
        self.setWindowTitle(f"Drift Detail — {entity_name}")
        self.resize(1000, 560)
        self._setup_ui(change_type, entity_name)
        self._load_data()

    def _setup_ui(self, change_type: str, entity_name: str):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        color_map = {"ADDED": "#a6e3a1", "REMOVED": "#f38ba8", "MODIFIED": "#f9e2af"}
        color = color_map.get(change_type, "#cdd6f4")
        icon_map = {"ADDED": "🟢", "REMOVED": "🔴", "MODIFIED": "🟡"}
        icon = icon_map.get(change_type, "🔵")

        hdr = QLabel(
            f"<span style='color:{color};font-weight:bold;font-size:15px'>"
            f"{icon}  {change_type}</span>"
            f"  <span style='color:#cdd6f4;font-size:14px'>·  {entity_name}</span>"
        )
        hdr.setTextFormat(Qt.RichText)
        lay.addWidget(hdr)

        changed = self._row.get("changed_fields", "")
        if changed:
            fl = QLabel(f"Changed fields: <b style='color:#cba6f7'>{changed}</b>")
            fl.setTextFormat(Qt.RichText)
            fl.setStyleSheet("color: #a6adc8; font-size: 12px; margin-bottom: 4px;")
            lay.addWidget(fl)

        # Side-by-side splitter
        splitter = QSplitter(Qt.Horizontal)

        def _panel(title: str, color: str) -> QTextEdit:
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(title)
            lbl.setStyleSheet(f"font-weight: bold; color: {color}; padding: 4px 0;")
            wl.addWidget(lbl)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setStyleSheet(
                "font-family: 'Consolas', 'Courier New', monospace; font-size: 12px;"
            )
            wl.addWidget(te)
            splitter.addWidget(w)
            return te

        self._baseline_te = _panel(
            f"📸  Baseline  (Snapshot #{self._baseline_id})", "#89dceb"
        )
        self._current_te = _panel(
            f"📸  Current   (Snapshot #{self._current_id})", "#f9e2af"
        )
        lay.addWidget(splitter)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _load_data(self):
        entity_id = self._row.get("entity_id", "")
        if not entity_id:
            msg = "(Entity ID not available — drift data may be from an older snapshot format.)"
            self._baseline_te.setPlainText(msg)
            self._current_te.setPlainText(msg)
            return

        try:
            from app.db.database import session_scope
            from app.db.models import SnapshotControl

            with session_scope() as db:
                bl = (
                    db.query(SnapshotControl)
                    .filter(
                        SnapshotControl.snapshot_id == self._baseline_id,
                        SnapshotControl.entity_id == entity_id,
                    )
                    .first()
                )
                cu = (
                    db.query(SnapshotControl)
                    .filter(
                        SnapshotControl.snapshot_id == self._current_id,
                        SnapshotControl.entity_id == entity_id,
                    )
                    .first()
                )

            def _render(ctrl) -> str:
                if ctrl is None:
                    return "(Not present in this snapshot)"
                raw = ctrl.raw_json
                if raw is None:
                    return "(No raw data stored)"
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        return raw
                return json.dumps(raw, indent=2, default=str)

            self._baseline_te.setPlainText(_render(bl))
            self._current_te.setPlainText(_render(cu))

        except Exception as e:
            msg = f"Error loading snapshot data:\n{e}"
            self._baseline_te.setPlainText(msg)
            self._current_te.setPlainText(msg)


# ─────────────────────────────────────────────────────────────────────────────
# Dialog: Policy Assigned Devices
# ─────────────────────────────────────────────────────────────────────────────

class PolicyDevicesDialog(QDialog):
    """Shows devices that have a compliance status record for this policy."""

    def __init__(self, policy_id: str, policy_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Devices — {policy_name}")
        self.resize(820, 500)
        self._policy_id = policy_id
        self._policy_name = policy_name
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lbl = QLabel(
            f"Devices with a compliance record for  "
            f"<b style='color:#cba6f7'>{self._policy_name}</b>"
        )
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        from PySide6.QtWidgets import QTableWidget, QAbstractItemView
        self._tbl = QTableWidget()
        self._tbl.setColumnCount(4)
        self._tbl.setHorizontalHeaderLabels(["Device Name", "Status", "User", "Last Report"])
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tbl.setColumnWidth(1, 110)
        self._tbl.setColumnWidth(2, 200)
        self._tbl.setColumnWidth(3, 140)
        lay.addWidget(self._tbl)

        self._info = QLabel("")
        self._info.setStyleSheet("color: #a6adc8; font-size: 12px;")
        lay.addWidget(self._info)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _load(self):
        try:
            from app.db.database import session_scope
            from app.db.models import DeviceComplianceStatus, ManagedDevice
            from PySide6.QtWidgets import QTableWidgetItem

            STATUS_COLORS = {
                "compliant": "#a6e3a1",
                "noncompliant": "#f38ba8",
                "error": "#fab387",
                "conflict": "#f9e2af",
                "unknown": "#a6adc8",
                "inGracePeriod": "#f9e2af",
            }

            with session_scope() as db:
                rows = (
                    db.query(DeviceComplianceStatus)
                    .filter(DeviceComplianceStatus.policy_id == self._policy_id)
                    .order_by(DeviceComplianceStatus.status)
                    .all()
                )
                result = []
                for r in rows:
                    dev = (
                        db.query(ManagedDevice)
                        .filter(ManagedDevice.device_id == r.device_id)
                        .first()
                    )
                    result.append(
                        {
                            "name": dev.device_name if dev else r.device_id,
                            "status": r.status or "unknown",
                            "user": r.user_principal_name or r.user_name or "—",
                            "last_report": (
                                r.last_report_datetime.strftime("%Y-%m-%d %H:%M")
                                if r.last_report_datetime
                                else "—"
                            ),
                        }
                    )

            self._tbl.setRowCount(len(result))
            for i, row in enumerate(result):
                self._tbl.setItem(i, 0, QTableWidgetItem(row["name"]))
                st_item = QTableWidgetItem(row["status"])
                st_item.setForeground(
                    QColor(STATUS_COLORS.get(row["status"], "#a6adc8"))
                )
                self._tbl.setItem(i, 1, st_item)
                self._tbl.setItem(i, 2, QTableWidgetItem(row["user"]))
                self._tbl.setItem(i, 3, QTableWidgetItem(row["last_report"]))

            self._info.setText(
                f"{len(result)} device record(s) found for this policy."
                if result
                else "No compliance records found. Run a sync to populate data."
            )
        except Exception as e:
            self._info.setText(f"Error loading data: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Device Explorer context menu
# ─────────────────────────────────────────────────────────────────────────────

def build_device_context_menu(
    row_data: dict,
    pos: QPoint,
    parent_widget,
    on_view_detail: Optional[Callable[[str], None]] = None,
    on_explain: Optional[Callable[[str], None]] = None,
    on_refresh_table: Optional[Callable[[], None]] = None,
):
    """
    Build and exec the device right-click context menu.

    Parameters
    ----------
    row_data        : dict from FilterableTable (device record)
    pos             : global screen position for the menu
    parent_widget   : owning widget (for dialogs)
    on_view_detail  : callback(device_id) → navigate to Device Detail page
    on_explain      : callback(device_id) → navigate to Explain State page
    on_refresh_table: callback() → refresh Device Explorer table after sync
    """
    device_id = row_data.get("id", "")
    device_name = row_data.get("device_name", "Unknown")
    serial = row_data.get("serial_number", "")
    user_upn = row_data.get("user_upn", "")
    compliance = row_data.get("compliance_state", "")
    os_name = row_data.get("os", "")

    menu = _styled_menu(parent_widget)

    # ── Header ──────────────────────────────────────────────────────────────
    _section_header(menu, f"🖥️  {device_name}")
    if os_name or compliance:
        meta = QAction(f"    {os_name}  ·  {compliance}", menu)
        meta.setEnabled(False)
        menu.addAction(meta)
    menu.addSeparator()

    # ── Navigation ──────────────────────────────────────────────────────────
    act_detail = QAction("📋  View Device Details", menu)
    if on_view_detail and device_id:
        act_detail.triggered.connect(lambda: on_view_detail(device_id))
    else:
        act_detail.setEnabled(False)
    menu.addAction(act_detail)

    act_explain = QAction("🔍  Explain Device State", menu)
    if on_explain and device_id:
        act_explain.triggered.connect(lambda: on_explain(device_id))
    else:
        act_explain.setEnabled(False)
    menu.addAction(act_explain)

    menu.addSeparator()

    # ── Sync ─────────────────────────────────────────────────────────────────
    act_sync = QAction("↻  Force Sync This Device", menu)
    if device_id:
        act_sync.triggered.connect(
            lambda: _force_sync_device(device_id, device_name, parent_widget, on_refresh_table)
        )
    else:
        act_sync.setEnabled(False)
    menu.addAction(act_sync)

    menu.addSeparator()

    # ── Copy submenu ─────────────────────────────────────────────────────────
    copy_menu = _styled_menu(parent_widget)
    copy_menu.setTitle("📋  Copy…")

    _add_copy(copy_menu, f"Device Name       {device_name}", device_name)
    if device_id:
        short_id = f"{device_id[:8]}…" if len(device_id) > 8 else device_id
        _add_copy(copy_menu, f"Device ID          {short_id}", device_id)
    if serial:
        _add_copy(copy_menu, f"Serial Number    {serial}", serial)
    if user_upn:
        _add_copy(copy_menu, f"User UPN          {user_upn}", user_upn)
    copy_menu.addSeparator()
    _add_copy(copy_menu, "Full Row as JSON", json.dumps(row_data, default=str, indent=2))
    menu.addMenu(copy_menu)

    menu.addSeparator()

    # ── Open in portal ────────────────────────────────────────────────────────
    act_intune = QAction("🌐  Open in Intune Portal", menu)
    if device_id:
        act_intune.triggered.connect(
            lambda: webbrowser.open(_url_device_intune(device_id))
        )
    else:
        act_intune.setEnabled(False)
    menu.addAction(act_intune)

    act_entra = QAction("🌐  Open in Entra Portal", menu)
    act_entra.triggered.connect(lambda: webbrowser.open(_url_device_entra(device_id)))
    menu.addAction(act_entra)

    menu.addSeparator()

    # ── Export submenu ───────────────────────────────────────────────────────
    exp_menu = _styled_menu(parent_widget)
    exp_menu.setTitle("📤  Export Row…")
    act_ej = QAction("Export as JSON", exp_menu)
    act_ej.triggered.connect(lambda: _export_json(row_data, parent_widget))
    exp_menu.addAction(act_ej)
    act_ec = QAction("Export as CSV", exp_menu)
    act_ec.triggered.connect(lambda: _export_csv(row_data, parent_widget))
    exp_menu.addAction(act_ec)
    menu.addMenu(exp_menu)

    menu.exec(pos)


def _add_copy(menu: QMenu, label: str, value: str):
    act = QAction(label, menu)
    act.triggered.connect(lambda: _clip(value))
    menu.addAction(act)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Policy Explorer context menu
# ─────────────────────────────────────────────────────────────────────────────

def build_policy_context_menu(
    row_data: dict,
    pos: QPoint,
    parent_widget,
    get_selected_rows: Optional[Callable[[], list[dict]]] = None,
    on_explain: Optional[Callable[[str], None]] = None,
):
    """
    Build and exec the policy right-click context menu.

    Parameters
    ----------
    row_data         : dict of the right-clicked policy row
    pos              : global screen position
    parent_widget    : owning widget
    get_selected_rows: callable() → list of currently selected row dicts
                       (used to enable the "Compare 2 policies" action)
    on_explain       : callback(policy_id) → navigate to Explain State
    """
    policy_id = row_data.get("id", "")
    policy_name = row_data.get("display_name", "Unknown")
    policy_type = row_data.get("control_type", "")
    assignments = row_data.get("assignment_count", "?")

    menu = _styled_menu(parent_widget)

    # ── Header ───────────────────────────────────────────────────────────────
    _section_header(menu, f"📑  {policy_name}")
    meta = QAction(f"    {policy_type}  ·  {assignments} assignment(s)", menu)
    meta.setEnabled(False)
    menu.addAction(meta)
    menu.addSeparator()

    # ── Assigned devices (compliance only) ───────────────────────────────────
    act_devices = QAction("🖥️  Show Assigned Devices", menu)
    if policy_id and "compliance" in policy_type.lower():
        act_devices.triggered.connect(
            lambda: PolicyDevicesDialog(policy_id, policy_name, parent_widget).exec()
        )
    else:
        act_devices.setEnabled(bool(policy_id))
        if policy_id and "compliance" not in policy_type.lower():
            act_devices.setToolTip("Available for compliance policies only")
    menu.addAction(act_devices)

    # ── Policy diff ───────────────────────────────────────────────────────────
    selected = get_selected_rows() if get_selected_rows else []
    # Filter to unique IDs (ignore current row already counted)
    selected_ids = [r.get("id") for r in selected]

    if len(selected) == 2:
        act_diff = QAction(f"⚖️  Compare Selected Policies (2 selected)", menu)
        act_diff.triggered.connect(
            lambda: _show_policy_diff(selected[0], selected[1], parent_widget)
        )
    elif len(selected) > 2:
        act_diff = QAction(f"⚖️  Compare Policies (select exactly 2)", menu)
        act_diff.setEnabled(False)
    else:
        act_diff = QAction("⚖️  Compare Policies (Ctrl+click to select 2)", menu)
        act_diff.setEnabled(False)
    menu.addAction(act_diff)

    menu.addSeparator()

    # ── Copy submenu ─────────────────────────────────────────────────────────
    copy_menu = _styled_menu(parent_widget)
    copy_menu.setTitle("📋  Copy…")
    _add_copy(copy_menu, f"Policy Name       {policy_name}", policy_name)
    if policy_id:
        short_id = f"{policy_id[:8]}…" if len(policy_id) > 8 else policy_id
        _add_copy(copy_menu, f"Policy ID          {short_id}", policy_id)
    _add_copy(copy_menu, f"Policy Type       {policy_type}", policy_type)
    copy_menu.addSeparator()
    _add_copy(copy_menu, "Full Row as JSON", json.dumps(row_data, default=str, indent=2))
    menu.addMenu(copy_menu)

    menu.addSeparator()

    # ── Open in portal ────────────────────────────────────────────────────────
    act_intune = QAction("🌐  Open in Intune Portal", menu)
    if policy_id:
        act_intune.triggered.connect(
            lambda: webbrowser.open(_url_policy_intune(policy_id, policy_type))
        )
    else:
        act_intune.setEnabled(False)
    menu.addAction(act_intune)

    menu.addSeparator()

    # ── Export ────────────────────────────────────────────────────────────────
    exp_menu = _styled_menu(parent_widget)
    exp_menu.setTitle("📤  Export Row…")
    act_ej = QAction("Export as JSON", exp_menu)
    act_ej.triggered.connect(lambda: _export_json(row_data, parent_widget))
    exp_menu.addAction(act_ej)
    act_ec = QAction("Export as CSV", exp_menu)
    act_ec.triggered.connect(lambda: _export_csv(row_data, parent_widget))
    exp_menu.addAction(act_ec)
    menu.addMenu(exp_menu)

    menu.exec(pos)


def _show_policy_diff(policy_a: dict, policy_b: dict, parent):
    """Load richer policy data from DB then open the diff dialog."""
    a_full = _enrich_policy(policy_a)
    b_full = _enrich_policy(policy_b)
    PolicyDiffDialog(a_full, b_full, parent).exec()


def _enrich_policy(policy: dict) -> dict:
    """Try to add raw_json data from DB to supplement the table row dict."""
    try:
        from app.db.database import session_scope
        from app.db.models import ComplianceControl

        pid = policy.get("id", "")
        if not pid:
            return policy
        with session_scope() as db:
            row = (
                db.query(ComplianceControl)
                .filter(ComplianceControl.control_id == pid)
                .first()
            )
            if row and row.raw_json:
                raw = (
                    json.loads(row.raw_json)
                    if isinstance(row.raw_json, str)
                    else row.raw_json
                )
                merged = dict(policy)
                merged.update(raw)
                return merged
    except Exception:
        pass
    return policy


# ─────────────────────────────────────────────────────────────────────────────
# 3a. Governance — Snapshot table context menu
# ─────────────────────────────────────────────────────────────────────────────

def build_snapshot_context_menu(
    snap_id: int,
    snap_name: str,
    pos: QPoint,
    parent_widget,
    on_set_baseline: Optional[Callable[[int], None]] = None,
    on_set_current: Optional[Callable[[int], None]] = None,
    on_delete: Optional[Callable[[int], None]] = None,
):
    menu = _styled_menu(parent_widget)

    _section_header(menu, f"📸  {snap_name or f'Snapshot #{snap_id}'}")
    menu.addSeparator()

    # ── Use in comparison ─────────────────────────────────────────────────────
    act_bl = QAction("◀  Use as Baseline for Compare", menu)
    if on_set_baseline:
        act_bl.triggered.connect(lambda: on_set_baseline(snap_id))
    else:
        act_bl.setEnabled(False)
    menu.addAction(act_bl)

    act_cu = QAction("▶  Use as Current for Compare", menu)
    if on_set_current:
        act_cu.triggered.connect(lambda: on_set_current(snap_id))
    else:
        act_cu.setEnabled(False)
    menu.addAction(act_cu)

    menu.addSeparator()

    # ── Copy ──────────────────────────────────────────────────────────────────
    copy_menu = _styled_menu(parent_widget)
    copy_menu.setTitle("📋  Copy…")
    _add_copy(copy_menu, f"Snapshot Name  {snap_name}", snap_name)
    _add_copy(copy_menu, f"Snapshot ID      {snap_id}", str(snap_id))
    menu.addMenu(copy_menu)

    menu.addSeparator()

    # ── Delete ────────────────────────────────────────────────────────────────
    act_del = QAction("🗑️  Delete Snapshot…", menu)
    act_del.setObjectName("danger")
    act_del.setStyleSheet("color: #f38ba8;")
    if on_delete:
        act_del.triggered.connect(
            lambda: _confirm_delete_snapshot(snap_id, snap_name, parent_widget, on_delete)
        )
    else:
        act_del.setEnabled(False)
    menu.addAction(act_del)

    menu.exec(pos)


def _confirm_delete_snapshot(snap_id, snap_name, parent, on_delete):
    reply = QMessageBox.question(
        parent,
        "Delete Snapshot",
        f"Permanently delete snapshot:\n\n"
        f"  '{snap_name}'  (ID: {snap_id})\n\n"
        "This cannot be undone.",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply == QMessageBox.Yes:
        try:
            from app.db.database import session_scope
            from app.db.models import GovernanceSnapshot, SnapshotControl, SnapshotAssignment

            with session_scope() as db:
                db.query(SnapshotControl).filter(
                    SnapshotControl.snapshot_id == snap_id
                ).delete()
                db.query(SnapshotAssignment).filter(
                    SnapshotAssignment.snapshot_id == snap_id
                ).delete(synchronize_session=False) if hasattr(
                    __builtins__, "__import__"
                ) else None
                db.query(GovernanceSnapshot).filter(
                    GovernanceSnapshot.id == snap_id
                ).delete()
            on_delete(snap_id)
        except Exception as e:
            QMessageBox.warning(parent, "Delete Failed", f"Could not delete snapshot:\n{e}")


# ─────────────────────────────────────────────────────────────────────────────
# 3b. Governance — Drift table context menu
# ─────────────────────────────────────────────────────────────────────────────

def build_drift_context_menu(
    row_data: dict,
    pos: QPoint,
    parent_widget,
    baseline_id: int,
    current_id: int,
    on_navigate_policy: Optional[Callable[[str], None]] = None,
    on_navigate_device: Optional[Callable[[str], None]] = None,
):
    """
    Parameters
    ----------
    row_data         : drift row dict (keys: change_type, entity_type, display_name,
                       changed_fields, entity_id)
    baseline_id      : ID of the baseline snapshot
    current_id       : ID of the current snapshot
    on_navigate_policy : callback(policy_id) → go to policy explorer filtered
    on_navigate_device : callback(device_id) → go to device detail
    """
    change_type = str(row_data.get("change_type", "")).upper()
    entity_name = row_data.get("display_name", row_data.get("entity_name", "Unknown"))
    entity_type = row_data.get("entity_type", "")
    entity_id = row_data.get("entity_id", "")
    changed_fields = row_data.get("changed_fields", "")

    icon_map = {"ADDED": "🟢", "REMOVED": "🔴", "MODIFIED": "🟡"}
    icon = icon_map.get(change_type, "🔵")

    menu = _styled_menu(parent_widget)

    _section_header(menu, f"{icon}  {change_type}  ·  {entity_name}")
    if entity_type:
        meta = QAction(f"    Type: {entity_type}", menu)
        meta.setEnabled(False)
        menu.addAction(meta)
    menu.addSeparator()

    # ── Before / After detail ─────────────────────────────────────────────────
    act_detail = QAction("🔬  View Before / After Details", menu)
    act_detail.triggered.connect(
        lambda: DriftDetailDialog(row_data, baseline_id, current_id, parent_widget).exec()
    )
    menu.addAction(act_detail)

    # ── Navigate to entity ────────────────────────────────────────────────────
    if entity_id:
        et_lower = entity_type.lower()
        if "device" in et_lower and on_navigate_device:
            act_nav = QAction("🖥️  Open in Device Detail", menu)
            act_nav.triggered.connect(lambda: on_navigate_device(entity_id))
            menu.addAction(act_nav)
        elif ("policy" in et_lower or "control" in et_lower or "compliance" in et_lower) \
                and on_navigate_policy:
            act_nav = QAction("📑  Open in Policy Explorer", menu)
            act_nav.triggered.connect(lambda: on_navigate_policy(entity_id))
            menu.addAction(act_nav)

    menu.addSeparator()

    # ── Copy submenu ──────────────────────────────────────────────────────────
    copy_menu = _styled_menu(parent_widget)
    copy_menu.setTitle("📋  Copy…")
    summary = f"{change_type} | {entity_type} | {entity_name}"
    _add_copy(copy_menu, "Change Summary", summary)
    if entity_id:
        _add_copy(copy_menu, "Entity ID", entity_id)
    if changed_fields:
        _add_copy(copy_menu, "Changed Fields", str(changed_fields))
    copy_menu.addSeparator()
    _add_copy(copy_menu, "Full Row as JSON", json.dumps(row_data, default=str, indent=2))
    menu.addMenu(copy_menu)

    menu.addSeparator()

    # ── Export ────────────────────────────────────────────────────────────────
    act_exp = QAction("📤  Export Row as JSON", menu)
    act_exp.triggered.connect(lambda: _export_json(row_data, parent_widget))
    menu.addAction(act_exp)

    menu.exec(pos)
