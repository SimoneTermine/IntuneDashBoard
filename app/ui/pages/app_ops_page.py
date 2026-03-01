"""
App Ops page - deployment status, failures, error clustering.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QGroupBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from app.ui.widgets.filterable_table import FilterableTable


FAIL_COLUMNS = [
    ("name", "App Name", 260),
    ("app_id", "App ID", 140),
    ("fail_count", "Failed Devices", 120),
]

DEVICE_APP_COLUMNS = [
    ("app_name", "App", 250),
    ("install_state", "State", 120),
    ("error_code", "Error Code", 100),
    ("last_sync", "Last Sync", 140),
]


class AppOpsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("App Operations")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        info = QLabel(
            "App install status data is collected from the Microsoft Graph beta API. "
            "Availability depends on app type and Intune reporting. "
            "Data is best-effort and limited to the last 50 apps per sync cycle."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a6adc8; font-size: 12px; padding: 6px; "
                           "background: #313244; border-radius: 6px;")
        layout.addWidget(info)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # Top failures
        fail_widget = QWidget()
        fl = QVBoxLayout(fail_widget)
        fl.setContentsMargins(0, 8, 0, 0)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setMaximumWidth(90)
        refresh_btn.clicked.connect(self.refresh)
        fl.addWidget(refresh_btn)

        self._fail_table = FilterableTable(FAIL_COLUMNS)
        fl.addWidget(self._fail_table)

        # Error code clustering
        error_group = QGroupBox("Error Code Clustering")
        egl = QVBoxLayout(error_group)
        self._error_table = QTableWidget()
        self._error_table.setColumnCount(3)
        self._error_table.setHorizontalHeaderLabels(["Error Code (Hex)", "Affected Devices", "Common Meaning"])
        self._error_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._error_table.setAlternatingRowColors(True)
        self._error_table.verticalHeader().setVisible(False)
        self._error_table.setColumnWidth(0, 130)
        self._error_table.setColumnWidth(1, 110)
        self._error_table.horizontalHeader().setStretchLastSection(True)
        egl.addWidget(self._error_table)
        fl.addWidget(error_group)
        tabs.addTab(fail_widget, "Top App Failures")

        # All apps tab
        apps_widget = QWidget()
        al = QVBoxLayout(apps_widget)
        al.setContentsMargins(0, 8, 0, 0)
        self._all_apps_table = FilterableTable(FAIL_COLUMNS + [("app_type", "Type", 120)])
        al.addWidget(self._all_apps_table)
        tabs.addTab(apps_widget, "All Apps")

    def refresh(self):
        from app.analytics.queries import get_app_failures_summary, get_apps
        from app.db.database import session_scope
        from app.db.models import DeviceAppStatus
        from sqlalchemy import func

        # Top failures
        fails = get_app_failures_summary()
        self._fail_table.load_data(fails)

        # All apps
        apps = get_apps()
        self._all_apps_table.load_data(apps)

        # Error clustering
        with session_scope() as db:
            rows = db.query(
                DeviceAppStatus.error_code,
                func.count(DeviceAppStatus.device_id.distinct()).label("device_count")
            ).filter(
                DeviceAppStatus.error_code != None,
                DeviceAppStatus.error_code != 0,
            ).group_by(DeviceAppStatus.error_code).order_by(
                func.count(DeviceAppStatus.device_id.distinct()).desc()
            ).limit(20).all()

        ERROR_MEANINGS = {
            0x87D1041C: "App not detected after install",
            0x80070002: "File not found",
            0x87D300C9: "App installation failed",
            0x87D13B64: "MDM enrollment failed",
            0x87D1313C: "No license available",
        }

        self._error_table.setRowCount(len(rows))
        for i, (code, count) in enumerate(rows):
            if code is None:
                continue
            hex_code = f"0x{code:08X}" if isinstance(code, int) else str(code)
            meaning = ERROR_MEANINGS.get(code, "See Microsoft error code reference")
            self._error_table.setItem(i, 0, QTableWidgetItem(hex_code))
            count_item = QTableWidgetItem(str(count))
            count_item.setForeground(QColor("#f38ba8"))
            self._error_table.setItem(i, 1, count_item)
            self._error_table.setItem(i, 2, QTableWidgetItem(meaning))
