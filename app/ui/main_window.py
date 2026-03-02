"""
Main application window.
Sidebar navigation → StackedWidget pages.
Global search bar, sync status, status bar.
app/ui/main_window.py  —  v1.2.1 (Remediations removed)
"""

import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QFrame, QPushButton, QLabel, QStackedWidget,
    QLineEdit, QStatusBar, QSizePolicy, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from app.ui.pages import (
    OverviewPage, DeviceExplorerPage, DeviceDetailPage,
    PolicyExplorerPage, ExplainabilityPage, AppOpsPage,
    GovernancePage, GroupUsagePage,
    SettingsPage, GraphQueryPage,
)
from app.ui.widgets.sync_status_widget import SyncStatusWidget
from app.version import APP_NAME, __version__

logger = logging.getLogger(__name__)


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


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setMinimumSize(1200, 720)
        self.resize(1440, 900)
        self._sync_worker = None
        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet(
            "QFrame#Sidebar { background: #181825; border-right: 1px solid #313244; }"
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        logo = QLabel(f"  \U0001f6e1\ufe0f  {APP_NAME}")
        logo.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: #cba6f7; "
            "padding: 18px 16px 14px 16px; border-bottom: 1px solid #313244;"
        )
        sidebar_layout.addWidget(logo)

        nav_entries = [
            (None, "OVERVIEW",   None,             True),
            ("📊", "Overview",   "overview",       False),
            (None, "INVENTORY",  None,             True),
            ("🖥️", "Device Explorer",  "devices",       False),
            ("📋", "Device Detail",    "device_detail", False),
            ("📑", "Policy Explorer",  "policies",      False),
            ("👥", "Group Usage",      "group_usage",   False),
            (None, "ANALYSIS",   None,             True),
            ("🔍", "Explain State",    "explain",       False),
            ("📦", "App Ops",          "app_ops",       False),
            ("🧪", "Graph Query Lab",  "graph_query",   False),
            (None, "GOVERNANCE", None,             True),
            ("📈", "Drift & Snapshots", "governance",   False),
            (None, "SETTINGS",   None,             True),
            ("⚙️", "Settings",   "settings",       False),
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

        self._sync_widget = SyncStatusWidget()
        self._sync_widget.sync_requested.connect(self.run_sync)
        sidebar_layout.addWidget(self._sync_widget)

        root_layout.addWidget(sidebar)

        # ── Content area ──────────────────────────────────────────────────
        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet(
            "QFrame#Toolbar { background: #181825; border-bottom: 1px solid #313244; }"
        )
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
            demo_badge.setText("  🎭 DEMO MODE  ")
            demo_badge.setStyleSheet(
                "background: #f38ba8; color: #1e1e2e; font-weight: bold; "
                "border-radius: 4px; padding: 2px 8px; font-size: 11px;"
            )

        toolbar_layout.addWidget(self._global_search)
        toolbar_layout.addWidget(search_btn)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(demo_badge)

        content_layout.addWidget(toolbar)

        self._stack = QStackedWidget()
        content_layout.addWidget(self._stack)

        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet("color: #a6adc8; font-size: 11px;")
        self.setStatusBar(self._status_bar)

        root_layout.addWidget(content_area)

        # ── Pages ─────────────────────────────────────────────────────────
        self._pages: dict[str, QWidget] = {
            "overview":      OverviewPage(),
            "devices":       DeviceExplorerPage(),
            "device_detail": DeviceDetailPage(),
            "policies":      PolicyExplorerPage(),
            "group_usage":   GroupUsagePage(),
            "explain":       ExplainabilityPage(),
            "app_ops":       AppOpsPage(),
            "graph_query":   GraphQueryPage(),
            "governance":    GovernancePage(),
            "settings":      SettingsPage(),
        }

        for page in self._pages.values():
            self._stack.addWidget(page)

        if hasattr(self._pages["devices"], "device_selected"):
            self._pages["devices"].device_selected.connect(self._on_device_selected)

        self._navigate("overview")

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._focus_search)
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_current)

    def _navigate(self, page_key: str):
        if page_key not in self._pages:
            logger.warning(f"Unknown page: {page_key}")
            return
        for k, btn in self._nav_buttons.items():
            btn.setChecked(k == page_key)
        page = self._pages[page_key]
        self._stack.setCurrentWidget(page)
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception as e:
                logger.warning(f"Page refresh failed ({page_key}): {e}")
        self._status_bar.showMessage(f"Viewing: {page_key.replace('_', ' ').title()}")

    def navigate_to_explain(self, device_id: str):
        self._navigate("explain")
        self._pages["explain"].load_device(device_id)

    def _on_device_selected(self, device_id: str):
        self._navigate("device_detail")
        self._pages["device_detail"].load_device(device_id)

    def _focus_search(self):
        self._global_search.setFocus()
        self._global_search.selectAll()

    def _global_search_action(self):
        query = self._global_search.text().strip()
        if not query:
            return
        self._navigate("devices")
        if hasattr(self._pages["devices"], "set_search"):
            self._pages["devices"].set_search(query)

    def _refresh_current(self):
        current = self._stack.currentWidget()
        if current and hasattr(current, "refresh"):
            try:
                current.refresh()
            except Exception as e:
                logger.warning(f"Manual refresh failed: {e}")

    def run_sync(self):
        from app.ui.workers.sync_worker import SyncWorker
        if self._sync_worker and self._sync_worker.isRunning():
            QMessageBox.information(self, "Sync", "A sync is already in progress.")
            return
        self._sync_widget.set_syncing(True)
        self._status_bar.showMessage("Syncing…")
        self._sync_worker = SyncWorker()
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.start()

    def _on_sync_progress(self, msg: str):
        self._status_bar.showMessage(f"Sync: {msg}")

    def _on_sync_finished(self, success: bool, message: str):
        self._sync_widget.set_syncing(False)
        if success:
            self._status_bar.showMessage(f"Sync complete — {message}")
            current = self._stack.currentWidget()
            if current and hasattr(current, "refresh"):
                try:
                    current.refresh()
                except Exception:
                    pass
        else:
            self._status_bar.showMessage(f"Sync failed: {message}")
            QMessageBox.warning(self, "Sync Failed", message)
