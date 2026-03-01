"""
Reusable KPI card widget.
"""

from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class KpiCard(QFrame):
    """A styled card showing a metric label and value."""

    def __init__(self, title: str, value: str = "—", subtitle: str = "", color: str = "#cba6f7", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("KpiCardFrame")
        self.setStyleSheet(f"""
            QFrame#KpiCardFrame {{
                background-color: #313244;
                border-radius: 10px;
                border: 1px solid #45475a;
            }}
        """)
        self.setMinimumSize(150, 100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        self.title_label.setAlignment(Qt.AlignLeft)

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: bold;")
        self.value_label.setAlignment(Qt.AlignLeft)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.subtitle_label.setAlignment(Qt.AlignLeft)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.subtitle_label)

    def set_value(self, value: str):
        self.value_label.setText(str(value))

    def set_subtitle(self, subtitle: str):
        self.subtitle_label.setText(subtitle)
