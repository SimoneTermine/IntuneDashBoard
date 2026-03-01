"""
Overview dashboard page - KPIs, compliance charts, sync status.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QGroupBox,
    QTextEdit, QFrame,
)
from PySide6.QtCore import Qt

from app.ui.widgets.kpi_card import KpiCard
from app.ui.widgets.chart_widget import CompliancePieChart, OsBarChart


class OverviewPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Title
        title = QLabel("Overview")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        # KPI cards row
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self._kpi_total = KpiCard("TOTAL DEVICES", "—", "in Intune", "#89dceb")
        self._kpi_compliant = KpiCard("COMPLIANT", "—", "devices", "#a6e3a1")
        self._kpi_noncompliant = KpiCard("NON-COMPLIANT", "—", "devices", "#f38ba8")
        self._kpi_unknown = KpiCard("UNKNOWN / ERROR", "—", "devices", "#f9e2af")
        self._kpi_policies = KpiCard("TOTAL POLICIES", "—", "controls", "#cba6f7")
        self._kpi_apps = KpiCard("APPS TRACKED", "—", "managed apps", "#74c7ec")

        for kpi in [self._kpi_total, self._kpi_compliant, self._kpi_noncompliant,
                    self._kpi_unknown, self._kpi_policies, self._kpi_apps]:
            kpi_row.addWidget(kpi)
        layout.addLayout(kpi_row)

        # Charts row
        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        compliance_group = QGroupBox("Compliance Breakdown")
        cg_layout = QVBoxLayout(compliance_group)
        self._compliance_chart = CompliancePieChart()
        cg_layout.addWidget(self._compliance_chart)
        charts_row.addWidget(compliance_group)

        os_group = QGroupBox("Devices by OS")
        og_layout = QVBoxLayout(os_group)
        self._os_chart = OsBarChart()
        og_layout.addWidget(self._os_chart)
        charts_row.addWidget(os_group)

        layout.addLayout(charts_row)

        # Recent sync log
        sync_group = QGroupBox("Recent Sync Activity")
        sg_layout = QVBoxLayout(sync_group)
        self._sync_log_text = QTextEdit()
        self._sync_log_text.setReadOnly(True)
        self._sync_log_text.setMaximumHeight(180)
        self._sync_log_text.setPlaceholderText("Sync activity will appear here after first sync.")
        sg_layout.addWidget(self._sync_log_text)
        layout.addWidget(sync_group)

        layout.addStretch()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def refresh(self):
        """Reload KPIs and charts from local DB."""
        try:
            from app.analytics.queries import get_overview_kpis, get_compliance_breakdown, get_os_breakdown, get_recent_sync_logs
            kpis = get_overview_kpis()
            self._kpi_total.set_value(str(kpis["total_devices"]))
            self._kpi_compliant.set_value(str(kpis["compliant"]))
            self._kpi_noncompliant.set_value(str(kpis["noncompliant"]))
            self._kpi_unknown.set_value(str(kpis["unknown"]))
            self._kpi_policies.set_value(str(kpis["total_controls"]))
            self._kpi_apps.set_value(str(kpis["total_apps"]))

            compliance_data = get_compliance_breakdown()
            self._compliance_chart.update_data(compliance_data)

            os_data = get_os_breakdown()
            self._os_chart.update_data(os_data)

            # Sync log
            logs = get_recent_sync_logs(10)
            log_lines = []
            for log in logs:
                ts = log["started_at"].strftime("%Y-%m-%d %H:%M") if log["started_at"] else "?"
                status_icon = "✓" if log["status"] == "success" else "✗" if log["status"] == "failed" else "⟳"
                err = f"  ERROR: {log['error_message']}" if log["error_message"] else ""
                log_lines.append(f"[{ts}] {status_icon} {log['status'].upper()} — {log['devices_synced']} devices{err}")
            self._sync_log_text.setPlainText("\n".join(log_lines) if log_lines else "No sync history")

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Overview refresh failed: {e}")
