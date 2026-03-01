"""
Explainability page - "Why is this device non-compliant?"
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QScrollArea, QFrame, QGroupBox, QTextEdit, QTabWidget, QProgressBar,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


class ExplainabilityPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Explain Device State")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Select a device to understand why it is compliant, non-compliant, or in a conflict state."
        )
        subtitle.setStyleSheet("color: #a6adc8;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Device selector
        input_row = QHBoxLayout()
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(360)
        self._device_combo.setEditable(True)
        self._device_combo.setPlaceholderText("Select or search device...")

        self._analyze_btn = QPushButton("Analyze →")
        self._analyze_btn.clicked.connect(self._run_analysis)
        self._analyze_btn.setMinimumWidth(110)

        self._refresh_list_btn = QPushButton("↻ Load Devices")
        self._refresh_list_btn.setStyleSheet("background-color: #45475a;")
        self._refresh_list_btn.clicked.connect(self._load_device_list)

        input_row.addWidget(QLabel("Device:"))
        input_row.addWidget(self._device_combo)
        input_row.addWidget(self._analyze_btn)
        input_row.addWidget(self._refresh_list_btn)
        input_row.addStretch()
        layout.addLayout(input_row)

        # Completeness badge
        self._completeness_label = QLabel("")
        self._completeness_label.setStyleSheet("color: #f9e2af; font-size: 11px;")
        layout.addWidget(self._completeness_label)

        # Summary banner
        self._summary_label = QLabel("Run an analysis to see the explanation.")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            "background-color: #313244; border-radius: 8px; padding: 12px; color: #cdd6f4;"
        )
        layout.addWidget(self._summary_label)

        # Tabs: results + conflicts
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Results table
        results_widget = QWidget()
        rl = QVBoxLayout(results_widget)
        rl.setContentsMargins(0, 8, 0, 0)
        self._results_table = QTableWidget()
        self._results_table.setColumnCount(6)
        self._results_table.setHorizontalHeaderLabels(
            ["Policy Name", "Type", "Status", "Reason Code", "Reason Detail", "Source"]
        )
        self._results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._results_table.setAlternatingRowColors(True)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.horizontalHeader().setStretchLastSection(True)
        self._results_table.setColumnWidth(0, 200)
        self._results_table.setColumnWidth(1, 120)
        self._results_table.setColumnWidth(2, 100)
        self._results_table.setColumnWidth(3, 140)
        self._results_table.setColumnWidth(4, 280)
        rl.addWidget(self._results_table)
        self._tabs.addTab(results_widget, "Policy Results")

        # Conflicts tab
        conflicts_widget = QWidget()
        cl = QVBoxLayout(conflicts_widget)
        cl.setContentsMargins(0, 8, 0, 0)
        self._conflicts_text = QTextEdit()
        self._conflicts_text.setReadOnly(True)
        self._conflicts_text.setPlaceholderText("No conflicts detected or no analysis run yet.")
        cl.addWidget(self._conflicts_text)
        self._tabs.addTab(conflicts_widget, "Conflicts")

        # Assignment graph tab
        ag_widget = QWidget()
        agl = QVBoxLayout(ag_widget)
        agl.setContentsMargins(0, 8, 0, 0)
        self._assign_text = QTextEdit()
        self._assign_text.setReadOnly(True)
        self._assign_text.setPlaceholderText("Assignment paths will appear here after analysis.")
        agl.addWidget(self._assign_text)
        self._tabs.addTab(ag_widget, "Assignment Graph")

    def load_device(self, device_id: str):
        """Pre-select a device and run analysis."""
        # Find in combo
        for i in range(self._device_combo.count()):
            if self._device_combo.itemData(i) == device_id:
                self._device_combo.setCurrentIndex(i)
                break
        else:
            self._device_combo.addItem(device_id, device_id)
            self._device_combo.setCurrentIndex(self._device_combo.count() - 1)
        self._run_analysis()

    def _load_device_list(self):
        from app.analytics.queries import get_devices
        devices = get_devices(limit=1000)
        self._device_combo.clear()
        for d in devices:
            label = f"{d['device_name']} ({d['compliance_state']}) — {d['user_upn']}"
            self._device_combo.addItem(label, d["id"])

    def _run_analysis(self):
        device_id = self._device_combo.currentData()
        if not device_id:
            # Try text as device name lookup
            text = self._device_combo.currentText().strip()
            if text:
                from app.analytics.queries import get_devices
                devices = get_devices(search=text, limit=1)
                if devices:
                    device_id = devices[0]["id"]
        if not device_id:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Device", "Please select a device first.")
            return

        from app.analytics.explainability import ExplainabilityEngine
        try:
            engine = ExplainabilityEngine()
            explanation = engine.explain_device(device_id)
            self._display_explanation(explanation)
        except Exception as e:
            self._summary_label.setText(f"Analysis failed: {e}")
            import logging
            logging.getLogger(__name__).error(f"Explain failed: {e}", exc_info=True)

    def _display_explanation(self, explanation):
        from app.analytics.explainability import DeviceExplanation

        # Summary
        self._summary_label.setText(explanation.summary)

        # Completeness
        completeness_colors = {"full": "#a6e3a1", "partial": "#f9e2af", "minimal": "#f38ba8"}
        color = completeness_colors.get(explanation.data_completeness, "#a6adc8")
        self._completeness_label.setText(
            f"Data completeness: <span style='color:{color};font-weight:bold'>{explanation.data_completeness.upper()}</span> &nbsp; "
            "— Partial/minimal means group memberships or per-policy data not fully synced."
        )
        self._completeness_label.setTextFormat(Qt.RichText)

        # Results table
        self._results_table.setRowCount(len(explanation.results))
        status_colors = {
            "compliant": "#a6e3a1", "noncompliant": "#f38ba8", "error": "#fab387",
            "excluded": "#6c7086", "conflict": "#f9e2af", "unknown": "#a6adc8",
            "applied": "#89dceb", "filtered": "#f9e2af",
        }
        for i, r in enumerate(explanation.results):
            self._results_table.setItem(i, 0, QTableWidgetItem(r.control_name))
            self._results_table.setItem(i, 1, QTableWidgetItem(r.control_type))
            status_item = QTableWidgetItem(r.status)
            c = status_colors.get(r.status.lower(), "#a6adc8")
            status_item.setForeground(QColor(c))
            self._results_table.setItem(i, 2, status_item)
            self._results_table.setItem(i, 3, QTableWidgetItem(r.reason_code))
            self._results_table.setItem(i, 4, QTableWidgetItem(r.reason_detail))
            self._results_table.setItem(i, 5, QTableWidgetItem(r.source))

        # Conflicts
        if explanation.conflicts:
            lines = ["⚡ Potential Conflicts Detected (Heuristic)\n"]
            for c in explanation.conflicts:
                lines.append(f"  [{c.conflict_type}]")
                lines.append(f"    A: {c.control_a_name}")
                lines.append(f"    B: {c.control_b_name}")
                lines.append(f"    Detail: {c.detail}\n")
            self._conflicts_text.setPlainText("\n".join(lines))
        else:
            self._conflicts_text.setPlainText("No conflicts detected.\n\nNote: Conflict detection is heuristic (name-based). Review settings in Intune for definitive analysis.")

        # Assignment graph (tabular)
        ag_lines = [f"Assignment Graph for: {explanation.device_name}\n{'='*60}"]
        for r in explanation.results:
            icon = {"include": "→", "exclude": "✗"}.get(r.intent, "?")
            filter_note = f" [FILTER: {r.filter_id}]" if r.filter_id else ""
            ag_lines.append(
                f"\n  Device: {explanation.device_name}\n"
                f"    {icon} [{r.intent.upper()}] Policy: {r.control_name}\n"
                f"       via: {r.target_type} ({r.target_id}){filter_note}\n"
                f"       outcome: {r.status} [{r.reason_code}]"
            )
        self._assign_text.setPlainText("\n".join(ag_lines))
