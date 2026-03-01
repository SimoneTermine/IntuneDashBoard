"""
app/ui/pages/policy_explorer_page.py

Policy & App Explorer page.

Changes vs original:
  • Right-click context menu on policy rows (diff, assigned devices, copy, portal, export)
  • Multi-select enabled on the policy table (Ctrl+click to pick 2 → compare)
  • Right-click on app rows (copy, portal link, export)
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

    # ─────────────────────────────────────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Policy & App Explorer")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # ── Policies tab ──────────────────────────────────────────────────────
        self._policy_widget = QWidget()
        self._tabs.addTab(self._policy_widget, "Policies")
        self._build_policy_tab()

        # ── Apps tab ──────────────────────────────────────────────────────────
        self._app_widget = QWidget()
        self._tabs.addTab(self._app_widget, "Apps")
        self._build_app_tab()

        # ── Assignment detail panel ────────────────────────────────────────────
        self._detail_group = QGroupBox("Assignment Detail")
        detail_layout = QVBoxLayout(self._detail_group)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setMaximumHeight(140)
        self._detail_text.setPlaceholderText(
            "Select a policy to see its assignments… "
            "(Ctrl+click two policies to compare them)"
        )
        detail_layout.addWidget(self._detail_text)
        layout.addWidget(self._detail_group)

    def _build_policy_tab(self):
        layout = QVBoxLayout(self._policy_widget)
        layout.setContentsMargins(0, 8, 0, 0)

        filter_row = QHBoxLayout()
        self._type_filter = QComboBox()
        self._type_filter.addItems(
            [
                "All Types",
                "compliance_policy",
                "config_policy",
                "settings_catalog",
                "endpoint_security",
            ]
        )
        self._type_filter.setMaximumWidth(180)
        self._type_filter.currentTextChanged.connect(self.refresh_policies)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setMaximumWidth(90)
        refresh_btn.clicked.connect(self.refresh_policies)

        multi_hint = QLabel("Ctrl+click two rows to compare →")
        multi_hint.setStyleSheet("color: #6c7086; font-size: 11px;")

        filter_row.addWidget(QLabel("Type:"))
        filter_row.addWidget(self._type_filter)
        filter_row.addStretch()
        filter_row.addWidget(multi_hint)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        self._policy_table = FilterableTable(POLICY_COLUMNS)
        self._policy_table.row_selected.connect(self._on_policy_selected)
        self._policy_table.export_requested.connect(self._export_policies)

        # Multi-select so users can Ctrl+click two policies then right-click → compare
        self._policy_table.set_multi_select(True)

        # Right-click context menu
        self._policy_table.set_context_menu_handler(self._on_policy_context_menu)

        layout.addWidget(self._policy_table)

    def _build_app_tab(self):
        layout = QVBoxLayout(self._app_widget)
        layout.setContentsMargins(0, 8, 0, 0)
        self._app_table = FilterableTable(APP_COLUMNS)
        self._app_table.export_requested.connect(self._export_apps)

        # Right-click on apps: copy + export + portal link
        self._app_table.set_context_menu_handler(self._on_app_context_menu)

        layout.addWidget(self._app_table)

    # ─────────────────────────────────────────────────────────────────────────
    # Data
    # ─────────────────────────────────────────────────────────────────────────

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

        from app.analytics.queries import get_assignments_for_control

        assignments = get_assignments_for_control(ctrl_id)
        if assignments:
            lines = [f"Assignments for '{row_data.get('display_name', '')}':\n"]
            for a in assignments:
                intent_icon = "✓ include" if a["intent"] == "include" else "✗ exclude"
                filter_note = (
                    f" [filter: {a['filter_id']}]" if a.get("filter_id") else ""
                )
                lines.append(
                    f"  [{intent_icon}] {a['target_type']}: {a['target_id']}{filter_note}"
                )
            self._detail_text.setPlainText("\n".join(lines))
        else:
            self._detail_text.setPlainText(
                f"No assignments found for policy '{row_data.get('display_name', '')}'\n"
                "May not be synced yet."
            )

    def _export_policies(self):
        from app.export.csv_exporter import export_controls_csv
        from PySide6.QtWidgets import QMessageBox
        try:
            path = export_controls_csv()
            QMessageBox.information(self, "Export", f"Policies exported to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    def _export_apps(self):
        from app.analytics.queries import get_apps
        from app.export.csv_exporter import export_csv
        from datetime import datetime
        from PySide6.QtWidgets import QMessageBox
        try:
            data = get_apps(limit=5000)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = export_csv(data, f"apps_{ts}.csv")
            QMessageBox.information(self, "Export", f"Apps exported to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Context menus
    # ─────────────────────────────────────────────────────────────────────────

    def _on_policy_context_menu(self, row_data: dict, global_pos):
        from app.ui.widgets.context_menus import build_policy_context_menu
        build_policy_context_menu(
            row_data=row_data,
            pos=global_pos,
            parent_widget=self,
            get_selected_rows=self._policy_table.get_selected_rows,
        )

    def _on_app_context_menu(self, row_data: dict, global_pos):
        """Lightweight context menu for app rows (no diff / device list)."""
        import json, webbrowser
        from app.ui.widgets.context_menus import _styled_menu, _add_copy, _export_json, _export_csv, _section_header

        app_name = row_data.get("display_name", "Unknown")
        app_id = row_data.get("id", "")
        publisher = row_data.get("publisher", "")

        menu = _styled_menu(self)
        _section_header(menu, f"📦  {app_name}")
        if publisher:
            meta = __import__("PySide6.QtGui", fromlist=["QAction"]).QAction
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QAction
            pub_act = QAction(f"    by {publisher}", menu)
            pub_act.setEnabled(False)
            menu.addAction(pub_act)
        menu.addSeparator()

        copy_menu = _styled_menu(self)
        copy_menu.setTitle("📋  Copy…")
        _add_copy(copy_menu, f"App Name    {app_name}", app_name)
        if app_id:
            _add_copy(copy_menu, "App ID", app_id)
        if publisher:
            _add_copy(copy_menu, f"Publisher   {publisher}", publisher)
        copy_menu.addSeparator()
        _add_copy(copy_menu, "Full Row as JSON", json.dumps(row_data, default=str, indent=2))
        menu.addMenu(copy_menu)

        menu.addSeparator()

        if app_id:
            from PySide6.QtGui import QAction
            act_portal = QAction("🌐  Open in Intune Portal", menu)
            act_portal.triggered.connect(
                lambda: webbrowser.open(
                    f"https://intune.microsoft.com/#view/Microsoft_Intune_Apps"
                    f"/AppOverview.ReactView/appId/{app_id}"
                )
            )
            menu.addAction(act_portal)
            menu.addSeparator()

        exp_menu = _styled_menu(self)
        exp_menu.setTitle("📤  Export Row…")
        from PySide6.QtGui import QAction
        ej = QAction("Export as JSON", exp_menu)
        ej.triggered.connect(lambda: _export_json(row_data, self))
        exp_menu.addAction(ej)
        ec = QAction("Export as CSV", exp_menu)
        ec.triggered.connect(lambda: _export_csv(row_data, self))
        exp_menu.addAction(ec)
        menu.addMenu(exp_menu)

        menu.exec(global_pos)
