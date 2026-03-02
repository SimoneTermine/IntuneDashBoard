"""
Settings page — tenant/auth config, scheduler, storage, privacy.
Credentials fields (Tenant ID, Client ID) are masked by default with a show/hide toggle.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QCheckBox, QGroupBox,
    QTextEdit, QFileDialog, QMessageBox, QTabWidget, QScrollArea,
    QFrame, QDialog,
)
from PySide6.QtCore import Qt

from app.config import AppConfig

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth_worker = None
        self._auth_dialog = None
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

        # ── Auth tab ────────────────────────────────────────────────────────
        auth_widget = QWidget()
        auth_layout = QVBoxLayout(auth_widget)
        auth_layout.setContentsMargins(8, 8, 8, 8)
        auth_layout.setSpacing(12)

        tenant_group = QGroupBox("Tenant & App Registration")
        tgl = QVBoxLayout(tenant_group)
        self._tenant_id, _ = self._labeled_input_masked("Tenant ID (Directory ID):", tgl)
        self._client_id, _ = self._labeled_input_masked("Client ID (Application ID):", tgl)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Auth Mode:"))
        self._auth_mode = QComboBox()
        self._auth_mode.addItems(["device_code", "app_only"])
        self._auth_mode.currentTextChanged.connect(self._on_auth_mode_changed)
        mode_row.addWidget(self._auth_mode)
        mode_row.addStretch()
        tgl.addLayout(mode_row)
        auth_layout.addWidget(tenant_group)

        self._cert_group = QGroupBox("Certificate (App-Only Mode)")
        certgl = QVBoxLayout(self._cert_group)
        self._cert_thumbprint = self._labeled_input("Certificate Thumbprint:", certgl)
        cert_path_row = QHBoxLayout()
        cert_path_row.addWidget(QLabel("Certificate File (.pem/.pfx):"))
        self._cert_path = QLineEdit()
        self._cert_path.setPlaceholderText("/path/to/cert.pem")
        browse_cert_btn = QPushButton("Browse...")
        browse_cert_btn.setMaximumWidth(80)
        browse_cert_btn.clicked.connect(self._browse_cert)
        cert_path_row.addWidget(self._cert_path)
        cert_path_row.addWidget(browse_cert_btn)
        certgl.addLayout(cert_path_row)
        self._cert_group.hide()
        auth_layout.addWidget(self._cert_group)

        demo_group = QGroupBox("Demo Mode")
        dgl = QVBoxLayout(demo_group)
        self._demo_mode = QCheckBox(
            "Enable Demo Mode (uses synthetic data, no Graph connection needed)"
        )
        dgl.addWidget(self._demo_mode)
        demo_info = QLabel(
            "When enabled, the app loads a sample dataset so you can explore the UI "
            "without real credentials. Disable before connecting to a real tenant."
        )
        demo_info.setWordWrap(True)
        demo_info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        dgl.addWidget(demo_info)
        auth_layout.addWidget(demo_group)

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
        self._test_result.setPlaceholderText("Test result appears here...")
        cgl.addWidget(self._test_result)
        auth_layout.addWidget(conn_group)

        dcode_group = QGroupBox("Device Code Flow — How It Works")
        dcode_gl = QVBoxLayout(dcode_group)
        instructions = QLabel(
            "1. Click 'Test Graph Connection' or 'Sync Now'.\n"
            "2. A dialog will appear with a URL and a code.\n"
            "3. Open the URL in any browser (same or different device).\n"
            "4. Enter the code and sign in with your admin account.\n"
            "5. The app receives the token automatically — the dialog closes.\n\n"
            "The token is cached locally and refreshed automatically.\n"
            "If new permissions are added, the cache is cleared and you will be\n"
            "prompted to re-authenticate with the updated permission set."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #a6adc8; font-size: 12px;")
        dcode_gl.addWidget(instructions)
        auth_layout.addWidget(dcode_group)

        auth_layout.addStretch()
        tabs.addTab(auth_widget, "Tenant / Auth")

        # ── Scheduler tab ───────────────────────────────────────────────────
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

        # ── Storage tab ─────────────────────────────────────────────────────
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
        browse_export_btn = QPushButton("Browse...")
        browse_export_btn.setMaximumWidth(80)
        browse_export_btn.clicked.connect(self._browse_export)
        export_row.addWidget(self._export_dir)
        export_row.addWidget(browse_export_btn)
        stgl.addLayout(export_row)
        storage_layout.addWidget(storage_group)
        storage_layout.addStretch()
        tabs.addTab(storage_widget, "Storage")

        # ── Privacy tab ──────────────────────────────────────────────────────
        privacy_widget = QWidget()
        priv_layout = QVBoxLayout(privacy_widget)
        priv_layout.setContentsMargins(8, 8, 8, 8)
        privacy_text = QTextEdit()
        privacy_text.setReadOnly(True)
        privacy_text.setHtml(
            "<h3 style='color:#cba6f7'>Data Storage &amp; Privacy</h3>"
            "<p>All data is stored locally on your machine. No data is sent to any "
            "third-party service other than Microsoft Graph API.</p>"
            "<ul>"
            "<li>Device metadata, policy info, and app data are cached in a local SQLite DB.</li>"
            "<li>Authentication tokens are stored using MSAL encrypted token cache.</li>"
            "<li>Use the minimum required Graph API permissions (read-only where possible).</li>"
            "<li>Regularly rotate app credentials in Entra ID.</li>"
            "</ul>"
            "<p style='color:#6c7086;font-size:11px'>"
            "Data location: %APPDATA%\\IntuneDashboard\\<br>"
            "Logs: %APPDATA%\\IntuneDashboard\\logs\\"
            "</p>"
        )
        priv_layout.addWidget(privacy_text)
        tabs.addTab(privacy_widget, "Privacy")

        save_btn = QPushButton("💾  Save Settings")
        save_btn.setMinimumHeight(40)
        save_btn.clicked.connect(self._save_config)
        main_layout.addWidget(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _labeled_input(self, label: str, parent_layout) -> QLineEdit:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(200)
        inp = QLineEdit()
        row.addWidget(lbl)
        row.addWidget(inp)
        parent_layout.addLayout(row)
        return inp

    def _labeled_input_masked(self, label: str, parent_layout) -> tuple:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(200)
        inp = QLineEdit()
        inp.setEchoMode(QLineEdit.Password)
        toggle_btn = QPushButton("👁")
        toggle_btn.setMaximumWidth(36)
        toggle_btn.setCheckable(True)
        toggle_btn.setToolTip("Show / hide")
        toggle_btn.setStyleSheet(
            "QPushButton { border: 1px solid #45475a; border-radius: 4px; padding: 2px 4px; }"
            "QPushButton:checked { background: #313244; }"
        )
        toggle_btn.toggled.connect(
            lambda checked: inp.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        row.addWidget(lbl)
        row.addWidget(inp)
        row.addWidget(toggle_btn)
        parent_layout.addLayout(row)
        return inp, toggle_btn

    def _on_auth_mode_changed(self, mode: str):
        self._cert_group.setVisible(mode == "app_only")

    # ─────────────────────────────────────────────────────────────────────────
    # Load / Save
    # ─────────────────────────────────────────────────────────────────────────

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
        from app.graph.client import reset_client
        from app.graph.auth import _auth_instance
        import app.graph.auth as _auth_mod
        _auth_mod._auth_instance = None  # force re-init with new tenant/client
        reset_client()
        QMessageBox.information(
            self, "Saved",
            "Settings saved.\n"
            "Re-authenticate if you changed Tenant ID or Client ID."
        )
        logger.info("Settings saved")

    # ─────────────────────────────────────────────────────────────────────────
    # Test Connection — shows device code dialog when needed
    # ─────────────────────────────────────────────────────────────────────────

    def _test_connection(self):
        from app.graph.client import get_client, reset_client
        from app.ui.workers.sync_worker import AuthWorker

        self._save_config()
        reset_client()

        if self._demo_mode.isChecked():
            self._test_result.setPlainText(
                "Demo mode is active — skipping real connection test."
            )
            return

        # Always clear the token cache so the device code dialog is shown every time.
        # "Test Graph Connection" is an explicit re-authentication, not a silent check.
        from app.graph.auth import get_auth
        from app.graph import auth as _auth_mod
        get_auth().clear_cache()
        _auth_mod._auth_instance = None   # reset singleton so next get_auth() re-inits

        cfg = AppConfig()
        self._test_btn.setEnabled(False)
        self._test_result.setPlainText("Waiting for sign-in…")

        if cfg.auth_mode == "device_code":
            self._auth_worker = AuthWorker()

            def on_code(user_code: str, uri: str):
                """Called from background thread — build dialog on main thread."""
                dlg = QDialog(self)
                dlg.setWindowTitle("Sign in to Microsoft")
                dlg.setMinimumWidth(460)
                dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
                dl = QVBoxLayout(dlg)
                dl.setSpacing(12)
                dl.setContentsMargins(20, 20, 20, 20)

                header = QLabel(
                    "<b>Open the following URL in your browser and enter the code below:</b>"
                )
                header.setWordWrap(True)
                dl.addWidget(header)

                url_lbl = QLabel(
                    f'<a href="{uri}" style="color:#89dceb">{uri}</a>'
                )
                url_lbl.setOpenExternalLinks(True)
                url_lbl.setTextInteractionFlags(
                    Qt.TextBrowserInteraction | Qt.TextSelectableByMouse
                )
                dl.addWidget(url_lbl)

                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setStyleSheet("color: #45475a;")
                dl.addWidget(separator)

                code_label = QLabel("Your sign-in code:")
                dl.addWidget(code_label)

                code_lbl = QLabel(
                    f'<span style="font-size:32px;font-weight:bold;'
                    f'letter-spacing:6px;color:#cba6f7">{user_code}</span>'
                )
                code_lbl.setAlignment(Qt.AlignCenter)
                code_lbl.setTextFormat(Qt.RichText)
                dl.addWidget(code_lbl)

                waiting = QLabel(
                    "Waiting for sign-in... "
                    "This dialog will close automatically once authentication completes."
                )
                waiting.setWordWrap(True)
                waiting.setStyleSheet("color: #a6adc8; font-size: 11px;")
                dl.addWidget(waiting)

                cancel_btn = QPushButton("Cancel")
                cancel_btn.clicked.connect(dlg.reject)
                dl.addWidget(cancel_btn)

                dlg.show()
                self._auth_dialog = dlg

            def on_done(success: bool, message: str):
                if self._auth_dialog:
                    self._auth_dialog.accept()
                    self._auth_dialog = None

                if success:
                    try:
                        client = get_client()
                        result = client.test_connection()
                        self._test_result.setPlainText(
                            f"✅ {result['details']}"
                            if result["ok"]
                            else f"❌ {result['details']}"
                        )
                    except Exception as e:
                        self._test_result.setPlainText(f"❌ Error: {e}")
                else:
                    self._test_result.setPlainText(f"❌ Auth failed: {message}")

                self._test_btn.setEnabled(True)

            self._auth_worker.device_code_ready.connect(on_code)
            self._auth_worker.finished.connect(on_done)
            self._auth_worker.start()

        else:
            # App-only: no interactive prompt needed
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

    # ─────────────────────────────────────────────────────────────────────────
    # Other actions
    # ─────────────────────────────────────────────────────────────────────────

    def _logout(self):
        reply = QMessageBox.question(
            self, "Clear Token Cache",
            "This will delete the cached authentication token.\n"
            "You will need to sign in again on the next sync.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                from app.graph.auth import get_auth
                get_auth().clear_cache()
                from app.graph.client import reset_client
                reset_client()
                QMessageBox.information(self, "Logged Out", "Token cache cleared.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to clear cache: {e}")

    def _browse_cert(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Certificate File", "",
            "Certificate Files (*.pem *.pfx *.p12 *.crt)"
        )
        if path:
            self._cert_path.setText(path)

    def _browse_export(self):
        path = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if path:
            self._export_dir.setText(path)

    def _run_manual_sync(self):
        main_win = self.window()
        if hasattr(main_win, "run_sync"):
            main_win.run_sync()
        else:
            QMessageBox.information(self, "Sync", "Use the Sync button in the sidebar.")

    def refresh(self):
        self._load_config()
