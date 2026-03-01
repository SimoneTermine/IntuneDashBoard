"""
app/ui/pages/device_explorer_page.py

Device Explorer page — list, filter, search devices.

Changes vs original:
  • Right-click context menu on every device row (sync, copy, portal, export, navigate)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFrame, QSplitter,
)
from PySide6.QtCore import Qt, Signal

from app.ui.widgets.filterable_table import FilterableTable


DEVICE_COLUMNS = [
    ("device_name", "Device Name", 180),
    ("os", "OS", 90),
    ("os_version", "Version", 100),
    ("compliance_state", "Compliance", 100),
    ("ownership", "Ownership", 90),
    ("user_upn", "User", 200),
    ("last_sync", "Last Sync", 140),
    ("model", "Model", 140),
    ("serial_number", "Serial", 120),
]


class DeviceExplorerPage(QWidget):

    device_selected = Signal(str)  # device_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_device_id = None
        self._setup_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # ── Title + filters row ───────────────────────────────────────────────
        title_row = QHBoxLayout()
        title = QLabel("Device Explorer")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        title_row.addWidget(title)
        title_row.addStretch()

        self._compliance_filter = QComboBox()
        self._compliance_filter.addItems(
            ["All States", "compliant", "noncompliant", "unknown", "error"]
        )
        self._compliance_filter.setMaximumWidth(140)
        self._compliance_filter.currentTextChanged.connect(self._on_filter_changed)

        self._os_filter = QComboBox()
        self._os_filter.addItems(["All OS", "Windows", "iOS", "Android", "macOS"])
        self._os_filter.setMaximumWidth(120)
        self._os_filter.currentTextChanged.connect(self._on_filter_changed)

        self._ownership_filter = QComboBox()
        self._ownership_filter.addItems(
            ["All Ownership", "company", "personal", "unknown"]
        )
        self._ownership_filter.setMaximumWidth(140)
        self._ownership_filter.currentTextChanged.connect(self._on_filter_changed)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setMaximumWidth(100)
        refresh_btn.clicked.connect(self.refresh)

        for w in [
            QLabel("State:"), self._compliance_filter,
            QLabel("OS:"), self._os_filter,
            QLabel("Owner:"), self._ownership_filter,
            refresh_btn,
        ]:
            title_row.addWidget(w)

        layout.addLayout(title_row)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = FilterableTable(DEVICE_COLUMNS)
        self._table.row_selected.connect(self._on_device_selected)
        self._table.export_requested.connect(self._export)

        # ── Right-click context menu ──────────────────────────────────────────
        self._table.set_context_menu_handler(self._on_context_menu)

        layout.addWidget(self._table)

        # ── Bottom button ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._detail_btn = QPushButton("View Device Details →")
        self._detail_btn.setEnabled(False)
        self._detail_btn.clicked.connect(self._open_detail)
        btn_row.addStretch()
        btn_row.addWidget(self._detail_btn)
        layout.addLayout(btn_row)

    # ─────────────────────────────────────────────────────────────────────────
    # Data
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self):
        from app.analytics.queries import get_devices

        compliance = self._compliance_filter.currentText()
        compliance = "" if compliance == "All States" else compliance
        os_filter = self._os_filter.currentText()
        os_filter = "" if os_filter == "All OS" else os_filter
        ownership = self._ownership_filter.currentText()
        ownership = "" if ownership == "All Ownership" else ownership

        data = get_devices(
            compliance_filter=compliance,
            os_filter=os_filter,
            ownership_filter=ownership,
            limit=2000,
        )
        self._table.load_data(data)

    def _on_filter_changed(self):
        self.refresh()

    def _on_device_selected(self, row_idx: int, row_data: dict):
        self._current_device_id = row_data.get("id")
        self._detail_btn.setEnabled(bool(self._current_device_id))

    def _open_detail(self):
        if self._current_device_id:
            self.device_selected.emit(self._current_device_id)

    def _export(self):
        from app.export.csv_exporter import export_devices_csv
        from PySide6.QtWidgets import QMessageBox
        try:
            path = export_devices_csv()
            QMessageBox.information(
                self, "Export Complete", f"Devices exported to:\n{path}"
            )
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Context menu
    # ─────────────────────────────────────────────────────────────────────────

    def _on_context_menu(self, row_data: dict, global_pos):
        from app.ui.widgets.context_menus import build_device_context_menu
        build_device_context_menu(
            row_data=row_data,
            pos=global_pos,
            parent_widget=self,
            on_view_detail=self._navigate_to_detail,
            on_explain=self._navigate_to_explain,
            on_refresh_table=self.refresh,
        )

    def _navigate_to_detail(self, device_id: str):
        """Navigate to Device Detail page."""
        self.device_selected.emit(device_id)

    def _navigate_to_explain(self, device_id: str):
        """Navigate to Explain State page."""
        main_win = self.window()
        if hasattr(main_win, "navigate_to_explain"):
            main_win.navigate_to_explain(device_id)
