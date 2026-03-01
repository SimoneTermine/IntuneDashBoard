"""
Compact sync status widget shown in the sidebar.
Shows last sync time, status dot, progress bar, and Sync Now button.
The button is disabled during cooldown with a countdown timer.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QTimer


class SyncStatusWidget(QWidget):

    sync_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cooldown_remaining = 0
        self._setup_ui()

        # Refresh sync info every 30 s
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(30_000)

        # Cooldown countdown every 1 s
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.timeout.connect(self._tick_cooldown)

        self._refresh_status()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # ── Status dot + label ──────────────────────────────────────
        status_row = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._status_label = QLabel("Unknown")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        status_row.addWidget(self._dot)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        # ── Last sync time ──────────────────────────────────────────
        self._time_label = QLabel("Last sync: never")
        self._time_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(self._time_label)

        # ── Stage label (visible during sync) ──────────────────────
        self._stage_label = QLabel("")
        self._stage_label.setStyleSheet("color: #89dceb; font-size: 10px;")
        self._stage_label.setWordWrap(True)
        self._stage_label.hide()
        layout.addWidget(self._stage_label)

        # ── Progress bar ───────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # ── Sync button ────────────────────────────────────────────
        self._sync_btn = QPushButton("↻  Sync Now")
        self._sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border-radius: 5px;
                padding: 6px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #585b70; }
            QPushButton:disabled { color: #6c7086; background-color: #313244; }
        """)
        self._sync_btn.clicked.connect(self.sync_requested.emit)
        layout.addWidget(self._sync_btn)

    # ─────────────────────────────────────────────────────────────
    # Public API called by main_window
    # ─────────────────────────────────────────────────────────────

    def set_syncing(self, syncing: bool):
        if syncing:
            self._progress.show()
            self._progress.setValue(0)
            self._stage_label.show()
            self._stage_label.setText("Starting…")
            self._dot.setStyleSheet("color: #89dceb;")
            self._status_label.setText("Syncing…")
            self._sync_btn.setEnabled(False)
            self._sync_btn.setText("↻  Syncing…")
        else:
            self._progress.hide()
            self._stage_label.hide()
            self._sync_btn.setText("↻  Sync Now")
            self._refresh_status()
            # Start cooldown — read from engine class variable
            self._start_cooldown()

    def update_progress(self, stage: str, percent: int, message: str, is_error: bool = False):
        self._progress.setValue(percent)
        self._stage_label.setText(message[:50])
        if is_error:
            self._dot.setStyleSheet("color: #f38ba8;")
            self._status_label.setText("Error")
            self._stage_label.setStyleSheet("color: #f38ba8; font-size: 10px;")
        else:
            self._stage_label.setStyleSheet("color: #89dceb; font-size: 10px;")

    def start_cooldown(self, seconds: int):
        """Called externally to start a cooldown timer."""
        self._cooldown_remaining = seconds
        self._sync_btn.setEnabled(False)
        self._cooldown_timer.start(1000)
        self._update_cooldown_label()

    # ─────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────

    def _refresh_status(self):
        try:
            from app.analytics.queries import get_last_sync_info
            info = get_last_sync_info()
            self._update_status_display(info.get("status", "never"), info.get("time"))
        except Exception:
            pass

    def _update_status_display(self, status: str, time):
        color_map = {
            "success": "#a6e3a1",
            "running": "#89dceb",
            "partial": "#f9e2af",
            "failed": "#f38ba8",
            "never": "#6c7086",
        }
        color = color_map.get(status, "#a6adc8")
        self._dot.setStyleSheet(f"color: {color};")
        self._status_label.setText(status.title())
        if time:
            ts = time.strftime("%m/%d %H:%M") if isinstance(time, datetime) else str(time)
            self._time_label.setText(f"Last: {ts}")
        else:
            self._time_label.setText("Last sync: never")

    def _start_cooldown(self):
        from app.collector.sync_engine import MIN_SYNC_INTERVAL_SECONDS, SyncEngine
        elapsed = SyncEngine.seconds_since_last_sync()
        if elapsed is not None:
            remaining = int(MIN_SYNC_INTERVAL_SECONDS - elapsed)
            if remaining > 0:
                self._cooldown_remaining = remaining
                self._sync_btn.setEnabled(False)
                self._cooldown_timer.start(1000)
                self._update_cooldown_label()
                return
        # No cooldown needed
        self._sync_btn.setEnabled(True)

    def _tick_cooldown(self):
        self._cooldown_remaining -= 1
        if self._cooldown_remaining <= 0:
            self._cooldown_timer.stop()
            self._cooldown_remaining = 0
            self._sync_btn.setEnabled(True)
            self._sync_btn.setText("↻  Sync Now")
        else:
            self._update_cooldown_label()

    def _update_cooldown_label(self):
        self._sync_btn.setText(f"↻  Wait {self._cooldown_remaining}s")
