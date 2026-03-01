"""
Policy/App Explorer page.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTabWidget, QTextEdit, QGroupBox,
)
from PySide6.QtCore import Qt

from app.ui.widgets.filterable_table import FilterableTable


POLICY_COLUMNS = [
    ("display_name", "Policy Name", 260),
    ("control_type", "Type", 140),
    ("platform", "Platform", 90),
    ("assignment_count", "Assignments", 100),
    ("last_modified", "Last Modified", 140),
    ("api_source", "API", 60),
]

APP_COLUMNS = [
    ("display_name", "App Name", 250),
    ("app_type", "Type", 130),
    ("publisher", "Publisher", 160),
    ("is_assigned", "Assigned", 80),
    ("last_modified", "Last Modified", 140),
]


class PolicyExplorerPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_control_id = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Policy & App Explorer")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Policies tab
        self._policy_widget = QWidget()
        self._tabs.addTab(self._policy_widget, "Policies")
        self._build_policy_tab()

        # Apps tab
        self._app_widget = QWidget()
        self._tabs.addTab(self._app_widget, "Apps")
        self._build_app_tab()

        # Assignment detail panel
        self._detail_group = QGroupBox("Assignment Details")
        detail_layout = QVBoxLayout(self._detail_group)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setMaximumHeight(140)
        self._detail_text.setPlaceholderText("Select a policy to see its assignments...")
        detail_layout.addWidget(self._detail_text)
        layout.addWidget(self._detail_group)

    def _build_policy_tab(self):
        layout = QVBoxLayout(self._policy_widget)
        layout.setContentsMargins(0, 8, 0, 0)

        filter_row = QHBoxLayout()
        self._type_filter = QComboBox()
        self._type_filter.addItems(["All Types", "compliance_policy", "config_policy",
                                     "settings_catalog", "endpoint_security"])
        self._type_filter.setMaximumWidth(180)
        self._type_filter.currentTextChanged.connect(self.refresh_policies)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setMaximumWidth(90)
        refresh_btn.clicked.connect(self.refresh_policies)

        filter_row.addWidget(QLabel("Type:"))
        filter_row.addWidget(self._type_filter)
        filter_row.addStretch()
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        self._policy_table = FilterableTable(POLICY_COLUMNS)
        self._policy_table.row_selected.connect(self._on_policy_selected)
        self._policy_table.export_requested.connect(self._export_policies)
        layout.addWidget(self._policy_table)

    def _build_app_tab(self):
        layout = QVBoxLayout(self._app_widget)
        layout.setContentsMargins(0, 8, 0, 0)
        self._app_table = FilterableTable(APP_COLUMNS)
        self._app_table.export_requested.connect(self._export_apps)
        layout.addWidget(self._app_table)

    def refresh(self):
        self.refresh_policies()
        self.refresh_apps()

    def refresh_policies(self):
        from app.analytics.queries import get_controls
        ctrl_type = self._type_filter.currentText()
        ctrl_type = "" if ctrl_type == "All Types" else ctrl_type
        data = get_controls(control_type=ctrl_type)
        self._policy_table.load_data(data)

    def refresh_apps(self):
        from app.analytics.queries import get_apps
        data = get_apps()
        self._app_table.load_data(data)

    def _on_policy_selected(self, row_idx, row_data):
        ctrl_id = row_data.get("id", "")
        self._selected_control_id = ctrl_id
        if not ctrl_id:
            return

        from app.analytics.queries import get_assignments_for_control, get_controls
        assignments = get_assignments_for_control(ctrl_id)
        if assignments:
            lines = [f"Assignments for '{row_data.get('display_name', '')}':\n"]
            for a in assignments:
                intent_icon = "✓ include" if a["intent"] == "include" else "✗ exclude"
                filter_note = f" [filter: {a['filter_id']}]" if a.get("filter_id") else ""
                lines.append(f"  [{intent_icon}] {a['target_type']}: {a['target_id']}{filter_note}")
            self._detail_text.setPlainText("\n".join(lines))
        else:
            self._detail_text.setPlainText(f"No assignments found for policy '{row_data.get('display_name', '')}'\nMay not be synced yet.")

    def _export_policies(self):
        from app.export.csv_exporter import export_controls_csv
        try:
            path = export_controls_csv()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Export", f"Policies exported to:\n{path}")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Failed", str(e))

    def _export_apps(self):
        from app.analytics.queries import get_apps
        from app.export.csv_exporter import export_csv
        from datetime import datetime
        try:
            data = get_apps(limit=5000)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = export_csv(data, f"apps_{ts}.csv")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Export", f"Apps exported to:\n{path}")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Export Failed", str(e))
