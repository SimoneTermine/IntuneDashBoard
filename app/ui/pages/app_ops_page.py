"""
app/ui/pages/app_ops_page.py

App Monitoring — v1.3.1

Layout:
  Header:     title + last-refresh label + Refresh button
  KPI row:    6 KpiCard widgets (global widget)
  State bar:  thin proportional colored strip + text legend
  Banner:     warning when tenant does not support getDeviceInstallStatusReport
  Tabs:
    📦  App Catalog     — per-app aggregated counts (always populated)
    📋  Install Log     — device×app×state; fallback: overview rows with banner
    🔴  Error Analysis  — error codes ranked by impact
    🔍  Device Drill    — per-device detail for selected app

Right-click context menus on all tables:
  Copy row · Export CSV · Copy row JSON · Open in Intune Portal
  View per-device status (Catalog) · Show in Install Log (Catalog)
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QFrame,
    QSizePolicy, QMessageBox, QFileDialog,
    QComboBox, QApplication, QMenu,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QAction, QPainter

from app.ui.widgets.filterable_table import FilterableTable
from app.ui.widgets.kpi_card import KpiCard

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Palette (Catppuccin Mocha)
# ─────────────────────────────────────────────────────────────────────────────
_GREEN  = "#a6e3a1"
_RED    = "#f38ba8"
_YELLOW = "#f9e2af"
_BLUE   = "#89dceb"
_MAUVE  = "#cba6f7"
_PEACH  = "#fab387"

_BG     = "#1e1e2e"
_MANTLE = "#181825"
_S0     = "#313244"
_S1     = "#45475a"
_S2     = "#585b70"
_OV0    = "#6c7086"
_SUB    = "#a6adc8"
_TEXT   = "#cdd6f4"

STATE_COLORS: dict[str, str] = {
    "installed":      _GREEN,
    "success":        _GREEN,
    "failed":         _RED,
    "installfailed":  _RED,
    "pendinginstall": _YELLOW,
    "pending":        _YELLOW,
    "notinstalled":   _MAUVE,
    "not installed":  _MAUVE,
    "notapplicable":  _OV0,
    "excluded":       _S2,
    "unknown":        _SUB,
}

# ─────────────────────────────────────────────────────────────────────────────
# Column definitions
# ─────────────────────────────────────────────────────────────────────────────

CATALOG_COLS = [
    ("display_name",  "App Name",          260),
    ("app_type",      "Type",              140),
    ("publisher",     "Publisher",         155),
    ("installed",     "✓ Installed",        90),
    ("failed",        "✗ Failed",           80),
    ("pending",       "⏳ Pending",          80),
    ("not_installed", "○ Not Installed",    110),
    ("success_rate",  "Success %",           90),
    ("total_devices", "Total Devices",      105),
    ("is_assigned",   "Assigned",            80),
    ("last_modified", "Last Modified",      140),
]

INSTALL_LOG_COLS = [
    ("app_name",      "App",               220),
    ("app_type",      "Type",              120),
    ("device_name",   "Device / Count",    175),
    ("user",          "User",              160),
    ("os",            "OS",                 80),
    ("install_state", "State",             130),
    ("error_code",    "Error Code",        110),
    ("error_desc",    "Description",       260),
    ("last_sync",     "Last Sync",         130),
]

ERROR_COLS = [
    ("error_code",    "Error Code",        110),
    ("description",   "Description",       310),
    ("device_count",  "Devices",            80),
    ("app_count",     "Apps",               70),
    ("severity",      "Severity",           90),
    ("affected_apps", "Top Affected Apps",  330),
]

DRILL_COLS = [
    ("device_name",   "Device / Count",    185),
    ("user",          "User",              160),
    ("os",            "OS",                 90),
    ("os_version",    "OS Version",        130),
    ("install_state", "State",             130),
    ("error_code",    "Error Code",        110),
    ("error_desc",    "Description",       260),
    ("compliance",    "Compliance",        110),
    ("last_sync",     "Last Sync",         130),
]


# ─────────────────────────────────────────────────────────────────────────────
# Shared button style helper
# ─────────────────────────────────────────────────────────────────────────────

def _btn_style(bg=_S0, fg=_TEXT, border=_S1, hover=_S1) -> str:
    return (
        f"QPushButton {{ background:{bg}; color:{fg}; border:1px solid {border}; "
        f"border-radius:6px; padding:5px 12px; font-size:12px; }}"
        f"QPushButton:hover {{ background:{hover}; }}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# StateBar  — thin proportional colored strip
# ─────────────────────────────────────────────────────────────────────────────

class StateBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[dict] = []
        self.setFixedHeight(16)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data: list[dict]):
        self._data = [d for d in data if d.get("count", 0) > 0]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = sum(d["count"] for d in self._data)
        if total == 0:
            p.fillRect(self.rect(), QColor(_S1))
            return
        x, w, h = 0, self.width(), self.height()
        for i, d in enumerate(self._data):
            sw = int(w * d["count"] / total)
            if i == len(self._data) - 1:
                sw = w - x
            if sw <= 0:
                continue
            p.fillRect(x, 0, sw, h, QColor(STATE_COLORS.get(d["state"].lower(), _S2)))
            x += sw


# ─────────────────────────────────────────────────────────────────────────────
# InfoBanner  — coloured notice strip
# ─────────────────────────────────────────────────────────────────────────────

class InfoBanner(QFrame):
    _PALETTE = {
        "warning": (_YELLOW, "#2a2110"),
        "info":    (_BLUE,   "#0d2437"),
        "error":   (_RED,    "#2a0d14"),
    }

    def __init__(self, text: str, level: str = "warning", parent=None):
        super().__init__(parent)
        fg, bg = self._PALETTE.get(level, self._PALETTE["warning"])
        self.setStyleSheet(
            f"QFrame {{ background:{bg}; border-radius:6px; border:1px solid {fg}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        icons = {"warning": "⚠️", "info": "ℹ️", "error": "🔴"}
        ic = QLabel(icons.get(level, "⚠️"))
        ic.setStyleSheet("border:none; background:transparent;")
        row.addWidget(ic)
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{fg}; font-size:11px; background:transparent; border:none;"
        )
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Context-menu helper
# ─────────────────────────────────────────────────────────────────────────────

_MENU_CSS = (
    f"QMenu {{ background:{_S0}; color:{_TEXT}; border:1px solid {_S1}; "
    f"border-radius:6px; padding:4px; }}"
    f"QMenu::item {{ padding:5px 18px; border-radius:4px; }}"
    f"QMenu::item:selected {{ background:{_S1}; color:{_MAUVE}; }}"
    f"QMenu::separator {{ height:1px; background:{_S1}; margin:3px 0; }}"
)


def _show_ctx_menu(
    parent: QWidget,
    row_data: dict,
    global_pos,
    visible_rows: list[dict],
    on_drill_down=None,
    on_filter_log=None,
):
    menu = QMenu(parent)
    menu.setStyleSheet(_MENU_CSS)

    def add(label, fn):
        a = QAction(label, parent)
        a.triggered.connect(fn)
        menu.addAction(a)

    add("📋  Copy row", lambda: QApplication.clipboard().setText(
        "\n".join(f"{k}: {v}" for k, v in row_data.items() if not k.startswith("_"))
    ))

    def _do_csv():
        path, _ = QFileDialog.getSaveFileName(parent, "Export CSV", "", "CSV (*.csv)")
        if not path:
            return
        keys = [k for k in (visible_rows[0] if visible_rows else row_data)
                if not k.startswith("_")]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(visible_rows)
        QMessageBox.information(parent, "Export", f"Saved: {path}")
    add(f"💾  Export {len(visible_rows)} rows → CSV", _do_csv)

    def _do_json():
        QApplication.clipboard().setText(
            json.dumps({k: v for k, v in row_data.items() if not k.startswith("_")},
                       indent=2, default=str)
        )
        QMessageBox.information(parent, "Copied", "Row JSON copied to clipboard.")
    add("📄  Copy row as JSON", _do_json)

    app_id = row_data.get("_app_id") or row_data.get("id")
    if app_id:
        menu.addSeparator()
        def _portal():
            url = (
                "https://intune.microsoft.com/#view/Microsoft_Intune_Apps/"
                f"SettingsMenu/~/0/appId/{app_id}"
            )
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        add("🌐  Open in Intune Portal", _portal)

        if on_drill_down:
            name = row_data.get("display_name") or row_data.get("app_name") or ""
            add("🔍  View per-device status",
                lambda _i=app_id, _n=name: on_drill_down(_i, _n))

        if on_filter_log:
            name = row_data.get("display_name") or row_data.get("app_name") or ""
            add("📋  Show in Install Log",
                lambda _i=app_id, _n=name: on_filter_log(_i, _n))

    menu.exec(global_pos)


# ─────────────────────────────────────────────────────────────────────────────
# Empty-state placeholder widget
# ─────────────────────────────────────────────────────────────────────────────

def _empty_state(icon: str, title: str, body: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setAlignment(Qt.AlignCenter)
    lay.setSpacing(10)
    for text, style in [
        (icon,  "font-size:36px;"),
        (title, f"color:{_TEXT}; font-size:14px; font-weight:bold;"),
        (body,  f"color:{_SUB}; font-size:12px;"),
    ]:
        lbl = QLabel(text)
        lbl.setStyleSheet(style)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(440)
        lay.addWidget(lbl)
    return w


# ─────────────────────────────────────────────────────────────────────────────
# Main page
# ─────────────────────────────────────────────────────────────────────────────

class AppOpsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drill_app_id:      str | None = None
        self._drill_app_name:    str        = ""
        self._log_app_id_filter: str        = ""
        self._setup_ui()

    # ──────────────────────────────────────────────────────────────────────────
    # Build UI
    # ──────────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # ── Header ─────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("App Monitoring")
        title.setStyleSheet(f"font-size:22px; font-weight:bold; color:{_MAUVE};")
        hdr.addWidget(title)
        hdr.addStretch()
        self._last_refresh = QLabel("")
        self._last_refresh.setStyleSheet(f"color:{_OV0}; font-size:11px;")
        hdr.addWidget(self._last_refresh)
        btn = QPushButton("↻  Refresh")
        btn.setFixedSize(100, 32)
        btn.setStyleSheet(_btn_style())
        btn.clicked.connect(self.refresh)
        hdr.addWidget(btn)
        root.addLayout(hdr)

        # ── KPI cards ──────────────────────────────────────────────────────
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)
        self._kpi_total     = KpiCard("TOTAL APPS",        "—", color=_MAUVE)
        self._kpi_installed = KpiCard("INSTALLED",          "—", color=_GREEN)
        self._kpi_failed    = KpiCard("FAILED",             "—", color=_RED)
        self._kpi_pending   = KpiCard("PENDING",            "—", color=_YELLOW)
        self._kpi_rate      = KpiCard("INSTALL RATE",       "—", color=_BLUE)
        self._kpi_apps_fail = KpiCard("APPS WITH FAILURES", "—", color=_PEACH)
        for card in (self._kpi_total, self._kpi_installed, self._kpi_failed,
                     self._kpi_pending, self._kpi_rate, self._kpi_apps_fail):
            kpi_row.addWidget(card)
        root.addLayout(kpi_row)

        # ── State distribution ─────────────────────────────────────────────
        bar_frame = QFrame()
        bar_frame.setStyleSheet(
            f"QFrame {{ background:{_MANTLE}; border-radius:8px; border:1px solid {_S0}; }}"
        )
        bl = QVBoxLayout(bar_frame)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(5)

        top = QHBoxLayout()
        bar_lbl = QLabel("INSTALL STATE DISTRIBUTION")
        bar_lbl.setStyleSheet(
            f"color:{_OV0}; font-size:10px; font-weight:bold; letter-spacing:1px;"
        )
        top.addWidget(bar_lbl)
        top.addStretch()
        self._bar_legend = QLabel("")
        self._bar_legend.setStyleSheet(f"color:{_SUB}; font-size:11px;")
        top.addWidget(self._bar_legend)
        bl.addLayout(top)

        self._state_bar = StateBar()
        bl.addWidget(self._state_bar)
        root.addWidget(bar_frame)

        # ── Warning banner ─────────────────────────────────────────────────
        self._overview_banner = InfoBanner(
            "Per-device data unavailable — getDeviceInstallStatusReport (Reports API beta) "
            "returns HTTP 400 for this tenant. Install Log and Device Drill-down show "
            "aggregated overview totals only. App Catalog and KPIs are accurate.",
            level="warning",
        )
        self._overview_banner.setVisible(False)
        root.addWidget(self._overview_banner)

        # ── Tab widget ─────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border:1px solid {_S0}; border-radius:0 8px 8px 8px;
                background:{_MANTLE};
            }}
            QTabBar::tab {{
                background:{_BG}; color:{_SUB};
                padding:8px 20px; border-radius:5px 5px 0 0;
                margin-right:2px; font-size:12px;
                border:1px solid {_S0}; border-bottom:none;
            }}
            QTabBar::tab:selected {{
                background:{_S0}; color:{_MAUVE}; font-weight:bold;
            }}
            QTabBar::tab:hover:!selected {{ background:{_S0}; color:{_TEXT}; }}
        """)
        root.addWidget(self._tabs, 1)

        self._build_catalog_tab()
        self._build_install_log_tab()
        self._build_error_tab()
        self._build_drill_tab()

    # ── Tab 0: App Catalog ─────────────────────────────────────────────────

    def _build_catalog_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(self._hint(
            "One row per managed app — counts from getAppStatusOverviewReport (always available). "
            "Right-click for drill-down, Install Log filter, portal link, or export."
        ))
        self._catalog_table = FilterableTable(CATALOG_COLS)
        self._catalog_table.set_multi_select(False)
        self._catalog_table.set_context_menu_handler(self._catalog_ctx)
        lay.addWidget(self._catalog_table)
        self._tabs.addTab(w, "📦  App Catalog")

    # ── Tab 1: Install Log ─────────────────────────────────────────────────

    def _build_install_log_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(self._lbl("State:"))
        self._state_combo = QComboBox()
        self._state_combo.setMaximumWidth(165)
        self._state_combo.setStyleSheet(f"""
            QComboBox {{ background:{_S0}; color:{_TEXT};
                border:1px solid {_S1}; border-radius:5px;
                padding:4px 8px; font-size:12px; }}
            QComboBox::drop-down {{ border:none; }}
            QComboBox QAbstractItemView {{ background:{_S0}; color:{_TEXT};
                selection-background-color:{_S1}; }}
        """)
        self._state_combo.addItems([
            "All States", "failed", "installed",
            "pendingInstall", "notInstalled", "notApplicable",
        ])
        self._state_combo.currentTextChanged.connect(self._refresh_install_log)
        bar.addWidget(self._state_combo)
        self._log_app_lbl = QLabel("")
        self._log_app_lbl.setStyleSheet(f"color:{_YELLOW}; font-size:11px; font-style:italic;")
        bar.addWidget(self._log_app_lbl)
        clr = QPushButton("✕ Clear filter")
        clr.setFixedHeight(28)
        clr.setMaximumWidth(125)
        clr.setStyleSheet(_btn_style())
        clr.clicked.connect(self._clear_log_filter)
        bar.addWidget(clr)
        bar.addStretch()
        lay.addLayout(bar)

        self._log_banner = InfoBanner(
            "Showing aggregated overview totals per app (one row per state bucket). "
            "Per-device rows require getDeviceInstallStatusReport (beta) — not available for this tenant.",
            level="info",
        )
        self._log_banner.setVisible(False)
        lay.addWidget(self._log_banner)

        self._install_log_table = FilterableTable(INSTALL_LOG_COLS)
        self._install_log_table.set_multi_select(True)
        self._install_log_table.set_context_menu_handler(self._log_ctx)
        lay.addWidget(self._install_log_table)
        self._tabs.addTab(w, "📋  Install Log")

    # ── Tab 2: Error Analysis ──────────────────────────────────────────────

    def _build_error_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(self._hint(
            "Failed installs grouped by error code, ranked by affected devices. "
            "Requires per-device data (getDeviceInstallStatusReport)."
        ))
        self._error_empty = _empty_state(
            "🎉", "No error data",
            "All apps installed cleanly, or per-device data is unavailable.\n"
            "Error analysis requires getDeviceInstallStatusReport (beta).",
        )
        self._error_empty.setVisible(False)
        lay.addWidget(self._error_empty)
        self._error_table = FilterableTable(ERROR_COLS)
        self._error_table.set_multi_select(False)
        self._error_table.set_context_menu_handler(self._error_ctx)
        lay.addWidget(self._error_table)
        self._tabs.addTab(w, "🔴  Error Analysis")

    # ── Tab 3: Device Drill-down ───────────────────────────────────────────

    def _build_drill_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self._drill_header = QLabel(
            "Right-click an app in App Catalog → \"View per-device status\" to load data here."
        )
        self._drill_header.setStyleSheet(
            f"color:{_SUB}; font-size:12px; padding:7px 10px; "
            f"background:{_S0}; border-radius:6px;"
        )
        self._drill_header.setWordWrap(True)
        lay.addWidget(self._drill_header)
        self._drill_banner = InfoBanner(
            "Showing aggregated overview totals only — per-device rows unavailable for this tenant.",
            level="info",
        )
        self._drill_banner.setVisible(False)
        lay.addWidget(self._drill_banner)
        self._drill_empty = _empty_state(
            "🔍", "No app selected",
            "Right-click an app in App Catalog\nand choose \"View per-device status\".",
        )
        lay.addWidget(self._drill_empty)
        self._drill_table = FilterableTable(DRILL_COLS)
        self._drill_table.set_multi_select(True)
        self._drill_table.set_context_menu_handler(self._drill_ctx)
        self._drill_table.setVisible(False)
        lay.addWidget(self._drill_table)
        self._tabs.addTab(w, "🔍  Device Drill-down")

    # ──────────────────────────────────────────────────────────────────────────
    # Static label helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{_SUB}; font-size:11px;")
        lbl.setWordWrap(True)
        return lbl

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{_SUB}; font-size:12px;")
        return lbl

    # ──────────────────────────────────────────────────────────────────────────
    # Refresh
    # ──────────────────────────────────────────────────────────────────────────

    def refresh(self):
        self._refresh_kpis()
        self._refresh_catalog()
        self._refresh_install_log()
        self._refresh_errors()
        if self._drill_app_id:
            self._load_drill_down(self._drill_app_id, self._drill_app_name)

    def _refresh_kpis(self):
        try:
            from app.analytics.app_monitoring_queries import (
                get_app_monitoring_kpis, get_install_state_distribution,
            )
            kpis = get_app_monitoring_kpis()

            self._kpi_total.set_value(str(kpis["total_apps"]))
            self._kpi_installed.set_value(str(kpis["installed"]))
            self._kpi_pending.set_value(str(kpis["pending"]))
            self._kpi_rate.set_value(f"{kpis['install_rate']}%")
            self._kpi_apps_fail.set_value(str(kpis["devices_with_failures"]))

            f = kpis["failed"]
            self._kpi_failed.set_value(str(f))
            fail_color = _RED if f > 0 else _GREEN
            self._kpi_failed.value_label.setStyleSheet(
                f"color:{fail_color}; font-size:28px; font-weight:bold;"
            )

            dist = get_install_state_distribution()
            self._state_bar.set_data(dist)

            parts = []
            for d in dist:
                c = STATE_COLORS.get(d["state"].lower(), _S2)
                parts.append(
                    f'<span style="color:{c}">■</span> '
                    f'<span style="color:{_SUB}">{d["state"]}</span> '
                    f'<b style="color:{_TEXT}">{d["count"]}</b>'
                )
            self._bar_legend.setText("  ".join(parts))
            self._last_refresh.setText(f"Refreshed {datetime.now().strftime('%H:%M:%S')}")

        except Exception as e:
            logger.error(f"KPI refresh failed: {e}", exc_info=True)

    def _refresh_catalog(self):
        try:
            from app.analytics.app_monitoring_queries import get_app_install_summary
            self._catalog_table.load_data(get_app_install_summary())
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
            synthetic = bool(data) and data[0].get("_synthetic", False)
            self._log_banner.setVisible(synthetic)
            self._overview_banner.setVisible(synthetic)
        except Exception as e:
            logger.error(f"Install log refresh failed: {e}", exc_info=True)

    def _refresh_errors(self):
        try:
            from app.analytics.app_monitoring_queries import get_app_error_analysis
            data = get_app_error_analysis()
            self._error_table.load_data(data)
            self._error_table.setVisible(bool(data))
            self._error_empty.setVisible(not data)
        except Exception as e:
            logger.error(f"Error analysis refresh failed: {e}", exc_info=True)

    def _load_drill_down(self, app_id: str, app_name: str):
        try:
            from app.analytics.app_monitoring_queries import get_device_installs_for_app
            self._drill_app_id   = app_id
            self._drill_app_name = app_name
            self._drill_header.setText(
                f"<b style='color:{_MAUVE}'>{app_name}</b>  —  "
                f"per-device install status  "
                f"<span style='color:{_OV0}'>({app_id})</span>"
            )
            data = get_device_installs_for_app(app_id)
            synthetic = bool(data) and data[0].get("_synthetic", False)
            self._drill_banner.setVisible(synthetic)
            if data:
                self._drill_empty.setVisible(False)
                self._drill_table.setVisible(True)
                self._drill_table.load_data(data)
            else:
                self._drill_empty.setVisible(True)
                self._drill_table.setVisible(False)
            self._tabs.setCurrentIndex(3)
        except Exception as e:
            logger.error(f"Drill-down failed: {e}", exc_info=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Context menus
    # ──────────────────────────────────────────────────────────────────────────

    def _catalog_ctx(self, row_data: dict, global_pos):
        rd = dict(row_data)
        if "id" in rd:
            rd["_app_id"] = rd["id"]
        _show_ctx_menu(self, rd, global_pos,
                       visible_rows=self._catalog_table.get_visible_data(),
                       on_drill_down=self._load_drill_down,
                       on_filter_log=self._filter_log_by_app)

    def _log_ctx(self, row_data: dict, global_pos):
        _show_ctx_menu(self, row_data, global_pos,
                       visible_rows=self._install_log_table.get_visible_data(),
                       on_drill_down=self._load_drill_down)

    def _error_ctx(self, row_data: dict, global_pos):
        _show_ctx_menu(self, row_data, global_pos,
                       visible_rows=self._error_table.get_visible_data())

    def _drill_ctx(self, row_data: dict, global_pos):
        _show_ctx_menu(self, row_data, global_pos,
                       visible_rows=self._drill_table.get_visible_data())

    # ──────────────────────────────────────────────────────────────────────────
    # Cross-tab actions
    # ──────────────────────────────────────────────────────────────────────────

    def _filter_log_by_app(self, app_id: str, app_name: str):
        self._log_app_id_filter = app_id
        self._log_app_lbl.setText(f"  App: {app_name}")
        self._tabs.setCurrentIndex(1)
        self._refresh_install_log()

    def _clear_log_filter(self):
        self._log_app_id_filter = ""
        self._log_app_lbl.setText("")
        self._refresh_install_log()
