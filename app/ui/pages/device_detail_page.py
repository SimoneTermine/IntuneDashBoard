"""
Device Detail page — tabbed view of a single device's full state.
Tabs: Summary | Compliance | Apps | Groups | Raw Data
"""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QScrollArea, QFrame, QTextEdit,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


COMPLIANCE_COLOR = {
    "compliant":      "#a6e3a1",
    "noncompliant":   "#f38ba8",
    "error":          "#fab387",
    "conflict":       "#f9e2af",
    "inGracePeriod":  "#f9e2af",
    "notApplicable":  "#6c7086",
    "unknown":        "#a6adc8",
}

INSTALL_COLOR = {
    "installed":   "#a6e3a1",
    "failed":      "#f38ba8",
    "notInstalled": "#f9e2af",
    "unknown":     "#a6adc8",
}


class DeviceDetailPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_id = None
        self._setup_ui()

    # ──────────────────────────────────────────────────────────────
    # UI Construction
    # ──────────────────────────────────────────────────────────────
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        self._header_label = QLabel("Select a device from Device Explorer")
        self._header_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(self._header_label)

        self._subtitle = QLabel("")
        self._subtitle.setStyleSheet("color: #a6adc8; font-size: 13px;")
        self._subtitle.setTextFormat(Qt.RichText)
        layout.addWidget(self._subtitle)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._summary_tab = QWidget()
        self._tabs.addTab(self._summary_tab, "📋 Summary")
        self._build_summary_tab()

        self._compliance_tab = QWidget()
        self._tabs.addTab(self._compliance_tab, "🛡️ Compliance")
        self._build_compliance_tab()

        self._apps_tab = QWidget()
        self._tabs.addTab(self._apps_tab, "📦 Apps")
        self._build_apps_tab()

        self._groups_tab = QWidget()
        self._tabs.addTab(self._groups_tab, "👥 Groups")
        self._build_groups_tab()

        self._raw_tab = QWidget()
        self._tabs.addTab(self._raw_tab, "{ } Raw Data")
        self._build_raw_tab()

        btn_row = QHBoxLayout()
        self._explain_btn = QPushButton("🔍  Explain Device State →")
        self._explain_btn.setEnabled(False)
        self._explain_btn.clicked.connect(self._open_explain)
        self._pdf_btn = QPushButton("📄  Generate Evidence PDF")
        self._pdf_btn.setEnabled(False)
        self._pdf_btn.clicked.connect(self._generate_pdf)
        btn_row.addStretch()
        btn_row.addWidget(self._explain_btn)
        btn_row.addWidget(self._pdf_btn)
        layout.addLayout(btn_row)

    def _build_summary_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self._summary_layout = QVBoxLayout(content)
        self._summary_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_content = QLabel("No device selected")
        self._summary_content.setWordWrap(True)
        self._summary_content.setTextFormat(Qt.RichText)
        self._summary_content.setStyleSheet("color: #a6adc8;")
        self._summary_layout.addWidget(self._summary_content)
        self._summary_layout.addStretch()
        scroll.setWidget(content)
        lay = QVBoxLayout(self._summary_tab)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(scroll)

    def _build_compliance_tab(self):
        lay = QVBoxLayout(self._compliance_tab)
        lay.setContentsMargins(0, 4, 0, 0)

        self._compliance_info = QLabel("Run a full sync to populate per-policy compliance data.")
        self._compliance_info.setStyleSheet(
            "background: #313244; border-radius: 6px; padding: 8px; color: #a6adc8; margin-bottom: 4px;"
        )
        self._compliance_info.setWordWrap(True)
        self._compliance_info.setTextFormat(Qt.RichText)
        lay.addWidget(self._compliance_info)

        self._compliance_table = QTableWidget()
        self._compliance_table.setColumnCount(4)
        self._compliance_table.setHorizontalHeaderLabels(["Policy", "Status", "Last Reported", "User"])
        self._compliance_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._compliance_table.setAlternatingRowColors(True)
        self._compliance_table.verticalHeader().setVisible(False)
        self._compliance_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._compliance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._compliance_table.setColumnWidth(1, 120)
        self._compliance_table.setColumnWidth(2, 140)
        self._compliance_table.setColumnWidth(3, 160)
        lay.addWidget(self._compliance_table)

    def _build_apps_tab(self):
        lay = QVBoxLayout(self._apps_tab)
        lay.setContentsMargins(0, 4, 0, 0)

        self._apps_info = QLabel(
            "App install status is synced for LOB and Win32 app types only. "
            "WebApp, OfficeApp, and similar app types do not expose per-device install status via Graph API."
        )
        self._apps_info.setStyleSheet(
            "background: #313244; border-radius: 6px; padding: 8px; color: #a6adc8; margin-bottom: 4px;"
        )
        self._apps_info.setWordWrap(True)
        lay.addWidget(self._apps_info)

        self._apps_table = QTableWidget()
        self._apps_table.setColumnCount(5)
        self._apps_table.setHorizontalHeaderLabels([
            "App Name", "Type", "Install State", "Error Code", "Last Sync"
        ])
        self._apps_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._apps_table.setAlternatingRowColors(True)
        self._apps_table.verticalHeader().setVisible(False)
        self._apps_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._apps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._apps_table.setColumnWidth(1, 130)
        self._apps_table.setColumnWidth(2, 110)
        self._apps_table.setColumnWidth(3, 90)
        self._apps_table.setColumnWidth(4, 140)
        lay.addWidget(self._apps_table)

    def _build_groups_tab(self):
        lay = QVBoxLayout(self._groups_tab)
        lay.setContentsMargins(0, 4, 0, 0)

        self._groups_info = QLabel(
            "Shows Entra ID groups this device/user is a member of (synced via transitiveMemberOf). "
            "These groups determine which Intune policies apply. "
            "Run a full sync to populate this data."
        )
        self._groups_info.setStyleSheet(
            "background: #313244; border-radius: 6px; padding: 8px; color: #a6adc8; margin-bottom: 4px;"
        )
        self._groups_info.setWordWrap(True)
        lay.addWidget(self._groups_info)

        self._groups_table = QTableWidget()
        self._groups_table.setColumnCount(2)
        self._groups_table.setHorizontalHeaderLabels(["Group Name", "Group ID"])
        self._groups_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._groups_table.setAlternatingRowColors(True)
        self._groups_table.verticalHeader().setVisible(False)
        self._groups_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._groups_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._groups_table.setColumnWidth(1, 280)
        lay.addWidget(self._groups_table)

    def _build_raw_tab(self):
        lay = QVBoxLayout(self._raw_tab)
        lay.setContentsMargins(0, 4, 0, 0)
        self._raw_text = QTextEdit()
        self._raw_text.setReadOnly(True)
        self._raw_text.setPlaceholderText("Raw Graph JSON for the selected device.")
        self._raw_text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        lay.addWidget(self._raw_text)

    # ──────────────────────────────────────────────────────────────
    # Data loading
    # ──────────────────────────────────────────────────────────────
    def load_device(self, device_id: str):
        from app.analytics.queries import get_device_by_id, get_device_app_statuses, get_groups
        from app.db.database import session_scope
        from app.db.models import Device, DeviceComplianceStatus, DeviceGroupMembership, Group, App

        self._device_id = device_id
        device = get_device_by_id(device_id)
        if not device:
            self._header_label.setText("Device not found in local DB")
            return

        self._pdf_btn.setEnabled(True)
        self._explain_btn.setEnabled(True)

        # ── Header ──────────────────────────────────────────────
        compliance = device["compliance_state"]
        c = COMPLIANCE_COLOR.get(compliance, "#a6adc8")
        self._header_label.setText(device["device_name"] or device_id)
        self._subtitle.setText(
            f"<span style='color:{c};font-weight:bold'>{compliance.upper()}</span>"
            f" &nbsp;·&nbsp; {device['os']} {device['os_version']}"
            f" &nbsp;·&nbsp; {device['ownership'] or '—'}"
            f" &nbsp;·&nbsp; {device['user_upn'] or 'No user'}"
        )

        # ── Summary tab ────────────────────────────────────────
        fields = [
            ("Device Name",        device["device_name"] or "—"),
            ("Device ID",          device["id"]),
            ("Azure AD Device ID", device.get("azure_ad_device_id") or "—"),
            ("Serial Number",      device["serial_number"] or "—"),
            ("Operating System",   f"{device['os']} {device['os_version']}"),
            ("Compliance State",   compliance.upper()),
            ("Ownership",          device["ownership"] or "—"),
            ("Management State",   device["management_state"] or "—"),
            ("Manufacturer",       device["manufacturer"] or "—"),
            ("Model",              device["model"] or "—"),
            ("IMEI",               device.get("imei") or "—"),
            ("Primary User (UPN)", device["user_upn"] or "—"),
            ("User Display Name",  device["user_name"] or "—"),
            ("Enrolled",           _fmt_dt(device.get("enrolled"))),
            ("Last Intune Sync",   _fmt_dt(device.get("last_sync"))),
            ("Encrypted",          "Yes" if device.get("encrypted") else "No"),
            ("Enrollment Profile", device.get("enroll_profile") or "—"),
            ("Last Data Sync",     _fmt_dt(device.get("synced_at"))),
        ]
        html = "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        for i, (k, v) in enumerate(fields):
            bg = "#313244" if i % 2 == 0 else "#1e1e2e"
            html += (
                f"<tr style='background:{bg}'>"
                f"<td style='padding:7px 14px;color:#a6adc8;font-weight:bold;width:220px'>{k}</td>"
                f"<td style='padding:7px 14px;color:#cdd6f4'>{v}</td>"
                f"</tr>"
            )
        html += "</table>"
        self._summary_content.setText(html)

        # ── Compliance tab ──────────────────────────────────────
        with session_scope() as db:
            statuses = db.query(DeviceComplianceStatus).filter(
                DeviceComplianceStatus.device_id == device_id
            ).order_by(DeviceComplianceStatus.policy_display_name).all()
            compliance_rows = [
                {
                    "policy": s.policy_display_name or s.policy_id,
                    "status": s.status or "unknown",
                    "last_report": _fmt_dt(s.last_report_datetime),
                    "user": s.user_principal_name or s.user_name or "—",
                }
                for s in statuses
            ]

        if compliance_rows:
            self._compliance_info.setText(
                f"<b>{len(compliance_rows)}</b> compliance policy record(s) — "
                f"sourced directly from Microsoft Graph."
            )
            self._compliance_table.setRowCount(len(compliance_rows))
            for i, row in enumerate(compliance_rows):
                st = row["status"]
                color = COMPLIANCE_COLOR.get(st, "#a6adc8")
                self._compliance_table.setItem(i, 0, QTableWidgetItem(row["policy"]))
                st_item = QTableWidgetItem(st)
                st_item.setForeground(QColor(color))
                self._compliance_table.setItem(i, 1, st_item)
                self._compliance_table.setItem(i, 2, QTableWidgetItem(row["last_report"]))
                self._compliance_table.setItem(i, 3, QTableWidgetItem(row["user"]))
        else:
            self._compliance_info.setText(
                f"<b>Overall state: {compliance.upper()}</b><br>"
                "Per-policy compliance data not yet synced. "
                "Run a full sync to populate this tab."
            )
            self._compliance_table.setRowCount(0)

        # ── Apps tab ──────────────────────────────────────────
        app_statuses = get_device_app_statuses(device_id)
        if not app_statuses:
            self._apps_info.setText(
                "No app install status data available for this device. "
                "This is expected if no LOB/Win32 apps are assigned, or if "
                "the app sync hasn't captured install status yet."
            )
        self._apps_table.setRowCount(len(app_statuses))
        for i, a in enumerate(app_statuses):
            state = a.get("install_state", "unknown")
            err = str(a.get("error_code") or "—")
            sync = _fmt_dt(a.get("last_sync"))
            app_type = ""
            with session_scope() as db:
                app_obj = db.get(App, a.get("app_id", ""))
                if app_obj:
                    app_type = app_obj.app_type or ""
            self._apps_table.setItem(i, 0, QTableWidgetItem(a.get("app_name", "—")))
            self._apps_table.setItem(i, 1, QTableWidgetItem(app_type))
            st_item = QTableWidgetItem(state)
            st_item.setForeground(QColor(INSTALL_COLOR.get(state.lower(), "#a6adc8")))
            self._apps_table.setItem(i, 2, st_item)
            self._apps_table.setItem(i, 3, QTableWidgetItem(err))
            self._apps_table.setItem(i, 4, QTableWidgetItem(sync))

        # ── Groups tab ────────────────────────────────────────
        with session_scope() as db:
            memberships = (
                db.query(DeviceGroupMembership, Group)
                .join(Group, Group.id == DeviceGroupMembership.group_id)
                .filter(DeviceGroupMembership.device_id == device_id)
                .order_by(Group.display_name)
                .all()
            )
            group_rows = [
                {"name": g.display_name or "—", "id": g.id}
                for _, g in memberships
            ]

        if group_rows:
            self._groups_info.setText(
                f"<b>{len(group_rows)}</b> group membership(s) synced via transitiveMemberOf. "
                "These groups are used to resolve policy targeting."
            )
        else:
            self._groups_info.setText(
                "No group memberships in local DB for this device. "
                "Make sure a full sync has run — memberships are fetched in the 'memberships' sync step."
            )
        self._groups_table.setRowCount(len(group_rows))
        for i, row in enumerate(group_rows):
            self._groups_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self._groups_table.setItem(i, 1, QTableWidgetItem(row["id"]))

        # ── Raw JSON tab ───────────────────────────────────────
        with session_scope() as db:
            d = db.get(Device, device_id)
            raw = d.raw_json if d else "{}"
        try:
            formatted = json.dumps(json.loads(raw or "{}"), indent=2, ensure_ascii=False)
        except Exception:
            formatted = raw or "{}"
        self._raw_text.setPlainText(formatted)

    def refresh(self):
        if self._device_id:
            self.load_device(self._device_id)

    # ──────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────
    def _generate_pdf(self):
        if not self._device_id:
            return
        from app.export.pdf_generator import generate_device_evidence_pdf
        from PySide6.QtWidgets import QMessageBox
        try:
            path = generate_device_evidence_pdf(self._device_id)
            QMessageBox.information(
                self, "PDF Generated",
                f"Evidence PDF created:\n{path}\n\nSHA256 hash saved alongside."
            )
        except Exception as e:
            QMessageBox.warning(self, "PDF Failed", str(e))

    def _open_explain(self):
        if self._device_id:
            main_window = self.window()
            if hasattr(main_window, "navigate_to_explain"):
                main_window.navigate_to_explain(self._device_id)


def _fmt_dt(val) -> str:
    if val is None:
        return "—"
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d %H:%M")
    return str(val)[:19]
