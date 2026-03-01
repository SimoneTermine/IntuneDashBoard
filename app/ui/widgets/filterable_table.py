"""
Filterable, sortable table widget.
Wraps QTableWidget with column config and quick-filter.
"""

from datetime import datetime
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QLineEdit, QPushButton, QComboBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor


COMPLIANCE_COLORS = {
    "compliant": "#a6e3a1",
    "noncompliant": "#f38ba8",
    "error": "#fab387",
    "conflict": "#f9e2af",
    "unknown": "#a6adc8",
    "notapplicable": "#6c7086",
    "installed": "#a6e3a1",
    "failed": "#f38ba8",
    "notinstalled": "#cba6f7",
    "pendinginstall": "#f9e2af",
    "excluded": "#6c7086",
    "applied": "#89dceb",
    "filtered": "#f9e2af",
}


class FilterableTable(QWidget):
    """
    Table widget with built-in search filtering, row count display, and export button.
    Columns: list of (key, header_label, width) tuples.
    """

    row_selected = Signal(int, dict)  # row index, row data dict
    export_requested = Signal()

    def __init__(self, columns: list[tuple], parent=None):
        super().__init__(parent)
        self._columns = columns
        self._all_data: list[dict] = []
        self._filtered_data: list[dict] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Toolbar row
        toolbar = QHBoxLayout()
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍  Filter table...")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._apply_filter)
        self._search_box.setMaximumWidth(300)

        self._count_label = QLabel("0 items")
        self._count_label.setStyleSheet("color: #a6adc8; font-size: 11px;")

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setMaximumWidth(110)
        self._export_btn.setObjectName("")
        self._export_btn.setStyleSheet("""
            QPushButton { background-color: #45475a; padding: 6px 12px; font-size: 12px; }
            QPushButton:hover { background-color: #585b70; }
        """)
        self._export_btn.clicked.connect(self.export_requested.emit)

        toolbar.addWidget(self._search_box)
        toolbar.addWidget(self._count_label)
        toolbar.addStretch()
        toolbar.addWidget(self._export_btn)
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels([c[1] for c in self._columns])
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setShowGrid(False)

        for i, (_, _, width) in enumerate(self._columns):
            self._table.setColumnWidth(i, width)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

    def load_data(self, data: list[dict]):
        """Load new data and refresh table."""
        self._all_data = data
        self._filtered_data = data
        self._apply_filter(self._search_box.text())

    def _apply_filter(self, text: str):
        if text.strip():
            tl = text.lower()
            self._filtered_data = [
                row for row in self._all_data
                if any(tl in str(v).lower() for v in row.values())
            ]
        else:
            self._filtered_data = self._all_data
        self._render()

    def _render(self):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(self._filtered_data))

        for row_i, row_data in enumerate(self._filtered_data):
            for col_i, (key, _, _) in enumerate(self._columns):
                value = row_data.get(key, "")
                display = _format_value(value)
                item = QTableWidgetItem(display)
                item.setData(Qt.UserRole, row_data)

                # Color-code compliance/status cells
                color_key = display.lower().strip()
                if color_key in COMPLIANCE_COLORS:
                    item.setForeground(QColor(COMPLIANCE_COLORS[color_key]))

                self._table.setItem(row_i, col_i, item)

        self._table.setSortingEnabled(True)
        self._count_label.setText(f"{len(self._filtered_data)} / {len(self._all_data)} items")

    def _on_selection_changed(self):
        rows = self._table.selectedItems()
        if rows:
            item = rows[0]
            row_data = item.data(Qt.UserRole)
            if row_data:
                self.row_selected.emit(self._table.currentRow(), row_data)

    def get_visible_data(self) -> list[dict]:
        return list(self._filtered_data)

    def clear(self):
        self._all_data = []
        self._filtered_data = []
        self._table.setRowCount(0)
        self._count_label.setText("0 items")


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)
