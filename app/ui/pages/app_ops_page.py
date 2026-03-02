"""
app/ui/pages/app_ops_page.py

App Monitoring — full rewrite v1.2.2.

5 tab layout:
  1. Overview      — KPI cards + state distribution bar
  2. App Catalog   — per-app aggregated stats, click to drill-down
  3. Install Log   — flat device×app×state table, filterable by state
  4. Error Analysis — error codes ranked by impact, descriptions, affected apps
  5. Device Drill  — per-device status for a selected app (populated from Catalog tab)

Right-click context menu on every table:
  - Copy row data (name, ID, state, error code...)
  - Export visible rows → CSV
  - Export full row → JSON
  - Open app in Intune Portal (where applicable)
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QTabWidget, QFrame,
    QAbstractItemView, QSizePolicy, QMessageBox,
    QFileDialog, QComboBox, QApplication, QMenu,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QTextEdit,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QAction, QPainter, QBrush, QPen

from app.ui.widgets.filterable_table import FilterableTable

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Colour constants  (Catppuccin Mocha)
# ─────────────────────────────────────────────────────────────────────────────
STATE_COLORS = {
    "installed":     "#a6e3a1",   # green
    "failed":        "#f38ba8",   # red
    "pendinginstall":"#f9e2af",   # yellow
    "pending":       "#f9e2af",
    "notinstalled":  "#cba6f7",   # mauve
    "not installed": "#cba6f7",
    "unknown":       "#a6adc8",   # subtext
    "excluded":      "#6c7086",
}

SEVERITY_COLORS = {
    "high":    "#f38ba8",
    "medium":  "#f9e2af",
    "ok":      "#a6e3a1",
    "unknown": "#a6adc8",
}

_CARD_STYLE = """
    QFrame {{
        background: {bg};
        border-radius: 10px;
        border: 1px solid {border};
    }}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Column definitions
# ─────────────────────────────────────────────────────────────────────────────

CATALOG_COLS = [
    ("display_name",   "App Name",       260),
    ("app_type",       "Type",           130),
    ("publisher",      "Publisher",      160),
    ("installed",      "✓ Installed",     90),
    ("failed",         "✗ Failed",        80),
    ("pending",        "⏳ Pending",       80),
    ("not_installed",  "○ Not Installed",  110),
    ("success_rate",   "Success %",        90),
    ("total_devices",  "Total Devices",    100),
    ("is_assigned",    "Assigned",         75),
    ("last_modified",  "Last Modified",   130),
]

INSTALL_LOG_COLS = [
    ("app_name",      "App",            230),
    ("app_type",      "Type",           110),
    ("device_name",   "Device",         170),
    ("user",          "User",           160),
    ("os",            "OS",              80),
    ("install_state", "State",          120),
    ("error_code",    "Error Code",     100),
    ("error_desc",    "Description",    240),
    ("last_sync",     "Last Sync",      130),
]

ERROR_COLS = [
    ("error_code",    "Error Code",     110),
    ("description",   "Description",   300),
    ("device_count",  "Devices",         80),
    ("app_count",     "Apps",            70),
    ("severity",      "Severity",        90),
    ("affected_apps", "Top Affected Apps", 320),
]

DRILL_COLS = [
    ("device_name",   "Device",         180),
    ("user",          "User",           160),
    ("os",            "OS",              90),
    ("os_version",    "OS Version",     120),
    ("install_state", "State",          120),
    ("error_code",    "Error Code",     100),
    ("error_desc",    "Description",    240),
    ("compliance",    "Compliance",      100),
    ("last_sync",     "Last Sync",      130),
]


# ─────────────────────────────────────────────────────────────────────────────
# KPI Card widget
# ─────────────────────────────────────────────────────────────────────────────

class KpiCard(QFrame):
    def __init__(self, title: str, value: str, subtitle: str = "",
                 color: str = "#cba6f7", parent=None):
        super().__init__(parent)
        self.setFixedHeight(100)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "QFrame { background: #1e1e2e; border-radius: 10px; "
            "border: 1px solid #313244; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold; "
                                "letter-spacing: 1px; background: transparent; border: none;")
        lay.addWidget(lbl_title)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(
            f"color: {color}; font-size: 26px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        lbl_val.setObjectName("kpi_value")
        lay.addWidget(lbl_val)

        if subtitle:
            lbl_sub = QLabel(subtitle)
            lbl_sub.setStyleSheet("color: #6c7086; font-size: 10px; "
                                  "background: transparent; border: none;")
            lay.addWidget(lbl_sub)

    def update_value(self, value: str, color: str | None = None):
        lbl = self.findChild(QLabel, "kpi_value")
        if lbl:
            lbl.setText(value)
            if color:
                lbl.setStyleSheet(
                    f"color: {color}; font-size: 26px; font-weight: bold; "
                    "background: transparent; border: none;"
                )


# ─────────────────────────────────────────────────────────────────────────────
# State Distribution Bar
# ─────────────────────────────────────────────────────────────────────────────

class StateBar(QWidget):
    """Horizontal proportional bar showing install state distribution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._segments: list[tuple[str, int, str]] = []  # (state, count, colour)

    def set_data(self, distribution: list[dict]):
        total = sum(d["count"] for d in distribution)
        if total == 0:
            self._segments = []
            self.update()
            return
        self._segments = []
        for d in distribution:
            state = (d["state"] or "unknown").lower()
            color = STATE_COLORS.get(state, "#45475a")
            self._segments.append((state, d["count"], color))
        self._total = total
        self.update()

    def paintEvent(self, event):
        if not self._segments:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(s[1] for s in self._segments)
        if total == 0:
            return
        x = 0
        w = self.width()
        h = self.height()
        for i, (state, count, color) in enumerate(self._segments):
            seg_w = int(count / total * w)
            if i == len(self._segments) - 1:
                seg_w = w - x
            p.fillRect(x, 0, seg_w, h, QColor(color))
            x += seg_w
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Context menu builder
# ─────────────────────────────────────────────────────────────────────────────

_MENU_STYLE = """
QMenu {
    background: #1e1e2e; color: #cdd6f4;
    border: 1px solid #45475a; border-radius: 6px; padding: 4px 2px;
}
QMenu::item { padding: 6px 22px 6px 14px; border-radius: 4px; margin: 1px 4px; }
QMenu::item:selected { background: #313244; color: #cba6f7; }
QMenu::item:disabled { color: #6c7086; }
QMenu::separator { height: 1px; background: #45475a; margin: 4px 10px; }
"""


def _clip(text: str):
    QApplication.clipboard().setText(str(text))


def _export_rows_csv(rows: list[dict], parent=None):
    if not rows:
        QMessageBox.information(parent, "Export", "No data to export.")
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export CSV", f"app_monitoring_{ts}.csv", "CSV (*.csv)"
    )
    if not path:
        return
    # Strip internal keys (prefixed with _)
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=clean[0].keys())
        writer.writeheader()
        writer.writerows(clean)
    QMessageBox.information(parent, "Export Complete", f"Saved:\n{path}")


def _export_row_json(row: dict, parent=None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export JSON", f"app_record_{ts}.json", "JSON (*.json)"
    )
    if not path:
        return
    clean = {k: v for k, v in row.items() if not k.startswith("_")}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, default=str)
    QMessageBox.information(parent, "Export Complete", f"Saved:\n{path}")


def build_row_context_menu(
    row_data: dict,
    global_pos,
    parent: QWidget,
    visible_rows: list[dict],
    on_drill_down=None,
    on_filter_by_app=None,
):
    menu = QMenu(parent)
    menu.setStyleSheet(_MENU_STYLE)

    # Title
    name = (row_data.get("display_name") or row_data.get("app_name") or
            row_data.get("error_code") or "Row")
    hdr = QAction(f"  {name}", menu)
    hdr.setEnabled(False)
    f = hdr.font(); f.setBold(True); hdr.setFont(f)
    menu.addAction(hdr)
    menu.addSeparator()

    # --- Copy section ---
    copy_menu = QMenu("📋  Copy…", menu)
    copy_menu.setStyleSheet(_MENU_STYLE)

    for key, label in [
        ("display_name",   "App Name"),
        ("app_name",       "App Name"),
        ("device_name",    "Device Name"),
        ("user",           "User"),
        ("install_state",  "Install State"),
        ("error_code",     "Error Code"),
        ("error_desc",     "Error Description"),
        ("success_rate",   "Success Rate"),
        ("_app_id",        "App ID"),
        ("_device_id",     "Device ID"),
    ]:
        if key in row_data and row_data[key] and row_data[key] != "—":
            display_val = row_data[key]
            if key.startswith("_"):
                label = key[1:].replace("_", " ").title()
            act = QAction(f"{label}: {str(display_val)[:50]}", copy_menu)
            act.triggered.connect(lambda checked, v=display_val: _clip(v))
            copy_menu.addAction(act)

    copy_menu.addSeparator()
    act_json = QAction("Full row as JSON", copy_menu)
    clean = {k: v for k, v in row_data.items() if not k.startswith("_")}
    act_json.triggered.connect(lambda: _clip(json.dumps(clean, default=str, indent=2)))
    copy_menu.addAction(act_json)
    menu.addMenu(copy_menu)

    # --- Export section ---
    menu.addSeparator()
    act_exp_row = QAction("💾  Export this row as JSON…", menu)
    act_exp_row.triggered.connect(lambda: _export_row_json(row_data, parent))
    menu.addAction(act_exp_row)

    act_exp_all = QAction(f"📤  Export {len(visible_rows)} visible rows as CSV…", menu)
    act_exp_all.triggered.connect(lambda: _export_rows_csv(visible_rows, parent))
    menu.addAction(act_exp_all)

    # --- Navigation section ---
    app_id = row_data.get("_app_id") or row_data.get("id")
    if app_id and on_drill_down:
        menu.addSeparator()
        act_drill = QAction("🔍  View all devices for this app →", menu)
        act_drill.triggered.connect(lambda: on_drill_down(app_id, name))
        menu.addAction(act_drill)

    if app_id and on_filter_by_app:
        act_filter = QAction("🔎  Filter Install Log by this app", menu)
        act_filter.triggered.connect(lambda: on_filter_by_app(app_id, name))
        menu.addAction(act_filter)

    app_id_for_portal = row_data.get("_app_id") or row_data.get("id")
    if app_id_for_portal:
        menu.addSeparator()
        act_portal = QAction("🌐  Open in Intune Portal", menu)
        act_portal.triggered.connect(lambda: _open_app_portal(app_id_for_portal))
        menu.addAction(act_portal)

    menu.exec(global_pos)


def _open_app_portal(app_id: str):
    try:
        from app.utils.intune_links import open_app_portal
        open_app_portal(app_id)
    except Exception as e:
        logger.error(f"Portal open failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main page
# ─────────────────────────────────────────────────────────────────────────────

class AppOpsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drill_app_id: str | None = None
        self._drill_app_name: str = ""
        self._setup_ui()

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("App Monitoring")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        hdr.addWidget(title)
        hdr.addStretch()
        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setMaximumWidth(110)
        refresh_btn.setStyleSheet(
            "QPushButton { background: #313244; padding: 7px 14px; "
            "border-radius: 6px; font-size: 12px; }"
            "QPushButton:hover { background: #45475a; }"
        )
        refresh_btn.clicked.connect(self.refresh)
        hdr.addWidget(refresh_btn)
        root.addLayout(hdr)

        # ── KPI cards row ─────────────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self._kpi_total     = KpiCard("TOTAL APPS",        "—", color="#cba6f7")
        self._kpi_installed = KpiCard("INSTALLED",          "—", color="#a6e3a1")
        self._kpi_failed    = KpiCard("FAILED",             "—", color="#f38ba8")
        self._kpi_pending   = KpiCard("PENDING",            "—", color="#f9e2af")
        self._kpi_rate      = KpiCard("INSTALL RATE",       "—", color="#89dceb")
        self._kpi_devices   = KpiCard("DEVICES WITH FAILS", "—", color="#fab387")

        for card in (self._kpi_total, self._kpi_installed, self._kpi_failed,
                     self._kpi_pending, self._kpi_rate, self._kpi_devices):
            kpi_row.addWidget(card)

        root.addLayout(kpi_row)

        # ── State distribution bar ────────────────────────────────────────────
        bar_frame = QFrame()
        bar_frame.setStyleSheet(
            "QFrame { background: #181825; border-radius: 8px; "
            "border: 1px solid #313244; padding: 4px; }"
        )
        bar_lay = QVBoxLayout(bar_frame)
        bar_lay.setContentsMargins(8, 6, 8, 6)
        bar_lay.setSpacing(4)

        bar_lbl = QLabel("INSTALL STATE DISTRIBUTION")
        bar_lbl.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; "
                              "letter-spacing: 1px;")
        bar_lay.addWidget(bar_lbl)

        self._state_bar = StateBar()
        bar_lay.addWidget(self._state_bar)

        # Legend
        self._bar_legend = QLabel("")
        self._bar_legend.setStyleSheet("color: #a6adc8; font-size: 11px;")
        bar_lay.addWidget(self._bar_legend)

        root.addWidget(bar_frame)

        # ── Tab widget ────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #313244;
                border-radius: 0 6px 6px 6px;
                background: #181825;
            }
            QTabBar::tab {
                background: #1e1e2e; color: #a6adc8;
                padding: 8px 20px; border-radius: 4px 4px 0 0;
                margin-right: 2px; font-size: 12px;
                border: 1px solid #313244; border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #313244; color: #cba6f7; font-weight: bold;
            }
            QTabBar::tab:hover { background: #45475a; color: #cdd6f4; }
        """)
        root.addWidget(self._tabs)

        self._build_catalog_tab()
        self._build_install_log_tab()
        self._build_error_tab()
        self._build_drill_tab()

    # ── Tab 1: App Catalog ────────────────────────────────────────────────────

    def _build_catalog_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        info = QLabel(
            "One row per app — aggregated install counts from all synced devices. "
            "Right-click any row to drill into per-device status or export data."
        )
        info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        info.setWordWrap(True)
        lay.addWidget(info)

        self._catalog_table = FilterableTable(CATALOG_COLS)
        self._catalog_table.set_multi_select(False)
        self._catalog_table.set_context_menu_handler(self._catalog_context_menu)
        self._catalog_table.row_selected.connect(self._on_catalog_row_selected)
        lay.addWidget(self._catalog_table)

        self._tabs.addTab(w, "📦  App Catalog")

    # ── Tab 2: Install Log ────────────────────────────────────────────────────

    def _build_install_log_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Filter toolbar
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        lbl = QLabel("Filter by state:")
        lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
        filter_bar.addWidget(lbl)

        self._state_combo = QComboBox()
        self._state_combo.setMaximumWidth(180)
        self._state_combo.addItems([
            "All States", "failed", "installed",
            "pendingInstall", "notInstalled", "unknown",
        ])
        self._state_combo.currentTextChanged.connect(self._refresh_install_log)
        filter_bar.addWidget(self._state_combo)

        self._log_app_filter_lbl = QLabel("")
        self._log_app_filter_lbl.setStyleSheet("color: #f9e2af; font-size: 11px;")
        filter_bar.addWidget(self._log_app_filter_lbl)

        clear_btn = QPushButton("✕  Clear App Filter")
        clear_btn.setMaximumWidth(130)
        clear_btn.setStyleSheet(
            "QPushButton { background: #45475a; padding: 4px 10px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #585b70; }"
        )
        clear_btn.clicked.connect(self._clear_log_app_filter)
        filter_bar.addWidget(clear_btn)
        filter_bar.addStretch()

        lay.addLayout(filter_bar)

        self._install_log_table = FilterableTable(INSTALL_LOG_COLS)
        self._install_log_table.set_multi_select(True)
        self._install_log_table.set_context_menu_handler(self._log_context_menu)
        lay.addWidget(self._install_log_table)

        self._tabs.addTab(w, "📋  Install Log")
        self._log_app_id_filter: str = ""

    # ── Tab 3: Error Analysis ────────────────────────────────────────────────

    def _build_error_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        info = QLabel(
            "Error codes from all failed installs — ranked by number of affected devices. "
            "Descriptions sourced from the Win32/Intune error catalogue."
        )
        info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        info.setWordWrap(True)
        lay.addWidget(info)

        self._error_table = FilterableTable(ERROR_COLS)
        self._error_table.set_multi_select(False)
        self._error_table.set_context_menu_handler(self._error_context_menu)
        lay.addWidget(self._error_table)

        self._tabs.addTab(w, "🔴  Error Analysis")

    # ── Tab 4: Device Drill-down ──────────────────────────────────────────────

    def _build_drill_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self._drill_header = QLabel(
            "Select an app in the App Catalog tab and right-click → "
            "\"View all devices for this app\" to load data here."
        )
        self._drill_header.setStyleSheet(
            "color: #a6adc8; font-size: 12px; padding: 6px; "
            "background: #313244; border-radius: 6px;"
        )
        self._drill_header.setWordWrap(True)
        lay.addWidget(self._drill_header)

        self._drill_table = FilterableTable(DRILL_COLS)
        self._drill_table.set_multi_select(True)
        self._drill_table.set_context_menu_handler(self._drill_context_menu)
        lay.addWidget(self._drill_table)

        self._tabs.addTab(w, "🔍  Device Drill-down")

    # ─────────────────────────────────────────────────────────────────────────
    # Refresh / data loading
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self):
        self._refresh_kpis()
        self._refresh_catalog()
        self._refresh_install_log()
        self._refresh_errors()
        # Drill-down only refreshes if an app is selected
        if self._drill_app_id:
            self._load_drill_down(self._drill_app_id, self._drill_app_name)

    def _refresh_kpis(self):
        try:
            from app.analytics.app_monitoring_queries import (
                get_app_monitoring_kpis, get_install_state_distribution,
            )
            kpis = get_app_monitoring_kpis()

            self._kpi_total.update_value(str(kpis["total_apps"]))
            self._kpi_installed.update_value(str(kpis["installed"]))

            fail_color = "#f38ba8" if kpis["failed"] > 0 else "#a6e3a1"
            self._kpi_failed.update_value(str(kpis["failed"]), fail_color)
            self._kpi_pending.update_value(str(kpis["pending"]))
            self._kpi_rate.update_value(f"{kpis['install_rate']}%")
            self._kpi_devices.update_value(str(kpis["devices_with_failures"]))

            dist = get_install_state_distribution()
            self._state_bar.set_data(dist)

            # Legend
            parts = []
            for d in dist:
                state = d["state"]
                color = STATE_COLORS.get(state.lower(), "#45475a")
                parts.append(f'<span style="color:{color}">■</span> {state}: {d["count"]}')
            self._bar_legend.setText("  ".join(parts))

        except Exception as e:
            logger.error(f"KPI refresh failed: {e}", exc_info=True)

    def _refresh_catalog(self):
        try:
            from app.analytics.app_monitoring_queries import get_app_install_summary
            data = get_app_install_summary()
            self._catalog_table.load_data(data)
        except Exception as e:
            logger.error(f"Catalog refresh failed: {e}", exc_info=True)

    def _refresh_install_log(self):
        try:
            from app.analytics.app_monitoring_queries import get_all_install_records
            state = self._state_combo.currentText()
            if state == "All States":
                state = ""
            data = get_all_install_records(
                state_filter=state,
                app_id_filter=self._log_app_id_filter,
            )
            self._install_log_table.load_data(data)
        except Exception as e:
            logger.error(f"Install log refresh failed: {e}", exc_info=True)

    def _refresh_errors(self):
        try:
            from app.analytics.app_monitoring_queries import get_app_error_analysis
            data = get_app_error_analysis()
            self._error_table.load_data(data)
        except Exception as e:
            logger.error(f"Error analysis refresh failed: {e}", exc_info=True)

    def _load_drill_down(self, app_id: str, app_name: str):
        try:
            from app.analytics.app_monitoring_queries import get_device_installs_for_app
            self._drill_app_id = app_id
            self._drill_app_name = app_name
            self._drill_header.setText(
                f"<b style='color:#cba6f7'>{app_name}</b>  —  "
                f"per-device install status  "
                f"<span style='color:#6c7086'>({app_id})</span>"
            )
            data = get_device_installs_for_app(app_id)
            self._drill_table.load_data(data)
            # Switch to drill tab
            self._tabs.setCurrentIndex(3)
        except Exception as e:
            logger.error(f"Drill-down failed: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Context menus
    # ─────────────────────────────────────────────────────────────────────────

    def _catalog_context_menu(self, row_data: dict, global_pos):
        # Inject _app_id from "id" field for context menu
        row_data = dict(row_data)
        if "id" in row_data and "_app_id" not in row_data:
            row_data["_app_id"] = row_data["id"]

        build_row_context_menu(
            row_data=row_data,
            global_pos=global_pos,
            parent=self,
            visible_rows=self._catalog_table.get_visible_data(),
            on_drill_down=self._load_drill_down,
            on_filter_by_app=self._filter_log_by_app,
        )

    def _log_context_menu(self, row_data: dict, global_pos):
        build_row_context_menu(
            row_data=row_data,
            global_pos=global_pos,
            parent=self,
            visible_rows=self._install_log_table.get_visible_data(),
            on_drill_down=self._load_drill_down,
        )

    def _error_context_menu(self, row_data: dict, global_pos):
        build_row_context_menu(
            row_data=row_data,
            global_pos=global_pos,
            parent=self,
            visible_rows=self._error_table.get_visible_data(),
        )

    def _drill_context_menu(self, row_data: dict, global_pos):
        build_row_context_menu(
            row_data=row_data,
            global_pos=global_pos,
            parent=self,
            visible_rows=self._drill_table.get_visible_data(),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Signals / helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _on_catalog_row_selected(self, row_idx: int, row_data: dict):
        pass  # single click does nothing — use double-click or right-click

    def _filter_log_by_app(self, app_id: str, app_name: str):
        self._log_app_id_filter = app_id
        self._log_app_filter_lbl.setText(f"  Filtered: {app_name}")
        self._refresh_install_log()
        self._tabs.setCurrentIndex(1)

    def _clear_log_app_filter(self):
        self._log_app_id_filter = ""
        self._log_app_filter_lbl.setText("")
        self._refresh_install_log()
