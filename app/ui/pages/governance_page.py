"""
Governance & Drift page - snapshot, baseline comparison, drift report.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTabWidget, QTextEdit, QGroupBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


class GovernancePage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_diff_report = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Governance & Drift Detection")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── Snapshot tab ────────────────────────────────────────────────
        snap_widget = QWidget()
        snap_layout = QVBoxLayout(snap_widget)
        snap_layout.setContentsMargins(0, 8, 0, 0)

        create_group = QGroupBox("Create Snapshot")
        cgl = QVBoxLayout(create_group)
        name_row = QHBoxLayout()
        self._snap_name = QLineEdit()
        self._snap_name.setPlaceholderText("Snapshot name (optional)...")
        create_btn = QPushButton("📸  Create Snapshot")
        create_btn.clicked.connect(self._create_snapshot)
        name_row.addWidget(self._snap_name)
        name_row.addWidget(create_btn)
        cgl.addLayout(name_row)
        snap_layout.addWidget(create_group)

        list_group = QGroupBox("Saved Snapshots")
        lgl = QVBoxLayout(list_group)
        self._snap_table = QTableWidget()
        self._snap_table.setColumnCount(5)
        self._snap_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Created", "Controls", "Assignments"]
        )
        self._snap_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._snap_table.setAlternatingRowColors(True)
        self._snap_table.verticalHeader().setVisible(False)
        self._snap_table.setColumnWidth(0, 40)
        self._snap_table.setColumnWidth(1, 200)
        self._snap_table.setColumnWidth(2, 140)
        self._snap_table.setColumnWidth(3, 80)
        self._snap_table.setColumnWidth(4, 90)
        self._snap_table.horizontalHeader().setStretchLastSection(True)
        lgl.addWidget(self._snap_table)

        refresh_snaps_btn = QPushButton("↻ Refresh List")
        refresh_snaps_btn.setMaximumWidth(120)
        refresh_snaps_btn.clicked.connect(self._load_snapshots)
        lgl.addWidget(refresh_snaps_btn)

        snap_layout.addWidget(list_group)
        tabs.addTab(snap_widget, "Snapshots")

        # ── Drift Comparison tab ────────────────────────────────────────
        diff_widget = QWidget()
        diff_layout = QVBoxLayout(diff_widget)
        diff_layout.setContentsMargins(0, 8, 0, 0)

        compare_row = QHBoxLayout()
        self._baseline_combo = QComboBox()
        self._baseline_combo.setMinimumWidth(220)
        self._current_combo = QComboBox()
        self._current_combo.setMinimumWidth(220)
        compare_btn = QPushButton("Compare →")
        compare_btn.clicked.connect(self._run_compare)
        compare_row.addWidget(QLabel("Baseline:"))
        compare_row.addWidget(self._baseline_combo)
        compare_row.addWidget(QLabel("vs."))
        compare_row.addWidget(self._current_combo)
        compare_row.addWidget(compare_btn)
        compare_row.addStretch()
        diff_layout.addLayout(compare_row)

        self._diff_summary = QLabel("Select two snapshots and click Compare.")
        self._diff_summary.setWordWrap(True)
        self._diff_summary.setStyleSheet(
            "background: #313244; border-radius: 6px; padding: 10px; color: #cdd6f4;"
        )
        diff_layout.addWidget(self._diff_summary)

        self._diff_table = QTableWidget()
        self._diff_table.setColumnCount(4)
        self._diff_table.setHorizontalHeaderLabels(
            ["Change Type", "Entity Type", "Name / ID", "Changed Fields"]
        )
        self._diff_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._diff_table.setAlternatingRowColors(True)
        self._diff_table.verticalHeader().setVisible(False)
        self._diff_table.setColumnWidth(0, 100)
        self._diff_table.setColumnWidth(1, 100)
        self._diff_table.setColumnWidth(2, 300)
        self._diff_table.horizontalHeader().setStretchLastSection(True)
        diff_layout.addWidget(self._diff_table)

        export_row = QHBoxLayout()
        export_csv_btn = QPushButton("Export CSV")
        export_csv_btn.setStyleSheet("background-color: #45475a;")
        export_csv_btn.clicked.connect(self._export_drift_csv)
        export_json_btn = QPushButton("Export JSON")
        export_json_btn.setStyleSheet("background-color: #45475a;")
        export_json_btn.clicked.connect(self._export_drift_json)
        export_row.addStretch()
        export_row.addWidget(export_csv_btn)
        export_row.addWidget(export_json_btn)
        diff_layout.addLayout(export_row)
        tabs.addTab(diff_widget, "Drift Comparison")

        # ── Blast Radius tab ────────────────────────────────────────────
        blast_widget = QWidget()
        blast_layout = QVBoxLayout(blast_widget)
        blast_layout.setContentsMargins(0, 8, 0, 0)

        blast_row = QHBoxLayout()
        self._blast_combo = QComboBox()
        self._blast_combo.setMinimumWidth(340)
        blast_btn = QPushButton("Estimate Blast Radius →")
        blast_btn.clicked.connect(self._run_blast)
        blast_load_btn = QPushButton("↻ Load Policies")
        blast_load_btn.setStyleSheet("background-color: #45475a;")
        blast_load_btn.clicked.connect(self._load_policies_for_blast)
        blast_row.addWidget(QLabel("Policy:"))
        blast_row.addWidget(self._blast_combo)
        blast_row.addWidget(blast_btn)
        blast_row.addWidget(blast_load_btn)
        blast_row.addStretch()
        blast_layout.addLayout(blast_row)

        self._blast_result = QTextEdit()
        self._blast_result.setReadOnly(True)
        self._blast_result.setPlaceholderText(
            "Select a policy and click 'Estimate Blast Radius'.\n\n"
            "Shows how many devices/groups are targeted by this control's assignments."
        )
        blast_layout.addWidget(self._blast_result)
        tabs.addTab(blast_widget, "Blast Radius")

    # ────────────────────────────────────────────────────────────────────
    # Public
    # ────────────────────────────────────────────────────────────────────
    def refresh(self):
        self._load_snapshots()
        self._load_policies_for_blast()

    # ────────────────────────────────────────────────────────────────────
    # Private helpers
    # ────────────────────────────────────────────────────────────────────
    def _load_snapshots(self):
        from app.analytics.drift import get_snapshots
        snaps = get_snapshots()

        self._snap_table.setRowCount(len(snaps))
        self._baseline_combo.clear()
        self._current_combo.clear()

        for i, s in enumerate(snaps):
            ts = s["created_at"].strftime("%Y-%m-%d %H:%M") if s["created_at"] else ""
            self._snap_table.setItem(i, 0, QTableWidgetItem(str(s["id"])))
            self._snap_table.setItem(i, 1, QTableWidgetItem(s["name"] or ""))
            self._snap_table.setItem(i, 2, QTableWidgetItem(ts))
            self._snap_table.setItem(i, 3, QTableWidgetItem(str(s["control_count"] or 0)))
            self._snap_table.setItem(i, 4, QTableWidgetItem(str(s["assignment_count"] or 0)))
            label = f"[{s['id']}] {s['name']} ({ts})"
            self._baseline_combo.addItem(label, s["id"])
            self._current_combo.addItem(label, s["id"])

    def _load_policies_for_blast(self):
        from app.analytics.queries import get_controls
        controls = get_controls(limit=500)
        self._blast_combo.clear()
        for c in controls:
            self._blast_combo.addItem(
                f"{c['display_name']} ({c['control_type']})", c["id"]
            )

    def _create_snapshot(self):
        from app.analytics.drift import create_snapshot
        name = self._snap_name.text().strip() or None
        try:
            snap_id = create_snapshot(name)
            QMessageBox.information(
                self, "Snapshot Created",
                f"Snapshot created successfully (id={snap_id}).\n"
                "Use it as a baseline for future drift comparisons."
            )
            self._snap_name.clear()
            self._load_snapshots()
        except Exception as e:
            QMessageBox.warning(self, "Snapshot Failed", str(e))

    def _run_compare(self):
        baseline_id = self._baseline_combo.currentData()
        current_id = self._current_combo.currentData()
        if baseline_id is None or current_id is None:
            QMessageBox.warning(self, "No Selection", "Select two snapshots to compare.")
            return
        if baseline_id == current_id:
            QMessageBox.warning(self, "Same Snapshot", "Please select two *different* snapshots.")
            return

        from app.analytics.drift import compare_snapshots
        try:
            report = compare_snapshots(baseline_id, current_id)
            self._last_diff_report = report
            self._display_report(report)
        except Exception as e:
            QMessageBox.warning(self, "Compare Failed", str(e))

    def _display_report(self, report: dict):
        summary = report.get("summary", {})
        added = summary.get("added", 0)
        removed = summary.get("removed", 0)
        modified = summary.get("modified", 0)
        total_baseline = summary.get("total_baseline", 0)
        total_current = summary.get("total_current", 0)

        self._diff_summary.setText(
            f"📊  Drift Summary —  "
            f"✅ Added: {added}   "
            f"🗑️  Removed: {removed}   "
            f"✏️  Modified: {modified}   "
            f"  |  Baseline total: {total_baseline}  →  Current total: {total_current}"
        )

        # Build rows
        rows = []
        COLOR_MAP = {
            "ADDED": "#a6e3a1",
            "REMOVED": "#f38ba8",
            "MODIFIED": "#f9e2af",
        }

        for item in report.get("added", []):
            rows.append(("ADDED", item.get("entity_type", ""), item.get("display_name", item.get("entity_id", "")), ""))
        for item in report.get("removed", []):
            rows.append(("REMOVED", item.get("entity_type", ""), item.get("display_name", item.get("entity_id", "")), ""))
        for item in report.get("modified", []):
            changed = ", ".join(item.get("changed_fields", []))
            rows.append(("MODIFIED", item.get("entity_type", ""), item.get("display_name", item.get("entity_id", "")), changed))

        self._diff_table.setRowCount(len(rows))
        for i, (change_type, entity_type, name, fields) in enumerate(rows):
            ct_item = QTableWidgetItem(change_type)
            color = COLOR_MAP.get(change_type, "#cdd6f4")
            ct_item.setForeground(QColor(color))
            self._diff_table.setItem(i, 0, ct_item)
            self._diff_table.setItem(i, 1, QTableWidgetItem(entity_type))
            self._diff_table.setItem(i, 2, QTableWidgetItem(name))
            self._diff_table.setItem(i, 3, QTableWidgetItem(fields))

    def _export_drift_csv(self):
        if not self._last_diff_report:
            QMessageBox.warning(self, "No Report", "Run a comparison first.")
            return
        from app.export.csv_exporter import export_drift_report_csv
        try:
            path = export_drift_report_csv(self._last_diff_report)
            QMessageBox.information(self, "Exported", f"Drift report CSV saved to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    def _export_drift_json(self):
        if not self._last_diff_report:
            QMessageBox.warning(self, "No Report", "Run a comparison first.")
            return
        from app.export.csv_exporter import export_drift_report_json
        try:
            path = export_drift_report_json(self._last_diff_report)
            QMessageBox.information(self, "Exported", f"Drift report JSON saved to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    def _run_blast(self):
        ctrl_id = self._blast_combo.currentData()
        ctrl_name = self._blast_combo.currentText()
        if not ctrl_id:
            return

        from app.analytics.drift import get_blast_radius
        try:
            result = get_blast_radius(ctrl_id)
            lines = [
                f"Blast Radius Analysis",
                f"Policy: {ctrl_name}",
                f"{'='*60}",
                "",
                f"All Devices targeted: {'YES' if result['all_devices'] else 'No'}",
                f"All Users targeted:   {'YES' if result['all_users'] else 'No'}",
                f"Estimated device impact: {result['estimated_device_impact']} devices",
                "",
                "Groups targeted (include):",
            ]
            for g in result.get("groups_targeted", []):
                mc = f"(~{g['member_count']} members)" if g.get("member_count") else "(member count unknown)"
                lines.append(f"  • {g['name']} {mc}  [{g['id']}]")

            if not result.get("groups_targeted") and not result["all_devices"] and not result["all_users"]:
                lines.append("  (none — policy may not be assigned or assignments not synced)")

            lines += ["", f"⚠️  Note: {result['note']}"]
            self._blast_result.setPlainText("\n".join(lines))
        except Exception as e:
            self._blast_result.setPlainText(f"Error: {e}")
