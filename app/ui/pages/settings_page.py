"""
Settings page — tenant/auth configuration, scheduler, storage, privacy.

Changes in v1.2.0:
  • Device code dialog: "Copy Code" button copies user_code to clipboard.
  • Sign-out button renamed to "Sign out / Clear Token Cache".
  • Admin consent section: "Open Admin Consent Page" button.
  • 403 / AdminConsentRequiredError surfaces a dedicated warning with the
    admin consent URL.
  • Cache type (DPAPI / plain) shown in Connection Test result.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QGroupBox, QCheckBox, QComboBox,
    QSpinBox, QScrollArea, QFrame, QDialog, QFileDialog,
    QMessageBox, QApplication,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.config import AppConfig, DEFAULT_SCOPES
from app.graph.auth import AuthError, AdminConsentRequiredError

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auth_worker = None
        self._auth_dialog = None
        self._setup_ui()
        self._load_config()

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        title = QLabel("⚙️  Settings")
        title.setFont(QFont("", 16, QFont.Bold))
        main_layout.addWidget(title)

        from PySide6.QtWidgets import QTabWidget
        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # ── Tenant / Auth tab ─────────────────────────────────────────────
        auth_widget = QWidget()
        auth_layout = QVBoxLayout(auth_widget)
        auth_layout.setContentsMargins(8, 8, 8, 8)
        auth_layout.setSpacing(12)

        tenant_group = QGroupBox("Tenant / App Registration")
        tgl = QVBoxLayout(tenant_group)

        # Tenant ID (masked)
        tid_row = QHBoxLayout()
        tid_row.addWidget(QLabel("Tenant ID:"))
        self._tenant_id = QLineEdit()
        self._tenant_id.setEchoMode(QLineEdit.Password)
        self._tenant_id.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        reveal_tid = QPushButton("👁")
        reveal_tid.setMaximumWidth(32)
        reveal_tid.setCheckable(True)
        reveal_tid.toggled.connect(
            lambda checked: self._tenant_id.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        tid_row.addWidget(self._tenant_id)
        tid_row.addWidget(reveal_tid)
        tgl.addLayout(tid_row)

        # Client ID (masked)
        cid_row = QHBoxLayout()
        cid_row.addWidget(QLabel("Client (App) ID:"))
        self._client_id = QLineEdit()
        self._client_id.setEchoMode(QLineEdit.Password)
        self._client_id.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        reveal_cid = QPushButton("👁")
        reveal_cid.setMaximumWidth(32)
        reveal_cid.setCheckable(True)
        reveal_cid.toggled.connect(
            lambda checked: self._client_id.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        cid_row.addWidget(self._client_id)
        cid_row.addWidget(reveal_cid)
        tgl.addLayout(cid_row)

        auth_layout.addWidget(tenant_group)

        # Auth mode
        mode_group = QGroupBox("Authentication Mode")
        mgl = QVBoxLayout(mode_group)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Auth Mode:"))
        self._auth_mode = QComboBox()
        self._auth_mode.addItems(["device_code", "app_only"])
        self._auth_mode.currentTextChanged.connect(self._on_auth_mode_changed)
        mode_row.addWidget(self._auth_mode)
        mode_row.addStretch()
        mgl.addLayout(mode_row)
        auth_layout.addWidget(mode_group)

        # Certificate (app-only)
        self._cert_group = QGroupBox("App-Only Certificate")
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

        # Demo mode
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

        # ── Connection Test ────────────────────────────────────────────────
        conn_group = QGroupBox("Connection Test")
        cgl = QVBoxLayout(conn_group)

        test_row = QHBoxLayout()
        self._test_btn = QPushButton("🔗  Test Graph Connection")
        self._test_btn.clicked.connect(self._test_connection)

        self._logout_btn = QPushButton("🚪  Sign out / Clear Token Cache")
        self._logout_btn.setObjectName("DangerButton")
        self._logout_btn.clicked.connect(self._logout)

        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._logout_btn)
        test_row.addStretch()
        cgl.addLayout(test_row)

        # Admin consent row
        consent_row = QHBoxLayout()
        self._consent_btn = QPushButton("🔑  Open Admin Consent Page")
        self._consent_btn.setToolTip(
            "Open the Azure AD admin consent page in your browser.\n"
            "A Global Administrator must grant consent for all required permissions."
        )
        self._consent_btn.clicked.connect(self._open_admin_consent)
        consent_row.addWidget(self._consent_btn)

        consent_info = QLabel(
            "Required if you see 403 / AADSTS65001 errors. "
            "A tenant admin must visit this URL and click 'Accept'."
        )
        consent_info.setWordWrap(True)
        consent_info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        consent_row.addWidget(consent_info, 1)
        cgl.addLayout(consent_row)

        self._test_result = QTextEdit()
        self._test_result.setReadOnly(True)
        self._test_result.setMaximumHeight(120)
        self._test_result.setPlaceholderText("Test result appears here…")
        cgl.addWidget(self._test_result)
        auth_layout.addWidget(conn_group)

        # Device code how-it-works
        dcode_group = QGroupBox("Device Code Flow — How It Works")
        dcode_gl = QVBoxLayout(dcode_group)
        instructions = QLabel(
            "1. Click 'Test Graph Connection' or 'Sync Now'.\n"
            "2. A dialog appears with a URL and a sign-in code.\n"
            "3. Use the 'Copy Code' button or select it manually.\n"
            "4. Open the URL in any browser, enter the code, sign in.\n"
            "5. The dialog closes automatically once authentication completes.\n\n"
            "The token is cached locally and refreshed automatically.\n"
            "If new permissions are added, the cache is cleared and you are\n"
            "prompted to re-authenticate with the updated permission set."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #a6adc8; font-size: 12px;")
        dcode_gl.addWidget(instructions)
        auth_layout.addWidget(dcode_group)

        auth_layout.addStretch()
        tabs.addTab(auth_widget, "Tenant / Auth")

        # ── Scheduler tab ─────────────────────────────────────────────────
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

        # ── Storage tab ───────────────────────────────────────────────────
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

        # ── Privacy tab ───────────────────────────────────────────────────
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
            "<li>Device metadata, policy info, and app data are cached in a local "
            "SQLite database.</li>"
            "<li>The authentication token cache is stored at "
            "<code>%APPDATA%\\IntuneDashboard\\msal_cache.bin</code> and is "
            "<b>encrypted via Windows DPAPI</b> when msal-extensions is installed "
            "(binding it to your Windows user account).</li>"
            "<li>Token contents are never written to log files.</li>"
            "<li>Use minimum required Graph API permissions (read-only where possible).</li>"
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

    def _on_auth_mode_changed(self, mode: str):
        self._cert_group.setVisible(mode == "app_only")

    # ─────────────────────────────────────────────────────────────────────────
    # Config load / save
    # ─────────────────────────────────────────────────────────────────────────

    def _load_config(self):
        cfg = AppConfig()
        self._tenant_id.setText(cfg.tenant_id or "")
        self._client_id.setText(cfg.client_id or "")
        mode = cfg.auth_mode or "device_code"
        idx = self._auth_mode.findText(mode)
        if idx >= 0:
            self._auth_mode.setCurrentIndex(idx)
        self._cert_thumbprint.setText(cfg.get("cert_thumbprint", "") or "")
        self._cert_path.setText(cfg.get("cert_path", "") or "")
        self._sync_enabled.setChecked(cfg.sync_enabled)
        self._sync_interval.setValue(cfg.sync_interval_minutes or 60)
        self._db_path.setText(cfg.db_path or "")
        self._export_dir.setText(cfg.export_dir or "")
        self._demo_mode.setChecked(cfg.demo_mode)
        self._on_auth_mode_changed(mode)

    def _save_config(self):
        cfg = AppConfig()
        cfg.set("tenant_id", self._tenant_id.text().strip())
        cfg.set("client_id", self._client_id.text().strip())
        cfg.set("auth_mode", self._auth_mode.currentText())
        cfg.set("cert_thumbprint", self._cert_thumbprint.text().strip())
        cfg.set("cert_path", self._cert_path.text().strip())
        cfg.set("sync_enabled", self._sync_enabled.isChecked())
        cfg.set("sync_interval_minutes", self._sync_interval.value())
        cfg.set("export_dir", self._export_dir.text().strip())
        cfg.set("demo_mode", self._demo_mode.isChecked())
        cfg.save()
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

        # Always clear the token cache so the device code dialog is shown.
        # "Test Graph Connection" is an explicit re-authentication action.
        from app.graph import auth as _auth_mod
        _auth_mod.get_auth().clear_cache()
        _auth_mod._auth_instance = None   # force singleton re-init

        cfg = AppConfig()
        self._test_btn.setEnabled(False)
        self._test_result.setPlainText("Waiting for sign-in…")

        if cfg.auth_mode == "device_code":
            self._auth_worker = AuthWorker()

            def on_code(user_code: str, uri: str):
                """Show device code dialog — called from background thread via signal."""
                dlg = QDialog(self)
                dlg.setWindowTitle("Sign in to Microsoft")
                dlg.setMinimumWidth(480)
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

                # ── Copy-to-clipboard button ──────────────────────────────
                copy_row = QHBoxLayout()
                copy_btn = QPushButton("📋  Copy Code")
                copy_btn.setMinimumHeight(32)
                copy_btn.setToolTip("Copy the sign-in code to the clipboard")

                def _copy_code():
                    QApplication.clipboard().setText(user_code)
                    copy_btn.setText("✅  Copied!")
                    copy_btn.setEnabled(False)

                copy_btn.clicked.connect(_copy_code)
                copy_row.addStretch()
                copy_row.addWidget(copy_btn)
                copy_row.addStretch()
                dl.addLayout(copy_row)
                # ─────────────────────────────────────────────────────────

                waiting = QLabel(
                    "Waiting for sign-in… "
                    "This dialog closes automatically once authentication completes."
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
                        from app.graph.auth import get_auth
                        cache_type = get_auth().cache_type()
                        client = get_client()
                        result = client.test_connection()
                        status_icon = "✅" if result["ok"] else "❌"
                        self._test_result.setPlainText(
                            f"{status_icon} {result['details']}\n"
                            f"Token cache: {cache_type}"
                        )
                    except AdminConsentRequiredError as e:
                        self._test_result.setPlainText(
                            f"❌ Admin consent required.\n{e}\n\n"
                            "Use the 'Open Admin Consent Page' button below."
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
    # Sign out / Clear Token Cache
    # ─────────────────────────────────────────────────────────────────────────

    def _logout(self):
        reply = QMessageBox.question(
            self,
            "Sign out / Clear Token Cache",
            "You will be signed out and the local token cache will be removed.\n\n"
            "The next sync will require signing in again via device code.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            from app.graph.auth import get_auth
            from app.graph import auth as _auth_mod
            from app.graph.client import reset_client

            get_auth().sign_out()
            _auth_mod._auth_instance = None   # force singleton re-init on next use
            reset_client()

            QMessageBox.information(
                self,
                "Signed out",
                "You have been signed out.\n"
                "Token cache removed.\n\n"
                "The next sync will prompt for a new sign-in.",
            )
            self._test_result.setPlainText("Signed out — token cache cleared.")
        except Exception as e:
            QMessageBox.warning(self, "Sign-out Error", f"Failed to sign out:\n{e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Admin consent
    # ─────────────────────────────────────────────────────────────────────────

    def _open_admin_consent(self):
        from app.graph.auth import open_admin_consent_page, admin_consent_url

        cfg = AppConfig()
        if not cfg.client_id:
            QMessageBox.warning(
                self,
                "Client ID Missing",
                "Please enter your Client (App) ID in the settings above and save "
                "before opening the admin consent page.",
            )
            return

        url = admin_consent_url(cfg.client_id, cfg.tenant_id or "common")
        open_admin_consent_page(cfg.client_id, cfg.tenant_id or "common")
        QMessageBox.information(
            self,
            "Admin Consent Page Opened",
            f"The admin consent page has been opened in your browser.\n\n"
            f"URL:\n{url}\n\n"
            "A Global Administrator must sign in and click 'Accept' to grant "
            "consent for all required permissions.\n\n"
            "After consent is granted, click 'Test Graph Connection' or run a sync.",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Other actions
    # ─────────────────────────────────────────────────────────────────────────

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