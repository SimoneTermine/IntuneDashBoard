"""
Main application window.
Sidebar navigation → StackedWidget pages.
Global search bar, sync status, status bar.
"""

import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFrame, QPushButton, QLabel, QStackedWidget,
    QLineEdit, QStatusBar, QSizePolicy, QScrollArea,
    QSplitter, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from app.ui.pages import (
    OverviewPage, DeviceExplorerPage, DeviceDetailPage,
    PolicyExplorerPage, ExplainabilityPage, AppOpsPage,
    GovernancePage, GroupUsagePage, SettingsPage,
)
from app.ui.widgets.sync_status_widget import SyncStatusWidget

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar button
# ─────────────────────────────────────────────────────────────────────────────
class SidebarButton(QPushButton):
    def __init__(self, icon: str, text: str, parent=None):
        super().__init__(f"  {icon}  {text}", parent)
        self.setObjectName("SidebarButton")
        self.setCheckable(True)
        self.setMinimumHeight(40)
        self.setCursor(Qt.PointingHandCursor)


class SidebarSectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(
            "color: #45475a; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1.5px; padding: 12px 16px 4px 16px;"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Intune Dashboard")
        self.setMinimumSize(1200, 720)
        self.resize(1440, 900)
        self._sync_worker = None
        self._setup_ui()
        self._setup_shortcuts()
        self._check_first_run()

        # Auto-refresh overview every 60 s
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start(60_000)

        # Start scheduler
        from app.config import AppConfig
        if AppConfig().sync_enabled and not AppConfig().demo_mode:
            try:
                from app.collector.sync_engine import start_scheduler
                start_scheduler(sync_callback=self._on_scheduled_sync_done)
            except Exception as e:
                logger.warning(f"Scheduler start failed: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 16, 8, 8)
        sidebar_layout.setSpacing(2)

        # Logo / app name
        logo = QLabel("🛡️  Intune Dashboard")
        logo.setStyleSheet("color: #cba6f7; font-size: 15px; font-weight: bold; padding: 8px 12px;")
        sidebar_layout.addWidget(logo)

        version_lbl = QLabel("v1.0.0  ·  read-only")
        version_lbl.setStyleSheet("color: #45475a; font-size: 10px; padding: 0 12px 8px 12px;")
        sidebar_layout.addWidget(version_lbl)

        # Navigation entries: (icon, label, page_index, section_header)
        nav_entries = [
            (None, "OVERVIEW", None, True),
            ("📊", "Overview", "overview", False),

            (None, "INVENTORY", None, True),
            ("🖥️", "Device Explorer", "devices", False),
            ("📋", "Device Detail", "device_detail", False),
            ("📑", "Policy Explorer", "policies", False),
            ("👥", "Group Usage", "group_usage", False),

            (None, "ANALYSIS", None, True),
            ("🔍", "Explain State", "explain", False),
            ("📦", "App Ops", "app_ops", False),

            (None, "GOVERNANCE", None, True),
            ("📈", "Drift & Snapshots", "governance", False),

            (None, "SETTINGS", None, True),
            ("⚙️", "Settings", "settings", False),
        ]

        self._nav_buttons: dict[str, SidebarButton] = {}
        self._page_keys: list[str] = []

        for entry in nav_entries:
            icon, label, page_key, is_section = entry
            if is_section:
                sidebar_layout.addWidget(SidebarSectionLabel(label))
            else:
                btn = SidebarButton(icon, label)
                btn.clicked.connect(lambda checked, k=page_key: self._navigate(k))
                self._nav_buttons[page_key] = btn
                self._page_keys.append(page_key)
                sidebar_layout.addWidget(btn)

        sidebar_layout.addStretch()

        # Sync status widget at bottom of sidebar
        self._sync_widget = SyncStatusWidget()
        self._sync_widget.sync_requested.connect(self.run_sync)
        sidebar_layout.addWidget(self._sync_widget)

        root_layout.addWidget(sidebar)

        # ── Content area ────────────────────────────────────────────────
        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Top toolbar (global search)
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet("QFrame#Toolbar { background: #181825; border-bottom: 1px solid #313244; }")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 0, 12, 0)

        self._global_search = QLineEdit()
        self._global_search.setPlaceholderText("🔍  Global search — devices, policies, apps…")
        self._global_search.setMaximumWidth(480)
        self._global_search.returnPressed.connect(self._global_search_action)

        search_btn = QPushButton("Search")
        search_btn.setMaximumWidth(70)
        search_btn.setStyleSheet("font-size: 12px;")
        search_btn.clicked.connect(self._global_search_action)

        demo_badge = QLabel()
        from app.config import AppConfig
        if AppConfig().demo_mode:
            demo_badge.setText("⚡ DEMO MODE")
            demo_badge.setStyleSheet(
                "background: #f9e2af; color: #1e1e2e; padding: 3px 8px; "
                "border-radius: 4px; font-weight: bold; font-size: 11px;"
            )

        toolbar_layout.addWidget(self._global_search)
        toolbar_layout.addWidget(search_btn)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(demo_badge)
        content_layout.addWidget(toolbar)

        # Stacked pages
        self._stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}

        # Instantiate all pages
        self._pages["overview"] = OverviewPage()
        self._pages["devices"] = DeviceExplorerPage()
        self._pages["device_detail"] = DeviceDetailPage()
        self._pages["policies"] = PolicyExplorerPage()
        self._pages["group_usage"] = GroupUsagePage()
        self._pages["explain"] = ExplainabilityPage()
        self._pages["app_ops"] = AppOpsPage()
        self._pages["governance"] = GovernancePage()
        self._pages["settings"] = SettingsPage()

        # Wire inter-page navigation
        self._pages["devices"].device_selected.connect(self._on_device_selected)

        for page in self._pages.values():
            self._stack.addWidget(page)

        content_layout.addWidget(self._stack)
        root_layout.addWidget(content_area)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

        # Navigate to overview by default
        self._navigate("overview")

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("F5"), self, self._refresh_current)

    # ─────────────────────────────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────────────────────────────
    def _navigate(self, page_key: str):
        if page_key not in self._pages:
            logger.warning(f"Unknown page: {page_key}")
            return

        # Update sidebar button states
        for k, btn in self._nav_buttons.items():
            btn.setChecked(k == page_key)

        page = self._pages[page_key]
        self._stack.setCurrentWidget(page)

        # Trigger page-specific refresh
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as e:
                logger.warning(f"Page refresh failed ({page_key}): {e}")

        self._status_bar.showMessage(f"Viewing: {page_key.replace('_', ' ').title()}")

    def navigate_to_explain(self, device_id: str):
        """Navigate to explainability page pre-loaded for a device."""
        self._navigate("explain")
        explain_page: ExplainabilityPage = self._pages["explain"]
        explain_page.load_device(device_id)

    def _on_device_selected(self, device_id: str):
        """User clicked a device in explorer → go to detail page."""
        self._navigate("device_detail")
        detail_page: DeviceDetailPage = self._pages["device_detail"]
        detail_page.load_device(device_id)

    # ─────────────────────────────────────────────────────────────────────
    # Global search
    # ─────────────────────────────────────────────────────────────────────
    def _focus_search(self):
        self._global_search.setFocus()
        self._global_search.selectAll()

    def _global_search_action(self):
        query = self._global_search.text().strip()
        if not query:
            return

        from app.analytics.queries import global_search
        results = global_search(query)

        devices = results.get("devices", [])
        controls = results.get("controls", [])
        apps = results.get("apps", [])

        if devices:
            # Navigate to device explorer and pre-filter
            explorer: DeviceExplorerPage = self._pages["devices"]
            explorer._table._search_box.setText(query)
            self._navigate("devices")
            self._status_bar.showMessage(
                f"Search '{query}': {len(devices)} devices, {len(controls)} policies, {len(apps)} apps"
            )
        elif controls:
            policy_page: PolicyExplorerPage = self._pages["policies"]
            policy_page._policy_table._search_box.setText(query)
            self._navigate("policies")
        else:
            self._status_bar.showMessage(f"No results for '{query}'")

    # ─────────────────────────────────────────────────────────────────────
    # Sync
    # ─────────────────────────────────────────────────────────────────────
    def run_sync(self):
        """Start a manual full sync in background."""
        if self._sync_worker and self._sync_worker.isRunning():
            QMessageBox.information(self, "Sync", "A sync is already running.")
            return

        from app.config import AppConfig
        cfg = AppConfig()

        if not cfg.demo_mode and (not cfg.tenant_id or not cfg.client_id):
            QMessageBox.warning(
                self, "Not Configured",
                "Please configure Tenant ID and Client ID in Settings before syncing.\n"
                "Or enable Demo Mode to explore the UI without credentials."
            )
            return

        from app.ui.workers.sync_worker import SyncWorker, AuthWorker

        # If using device code and not cached, authenticate first
        if not cfg.demo_mode and cfg.auth_mode == "device_code":
            from app.graph.auth import get_auth
            if not get_auth().has_cached_token():
                self._do_auth_then_sync()
                return

        self._start_sync_worker()

    def _do_auth_then_sync(self):
        """Authenticate via device code then start sync."""
        from app.ui.workers.sync_worker import AuthWorker
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton

        self._auth_dlg = None
        worker = AuthWorker()

        def on_code(user_code, uri):
            dlg = QDialog(self)
            dlg.setWindowTitle("Sign in to Microsoft")
            dlg.setMinimumWidth(440)
            dl = QVBoxLayout(dlg)
            dl.addWidget(QLabel("<b>Step 1:</b> Open this URL in your browser:"))
            url_lbl = QLabel(f'<a href="{uri}" style="color:#89dceb">{uri}</a>')
            url_lbl.setOpenExternalLinks(True)
            dl.addWidget(url_lbl)
            dl.addWidget(QLabel("<b>Step 2:</b> Enter this code:"))
            code_lbl = QLabel(f'<center><span style="font-size:32px;font-weight:bold;color:#cba6f7">{user_code}</span></center>')
            code_lbl.setTextFormat(Qt.RichText)
            dl.addWidget(code_lbl)
            dl.addWidget(QLabel("Waiting for sign-in…"))
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(dlg.reject)
            dl.addWidget(cancel_btn)
            self._auth_dlg = dlg
            dlg.show()

        def on_done(success, message):
            if self._auth_dlg:
                self._auth_dlg.accept()
            if success:
                self._start_sync_worker()
            else:
                QMessageBox.warning(self, "Auth Failed", message)

        worker.device_code_ready.connect(on_code)
        worker.finished.connect(on_done)
        self._auth_worker = worker
        worker.start()

    def _start_sync_worker(self):
        from app.ui.workers.sync_worker import SyncWorker
        self._sync_worker = SyncWorker()
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.start()
        self._sync_widget.set_syncing(True)
        self._status_bar.showMessage("Sync in progress…")

    def _on_sync_progress(self, stage, percent, message, is_error):
        self._sync_widget.update_progress(stage, percent, message, is_error)
        self._status_bar.showMessage(f"Sync: {message}")

    def _on_sync_finished(self, success, message):
        self._sync_widget.set_syncing(False)
        self._status_bar.showMessage(message)
        # Refresh the current page
        self._refresh_current()

    def _on_scheduled_sync_done(self):
        self._sync_widget.set_syncing(False)
        self._refresh_current()

    # ─────────────────────────────────────────────────────────────────────
    # Refresh
    # ─────────────────────────────────────────────────────────────────────
    def _refresh_current(self):
        current = self._stack.currentWidget()
        if hasattr(current, "refresh"):
            try:
                current.refresh()
            except Exception as e:
                logger.warning(f"Refresh failed: {e}")

    def _auto_refresh(self):
        """Silently refresh the overview KPIs."""
        try:
            self._pages["overview"].refresh()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────
    # First-run check
    # ─────────────────────────────────────────────────────────────────────
    def _check_first_run(self):
        from app.config import AppConfig
        from app.analytics.queries import get_overview_kpis
        cfg = AppConfig()

        kpis = get_overview_kpis()
        if kpis["total_devices"] == 0:
            if cfg.demo_mode:
                # Auto-load demo data
                QTimer.singleShot(500, self._load_demo)
            else:
                self._status_bar.showMessage(
                    "No data yet. Configure your tenant in Settings and click 'Sync Now'."
                )

    def _load_demo(self):
        from app.demo.demo_data import load_demo_data
        try:
            count = load_demo_data()
            self._status_bar.showMessage(f"Demo data loaded: {count} objects")
            self._pages["overview"].refresh()
        except Exception as e:
            logger.error(f"Demo data load failed: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # Close
    # ─────────────────────────────────────────────────────────────────────
    def closeEvent(self, event):
        from app.collector.sync_engine import stop_scheduler
        stop_scheduler()
        if self._sync_worker and self._sync_worker.isRunning():
            self._sync_worker.quit()
            self._sync_worker.wait(3000)
        event.accept()
