"""
Chart widgets using pyqtgraph for local rendering (no browser/server).
"""

from typing import Optional
import logging

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

try:
    import pyqtgraph as pg
    import numpy as np
    HAS_PYQTGRAPH = True
    pg.setConfigOptions(antialias=True, background="#1e1e2e", foreground="#cdd6f4")
except ImportError:
    HAS_PYQTGRAPH = False
    logger.warning("pyqtgraph not available — charts disabled")


def _color_for_state(state: str) -> tuple:
    colors = {
        "compliant": (166, 227, 161),
        "noncompliant": (243, 139, 168),
        "unknown": (166, 173, 200),
        "error": (250, 179, 135),
        "conflict": (249, 226, 175),
        "windows": (137, 220, 235),
        "ios": (203, 166, 247),
        "android": (166, 227, 161),
        "macos": (250, 179, 135),
    }
    return colors.get(state.lower(), (166, 173, 200))


class CompliancePieChart(QWidget):
    """Pie chart for compliance breakdown using pyqtgraph bar chart as fallback."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._widget: Optional[QWidget] = None

    def update_data(self, data: list[dict]):
        """
        data: list of {'state': str, 'count': int}
        """
        if self._widget:
            self._layout.removeWidget(self._widget)
            self._widget.deleteLater()
            self._widget = None

        if not data:
            lbl = QLabel("No data available")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #6c7086;")
            self._widget = lbl
            self._layout.addWidget(self._widget)
            return

        if not HAS_PYQTGRAPH:
            self._widget = self._text_chart(data)
            self._layout.addWidget(self._widget)
            return

        # Build a bar chart (pyqtgraph doesn't have native pie, but bar is clear)
        pw = pg.PlotWidget(title="Compliance State")
        pw.setBackground("#313244")
        pw.getAxis("bottom").setStyle(tickTextOffset=5)
        pw.getAxis("left").setStyle(tickTextOffset=5)
        pw.showGrid(x=False, y=True, alpha=0.3)
        pw.setMaximumHeight(220)

        states = [d["state"] for d in data]
        counts = [d["count"] for d in data]
        brushes = [pg.mkBrush(*_color_for_state(s)) for s in states]

        x = list(range(len(states)))
        bars = pg.BarGraphItem(x=x, height=counts, width=0.6, brushes=brushes)
        pw.addItem(bars)

        ticks = [(i, s) for i, s in enumerate(states)]
        pw.getAxis("bottom").setTicks([ticks])

        self._widget = pw
        self._layout.addWidget(self._widget)

    def _text_chart(self, data: list[dict]) -> QLabel:
        lines = "\n".join([f"  {d['state']:20s} {d['count']}" for d in data])
        lbl = QLabel(f"Compliance Breakdown:\n{lines}")
        lbl.setStyleSheet("font-family: monospace; color: #cdd6f4; padding: 8px;")
        return lbl


class OsBarChart(QWidget):
    """Bar chart for OS distribution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._widget: Optional[QWidget] = None

    def update_data(self, data: list[dict]):
        """data: list of {'os': str, 'count': int}"""
        if self._widget:
            self._layout.removeWidget(self._widget)
            self._widget.deleteLater()
            self._widget = None

        if not data or not HAS_PYQTGRAPH:
            lbl = QLabel("No data" if not data else "Charts unavailable (install pyqtgraph)")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #6c7086;")
            self._widget = lbl
            self._layout.addWidget(self._widget)
            return

        pw = pg.PlotWidget(title="Devices by OS")
        pw.setBackground("#313244")
        pw.showGrid(x=False, y=True, alpha=0.3)
        pw.setMaximumHeight(220)

        oses = [d["os"] for d in data]
        counts = [d["count"] for d in data]
        brushes = [pg.mkBrush(*_color_for_state(o)) for o in oses]

        x = list(range(len(oses)))
        bars = pg.BarGraphItem(x=x, height=counts, width=0.6, brushes=brushes)
        pw.addItem(bars)
        ticks = [(i, o[:15]) for i, o in enumerate(oses)]
        pw.getAxis("bottom").setTicks([ticks])

        self._widget = pw
        self._layout.addWidget(self._widget)
