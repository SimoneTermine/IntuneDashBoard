"""
Settings page — tenant/auth config, scheduler, storage, privacy.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QCheckBox, QGroupBox,
    QTextEdit, QFileDialog, QMessageBox, QTabWidget, QScrollArea,
    QFrame,
)
from PySide6.QtCore import Qt

from app.config import AppConfig

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth_worker = None
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        main_layout.addWidget(title)

        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # ── Auth tab ────────────────────────────────────────────────────
        auth_widget = QWidget()
        auth_layout = QVBoxLayout(auth_widget)
        auth_layout.setContentsMargins(8, 8, 8, 8)
        auth_layout.setSpacing(12)

        tenant_group = QGroupBox("Tenant & App Registration")
        tgl = QVBoxLayout(tenant_group)

        self._tenant_id = self._labeled_input("Tenant ID (Directory ID):", tgl)
        self._client_id = self._labeled_input("Client ID (Application ID):", tgl)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Auth Mode:"))
        self._auth_mode = QComboBox()
        self._auth_mode.addItems(["device_code", "app_only"])
        self._auth_mode.currentTextChanged.connect(self._on_auth_mode_changed)
        mode_row.addWidget(self._auth_mode)
        mode_row.addStretch()
        tgl.addLayout(mode_row)
        auth_layout.addWidget(tenant_group)

        # App-only cert fields (hidden by default)
        self._cert_group = QGroupBox("Certificate (App-Only Mode)")
        certgl = QVBoxLayout(self._cert_group)
        self._cert_thumbprint = self._labeled_input("Certificate Thumbprint:", certgl)
        cert_path_row = QHBoxLayout()
        cert_path_row.addWidget(QLabel("Certificate File (.pem/.pfx):"))
        self._cert_path = QLineEdit()
        self._cert_path.setPlaceholderText("/path/to/cert.pem")
        browse_cert_btn = QPushButton("Browse…")
        browse_cert_btn.setMaximumWidth(80)
        browse_cert_btn.clicked.connect(self._browse_cert)
        cert_path_row.addWidget(self._cert_path)
        cert_path_row.addWidget(browse_cert_btn)
        certgl.addLayout(cert_path_row)
        self._cert_group.hide()
        auth_layout.addWidget(self._cert_group)

        # Demo mode
        demo_group = QGroupBox("Demo Mode")
        dgl = QVBoxLayout(demo_group)
        self._demo_mode = QCheckBox("Enable Demo Mode (uses synthetic data, no Graph connection needed)")
        dgl.addWidget(self._demo_mode)
        demo_info = QLabel(
            "When enabled, the app loads a sample dataset so you can explore the UI "
            "without real credentials. Disable before connecting to a real tenant."
        )
        demo_info.setWordWrap(True)
        demo_info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        dgl.addWidget(demo_info)
        auth_layout.addWidget(demo_group)

        # Test connection
        conn_group = QGroupBox("Connection Test")
        cgl = QVBoxLayout(conn_group)
        test_row = QHBoxLayout()
        self._test_btn = QPushButton("Test Graph Connection")
        self._test_btn.clicked.connect(self._test_connection)
        self._logout_btn = QPushButton("Clear Token Cache (Logout)")
        self._logout_btn.setObjectName("DangerButton")
        self._logout_btn.clicked.connect(self._logout)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._logout_btn)
        test_row.addStretch()
        cgl.addLayout(test_row)
        self._test_result = QTextEdit()
        self._test_result.setReadOnly(True)
        self._test_result.setMaximumHeight(120)
        self._test_result.setPlaceholderText("Test result appears here…")
        cgl.addWidget(self._test_result)
        auth_layout.addWidget(conn_group)

        # Device Code instructions
        dcode_group = QGroupBox("Device Code Flow — How It Works")
        dcode_gl = QVBoxLayout(dcode_group)
        instructions = QLabel(
            "1. Click 'Sync Now' or trigger authentication.\n"
            "2. A code and URL will appear in a dialog.\n"
            "3. Open the URL on any browser (same or different device).\n"
            "4. Enter the code and sign in with your admin account.\n"
            "5. The app receives the token automatically.\n\n"
            "The token is cached locally in encrypted form and refreshed automatically."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #a6adc8; font-size: 12px;")
        dcode_gl.addWidget(instructions)
        auth_layout.addWidget(dcode_group)

        auth_layout.addStretch()
        tabs.addTab(auth_widget, "Tenant / Auth")

        # ── Scheduler tab ───────────────────────────────────────────────
        sched_widget = QWidget()
        sched_layout = QVBoxLayout(sched_widget)
        sched_layout.setContentsMargins(8, 8, 8, 8)
        sched_layout.setSpacing(12)

        sched_group = QGroupBox("Automatic Sync Scheduler")
        sggl = QVBoxLayout(sched_group)
        self._sync_enabled = QCheckBox("Enable automatic background sync")
        sggl.addWidget(self._sync_enabled)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Sync interval (minutes):"))
        self._sync_interval = QSpinBox()
        self._sync_interval.setRange(5, 1440)
        self._sync_interval.setSingleStep(15)
        self._sync_interval.setValue(60)
        interval_row.addWidget(self._sync_interval)
        interval_row.addStretch()
        sggl.addLayout(interval_row)

        manual_row = QHBoxLayout()
        manual_sync_btn = QPushButton("Run Full Sync Now")
        manual_sync_btn.clicked.connect(self._run_manual_sync)
        manual_row.addWidget(manual_sync_btn)
        manual_row.addStretch()
        sggl.addLayout(manual_row)
        sched_layout.addWidget(sched_group)
        sched_layout.addStretch()
        tabs.addTab(sched_widget, "Scheduler")

        # ── Storage tab ─────────────────────────────────────────────────
        storage_widget = QWidget()
        storage_layout = QVBoxLayout(storage_widget)
        storage_layout.setContentsMargins(8, 8, 8, 8)
        storage_layout.setSpacing(12)

        storage_group = QGroupBox("Storage Paths")
        stgl = QVBoxLayout(storage_group)

        db_row = QHBoxLayout()
        db_row.addWidget(QLabel("Database file:"))
        self._db_path = QLineEdit()
        self._db_path.setReadOnly(True)
        db_row.addWidget(self._db_path)
        stgl.addLayout(db_row)

        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("Export folder:"))
        self._export_dir = QLineEdit()
        browse_export_btn = QPushButton("Browse…")
        browse_export_btn.setMaximumWidth(80)
        browse_export_btn.clicked.connect(self._browse_export)
        export_row.addWidget(self._export_dir)
        export_row.addWidget(browse_export_btn)
        stgl.addLayout(export_row)

        storage_layout.addWidget(storage_group)
        storage_layout.addStretch()
        tabs.addTab(storage_widget, "Storage")

        # ── Privacy tab ─────────────────────────────────────────────────
        privacy_widget = QWidget()
        priv_layout = QVBoxLayout(privacy_widget)
        priv_layout.setContentsMargins(8, 8, 8, 8)

        privacy_text = QTextEdit()
        privacy_text.setReadOnly(True)
        privacy_text.setHtml("""
<h3 style='color:#cba6f7'>Privacy & Data Handling</h3>
<p><b>What is stored locally:</b></p>
<ul>
<li>Microsoft Graph API responses (device metadata, policy definitions, app data) in a local SQLite database.</li>
<li>MSAL authentication token cache (access & refresh tokens) on disk.</li>
<li>Application settings (tenant ID, client ID) in a local JSON config file.</li>
<li>Log files (activity and error logs).</li>
</ul>
<p><b>What is NOT stored or transmitted:</b></p>
<ul>
<li>No data is sent to any server other than Microsoft Graph API (login.microsoftonline.com / graph.microsoft.com).</li>
<li>No telemetry, analytics, or usage data is collected.</li>
<li>This application has no backend server — it is 100% local.</li>
</ul>
<p><b>Security recommendations:</b></p>
<ul>
<li>Store the token cache file securely. On Windows, consider restricting file permissions.</li>
<li>Use the minimum required Graph API permissions (read-only scopes listed in README).</li>
<li>For app-only mode, store the private key in the Windows Certificate Store rather than a file.</li>
<li>Regularly rotate app credentials in Entra ID.</li>
</ul>
<p style='color:#6c7086;font-size:11px'>
Data location: %APPDATA%\\IntuneDashboard\\<br>
Logs: %APPDATA%\\IntuneDashboard\\logs\\
</p>
        """)
        priv_layout.addWidget(privacy_text)
        tabs.addTab(privacy_widget, "Privacy")

        # ── Save button ─────────────────────────────────────────────────
        save_btn = QPushButton("💾  Save Settings")
        save_btn.setMinimumHeight(40)
        save_btn.clicked.connect(self._save_config)
        main_layout.addWidget(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _labeled_input(self, label: str, parent_layout) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(200)
        inp = QLineEdit()
        row.addWidget(lbl)
        row.addWidget(inp)
        parent_layout.addLayout(row)
        return inp

    def _on_auth_mode_changed(self, mode: str):
        self._cert_group.setVisible(mode == "app_only")

    def _load_config(self):
        cfg = AppConfig()
        self._tenant_id.setText(cfg.tenant_id)
        self._client_id.setText(cfg.client_id)
        self._auth_mode.setCurrentText(cfg.auth_mode)
        self._cert_thumbprint.setText(cfg.get("cert_thumbprint", ""))
        self._cert_path.setText(cfg.get("cert_path", ""))
        self._demo_mode.setChecked(cfg.demo_mode)
        self._sync_enabled.setChecked(cfg.sync_enabled)
        self._sync_interval.setValue(cfg.sync_interval_minutes)
        self._db_path.setText(cfg.db_path)
        self._export_dir.setText(cfg.export_dir)
        self._on_auth_mode_changed(cfg.auth_mode)

    def _save_config(self):
        cfg = AppConfig()
        cfg.update({
            "tenant_id": self._tenant_id.text().strip(),
            "client_id": self._client_id.text().strip(),
            "auth_mode": self._auth_mode.currentText(),
            "cert_thumbprint": self._cert_thumbprint.text().strip(),
            "cert_path": self._cert_path.text().strip(),
            "demo_mode": self._demo_mode.isChecked(),
            "sync_enabled": self._sync_enabled.isChecked(),
            "sync_interval_minutes": self._sync_interval.value(),
            "export_dir": self._export_dir.text().strip(),
        })

        # Reset Graph client so it picks up new tenant/client
        from app.graph.client import reset_client
        reset_client()

        QMessageBox.information(self, "Saved", "Settings saved. Re-authenticate if you changed tenant/client IDs.")
        logger.info("Settings saved")

    def _test_connection(self):
        from app.graph.client import get_client, reset_client
        from app.ui.workers.sync_worker import AuthWorker

        # Save first
        self._save_config()
        reset_client()

        if self._demo_mode.isChecked():
            self._test_result.setPlainText("Demo mode is active — skipping real connection test.")
            return

        self._test_btn.setEnabled(False)
        self._test_result.setPlainText("Testing connection…")

        cfg = AppConfig()
        if cfg.auth_mode == "device_code":
            self._auth_worker = AuthWorker()

            def on_code(user_code, uri):
                from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QApplication
                dlg = QDialog(self)
                dlg.setWindowTitle("Authenticate with Microsoft")
                dlg.setMinimumWidth(420)
                dl = QVBoxLayout(dlg)
                dl.addWidget(QLabel("<b>Open the following URL in your browser and enter the code below:</b>"))
                url_lbl = QLabel(f'<a href="{uri}" style="color:#89dceb">{uri}</a>')
                url_lbl.setOpenExternalLinks(True)
                dl.addWidget(url_lbl)
                code_lbl = QLabel(f'<span style="font-size:28px;font-weight:bold;color:#cba6f7">{user_code}</span>')
                code_lbl.setAlignment(Qt.AlignCenter)
                dl.addWidget(code_lbl)
                dl.addWidget(QLabel("Waiting for sign-in… (this dialog will close automatically)"))
                close_btn = QPushButton("Cancel")
                close_btn.clicked.connect(dlg.reject)
                dl.addWidget(close_btn)
                dlg.show()
                self._auth_dialog = dlg

            def on_done(success, message):
                if hasattr(self, "_auth_dialog"):
                    self._auth_dialog.accept()
                if success:
                    client = get_client()
                    result = client.test_connection()
                    self._test_result.setPlainText(
                        f"✅ {result['details']}" if result["ok"] else f"❌ {result['details']}"
                    )
                else:
                    self._test_result.setPlainText(f"❌ Auth failed: {message}")
                self._test_btn.setEnabled(True)

            self._auth_worker.device_code_ready.connect(on_code)
            self._auth_worker.finished.connect(on_done)
            self._auth_worker.start()
        else:
            # App-only
            try:
                client = get_client()
                result = client.test_connection()
                self._test_result.setPlainText(
                    f"✅ {result['details']}" if result["ok"] else f"❌ {result['details']}"
                )
            except Exception as e:
                self._test_result.setPlainText(f"❌ Error: {e}")
            finally:
                self._test_btn.setEnabled(True)

    def _logout(self):
        reply = QMessageBox.question(
            self, "Logout", "Clear the MSAL token cache? You will need to re-authenticate.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            from app.graph.auth import get_auth
            get_auth().clear_cache()
            QMessageBox.information(self, "Logged Out", "Token cache cleared.")

    def _run_manual_sync(self):
        main_window = self.window()
        if hasattr(main_window, "run_sync"):
            main_window.run_sync()

    def _browse_cert(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Certificate File", "", "PEM/PFX Files (*.pem *.pfx *.p12)"
        )
        if path:
            self._cert_path.setText(path)

    def _browse_export(self):
        path = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if path:
            self._export_dir.setText(path)
