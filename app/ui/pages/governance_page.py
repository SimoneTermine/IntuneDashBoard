"""
app/ui/pages/governance_page.py

Governance & Drift page — snapshot, baseline comparison, blast radius.

Changes vs original:
  • Right-click on snapshot rows → use as baseline/current, copy, delete
  • Right-click on drift rows    → before/after dialog, navigate to entity, copy, export
  • Snapshot deletion support
  • entity_id stored as UserRole in drift table items (for DriftDetailDialog)
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
        self._active_baseline_id: int = 0
        self._active_current_id: int = 0
        self._setup_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Governance & Drift Detection")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── Snapshot tab ──────────────────────────────────────────────────────
        snap_widget = QWidget()
        snap_layout = QVBoxLayout(snap_widget)
        snap_layout.setContentsMargins(0, 8, 0, 0)

        create_group = QGroupBox("Create Snapshot")
        cgl = QVBoxLayout(create_group)
        name_row = QHBoxLayout()
        self._snap_name = QLineEdit()
        self._snap_name.setPlaceholderText("Snapshot name (optional)…")
        create_btn = QPushButton("📸  Create Snapshot")
        create_btn.clicked.connect(self._create_snapshot)
        name_row.addWidget(self._snap_name)
        name_row.addWidget(create_btn)
        cgl.addLayout(name_row)
        snap_layout.addWidget(create_group)

        list_group = QGroupBox("Saved Snapshots  (right-click for options)")
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
        self._snap_table.setSelectionBehavior(QAbstractItemView.SelectRows)

        # ── Snapshot context menu ─────────────────────────────────────────────
        self._snap_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._snap_table.customContextMenuRequested.connect(
            self._on_snapshot_context_menu
        )

        lgl.addWidget(self._snap_table)

        refresh_snaps_btn = QPushButton("↻ Refresh List")
        refresh_snaps_btn.setMaximumWidth(120)
        refresh_snaps_btn.clicked.connect(self._load_snapshots)
        lgl.addWidget(refresh_snaps_btn)

        snap_layout.addWidget(list_group)
        tabs.addTab(snap_widget, "Snapshots")

        # ── Drift Comparison tab ──────────────────────────────────────────────
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
        self._diff_summary.setStyleSheet(
            "color: #a6adc8; padding: 6px; background: #313244; border-radius: 4px;"
        )
        diff_layout.addWidget(self._diff_summary)

        hint = QLabel("💡  Right-click any row for Before / After details and more options.")
        hint.setStyleSheet("color: #6c7086; font-size: 11px; padding: 2px 0;")
        diff_layout.addWidget(hint)

        self._diff_table = QTableWidget()
        self._diff_table.setColumnCount(4)
        self._diff_table.setHorizontalHeaderLabels(
            ["Change", "Type", "Name", "Changed Fields"]
        )
        self._diff_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._diff_table.setAlternatingRowColors(True)
        self._diff_table.verticalHeader().setVisible(False)
        self._diff_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._diff_table.setColumnWidth(0, 80)
        self._diff_table.setColumnWidth(1, 120)
        self._diff_table.setColumnWidth(2, 280)
        self._diff_table.horizontalHeader().setStretchLastSection(True)

        # ── Drift context menu ────────────────────────────────────────────────
        self._diff_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._diff_table.customContextMenuRequested.connect(
            self._on_drift_context_menu
        )

        diff_layout.addWidget(self._diff_table)

        export_row = QHBoxLayout()
        export_btn = QPushButton("📄 Export Drift CSV")
        export_btn.clicked.connect(self._export_drift_csv)
        export_row.addStretch()
        export_row.addWidget(export_btn)
        diff_layout.addLayout(export_row)

        tabs.addTab(diff_widget, "Drift Comparison")

        # ── Blast Radius tab ──────────────────────────────────────────────────
        blast_widget = QWidget()
        blast_layout = QVBoxLayout(blast_widget)
        blast_layout.setContentsMargins(0, 8, 0, 0)

        blast_select_row = QHBoxLayout()
        self._blast_combo = QComboBox()
        self._blast_combo.setMinimumWidth(280)
        blast_btn = QPushButton("Analyze Blast Radius →")
        blast_btn.clicked.connect(self._run_blast)
        blast_select_row.addWidget(QLabel("Policy:"))
        blast_select_row.addWidget(self._blast_combo)
        blast_select_row.addWidget(blast_btn)
        blast_select_row.addStretch()
        blast_layout.addLayout(blast_select_row)

        self._blast_result = QTextEdit()
        self._blast_result.setReadOnly(True)
        self._blast_result.setPlaceholderText("Select a policy and click Analyze…")
        blast_layout.addWidget(self._blast_result)
        tabs.addTab(blast_widget, "Blast Radius")

    # ─────────────────────────────────────────────────────────────────────────
    # Public
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self):
        self._load_snapshots()
        self._load_policies_for_blast()

    # ─────────────────────────────────────────────────────────────────────────
    # Snapshot helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _load_snapshots(self):
        from app.analytics.drift import get_snapshots

        snaps = get_snapshots()

        self._snap_table.setRowCount(len(snaps))
        self._baseline_combo.clear()
        self._current_combo.clear()

        for i, s in enumerate(snaps):
            ts = s["created_at"].strftime("%Y-%m-%d %H:%M") if s["created_at"] else ""
            snap_id = s["id"]

            items = [
                QTableWidgetItem(str(snap_id)),
                QTableWidgetItem(s["name"] or ""),
                QTableWidgetItem(ts),
                QTableWidgetItem(str(s["control_count"] or 0)),
                QTableWidgetItem(str(s["assignment_count"] or 0)),
            ]
            # Store snap_id + name as UserRole on every cell for context menu
            snap_meta = {"id": snap_id, "name": s["name"] or f"Snapshot #{snap_id}"}
            for col, item in enumerate(items):
                item.setData(Qt.UserRole, snap_meta)
                self._snap_table.setItem(i, col, item)

            label = f"[{snap_id}] {s['name']} ({ts})"
            self._baseline_combo.addItem(label, snap_id)
            self._current_combo.addItem(label, snap_id)

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
                self,
                "Snapshot Created",
                f"Snapshot created successfully (id={snap_id}).\n"
                "Use it as a baseline for future drift comparisons.",
            )
            self._snap_name.clear()
            self._load_snapshots()
        except Exception as e:
            QMessageBox.warning(self, "Snapshot Failed", str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Snapshot context menu
    # ─────────────────────────────────────────────────────────────────────────

    def _on_snapshot_context_menu(self, pos):
        item = self._snap_table.itemAt(pos)
        if item is None:
            return
        snap_meta = item.data(Qt.UserRole)
        if not snap_meta:
            return

        snap_id = snap_meta.get("id")
        snap_name = snap_meta.get("name", f"Snapshot #{snap_id}")
        global_pos = self._snap_table.viewport().mapToGlobal(pos)

        from app.ui.widgets.context_menus import build_snapshot_context_menu

        build_snapshot_context_menu(
            snap_id=snap_id,
            snap_name=snap_name,
            pos=global_pos,
            parent_widget=self,
            on_set_baseline=self._set_baseline_combo,
            on_set_current=self._set_current_combo,
            on_delete=self._on_snapshot_deleted,
        )

    def _set_baseline_combo(self, snap_id: int):
        idx = self._baseline_combo.findData(snap_id)
        if idx >= 0:
            self._baseline_combo.setCurrentIndex(idx)

    def _set_current_combo(self, snap_id: int):
        idx = self._current_combo.findData(snap_id)
        if idx >= 0:
            self._current_combo.setCurrentIndex(idx)

    def _on_snapshot_deleted(self, snap_id: int):
        self._load_snapshots()
        QMessageBox.information(
            self, "Deleted", f"Snapshot #{snap_id} deleted successfully."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Drift comparison
    # ─────────────────────────────────────────────────────────────────────────

    def _run_compare(self):
        baseline_id = self._baseline_combo.currentData()
        current_id = self._current_combo.currentData()
        if baseline_id is None or current_id is None:
            QMessageBox.warning(self, "No Selection", "Select two snapshots to compare.")
            return
        if baseline_id == current_id:
            QMessageBox.warning(
                self, "Same Snapshot", "Please select two *different* snapshots."
            )
            return

        from app.analytics.drift import compare_snapshots

        try:
            report = compare_snapshots(baseline_id, current_id)
            self._last_diff_report = report
            self._active_baseline_id = baseline_id
            self._active_current_id = current_id
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
            f"📊  Drift Summary  —  "
            f"✅ Added: {added}   "
            f"🗑️  Removed: {removed}   "
            f"✏️  Modified: {modified}   "
            f"  |  Baseline: {total_baseline}  →  Current: {total_current}"
        )

        COLOR_MAP = {
            "ADDED": "#a6e3a1",
            "REMOVED": "#f38ba8",
            "MODIFIED": "#f9e2af",
        }

        rows: list[dict] = []
        for item in report.get("added", []):
            rows.append(
                {
                    "change_type": "ADDED",
                    "entity_type": item.get("entity_type", ""),
                    "display_name": item.get("display_name", item.get("entity_id", "")),
                    "changed_fields": "",
                    "entity_id": item.get("entity_id", ""),
                }
            )
        for item in report.get("removed", []):
            rows.append(
                {
                    "change_type": "REMOVED",
                    "entity_type": item.get("entity_type", ""),
                    "display_name": item.get("display_name", item.get("entity_id", "")),
                    "changed_fields": "",
                    "entity_id": item.get("entity_id", ""),
                }
            )
        for item in report.get("modified", []):
            changed = ", ".join(item.get("changed_fields", []))
            rows.append(
                {
                    "change_type": "MODIFIED",
                    "entity_type": item.get("entity_type", ""),
                    "display_name": item.get("display_name", item.get("entity_id", "")),
                    "changed_fields": changed,
                    "entity_id": item.get("entity_id", ""),
                }
            )

        self._diff_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            ct = row["change_type"]
            color = COLOR_MAP.get(ct, "#cdd6f4")

            ct_item = QTableWidgetItem(ct)
            ct_item.setForeground(QColor(color))
            ct_item.setData(Qt.UserRole, row)  # full dict on every cell

            et_item = QTableWidgetItem(row["entity_type"])
            et_item.setData(Qt.UserRole, row)

            nm_item = QTableWidgetItem(row["display_name"])
            nm_item.setData(Qt.UserRole, row)

            cf_item = QTableWidgetItem(row["changed_fields"])
            cf_item.setData(Qt.UserRole, row)

            self._diff_table.setItem(i, 0, ct_item)
            self._diff_table.setItem(i, 1, et_item)
            self._diff_table.setItem(i, 2, nm_item)
            self._diff_table.setItem(i, 3, cf_item)

    # ─────────────────────────────────────────────────────────────────────────
    # Drift context menu
    # ─────────────────────────────────────────────────────────────────────────

    def _on_drift_context_menu(self, pos):
        item = self._diff_table.itemAt(pos)
        if item is None:
            return
        row_data = item.data(Qt.UserRole)
        if not row_data:
            return

        global_pos = self._diff_table.viewport().mapToGlobal(pos)

        from app.ui.widgets.context_menus import build_drift_context_menu

        build_drift_context_menu(
            row_data=row_data,
            pos=global_pos,
            parent_widget=self,
            baseline_id=self._active_baseline_id,
            current_id=self._active_current_id,
            on_navigate_policy=self._navigate_to_policy,
            on_navigate_device=self._navigate_to_device,
        )

    def _navigate_to_device(self, device_id: str):
        main_win = self.window()
        if hasattr(main_win, "_on_device_selected"):
            main_win._on_device_selected(device_id)

    def _navigate_to_policy(self, policy_id: str):
        main_win = self.window()
        if hasattr(main_win, "_pages"):
            policy_page = main_win._pages.get("policies")
            if policy_page:
                policy_page._policy_table._search_box.setText(policy_id)
                main_win._navigate("policies")

    # ─────────────────────────────────────────────────────────────────────────
    # Export / Blast
    # ─────────────────────────────────────────────────────────────────────────

    def _export_drift_csv(self):
        if not self._last_diff_report:
            QMessageBox.warning(self, "No Report", "Run a comparison first.")
            return
        try:
            from app.export.csv_exporter import export_drift_report_csv
            path = export_drift_report_csv(self._last_diff_report)
            QMessageBox.information(self, "Export Complete", f"Drift report saved to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Failed", str(e))

    def _run_blast(self):
        policy_id = self._blast_combo.currentData()
        if not policy_id:
            return
        try:
            from app.analytics.blast_radius import compute_blast_radius
            result = compute_blast_radius(policy_id)
            self._blast_result.setPlainText(result)
        except Exception as e:
            self._blast_result.setPlainText(f"Error: {e}")
