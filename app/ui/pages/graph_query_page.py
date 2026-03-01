"""
Graph Query page.
Run ad-hoc Microsoft Graph queries directly from the Analysis section.
"""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QMessageBox,
)


class GraphQueryPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Graph Query Lab")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        help_text = QLabel(
            "Esegui query custom direttamente su Microsoft Graph. "
            "Puoi usare endpoint relativi (es. `deviceManagement/managedDevices?$top=5`) "
            "oppure URL assoluti `https://graph.microsoft.com/...`."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet(
            "color: #a6adc8; font-size: 12px; padding: 6px; "
            "background: #313244; border-radius: 6px;"
        )
        layout.addWidget(help_text)

        endpoint_row = QHBoxLayout()
        endpoint_row.addWidget(QLabel("Endpoint:"))
        self._endpoint_input = QLineEdit()
        self._endpoint_input.setPlaceholderText("deviceManagement/managedDevices?$top=5")
        self._endpoint_input.returnPressed.connect(self._run_query)
        endpoint_row.addWidget(self._endpoint_input, 1)
        layout.addLayout(endpoint_row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("API:"))
        self._api_combo = QComboBox()
        self._api_combo.addItems(["v1.0", "beta"])
        self._api_combo.setMaximumWidth(100)
        options_row.addWidget(self._api_combo)

        options_row.addWidget(QLabel("Mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Single response", "Paged (collect all)"])
        self._mode_combo.setMaximumWidth(180)
        options_row.addWidget(self._mode_combo)

        options_row.addWidget(QLabel("Max items:"))
        self._max_items = QSpinBox()
        self._max_items.setMinimum(1)
        self._max_items.setMaximum(5000)
        self._max_items.setValue(250)
        self._max_items.setMaximumWidth(90)
        options_row.addWidget(self._max_items)

        options_row.addStretch()

        self._run_btn = QPushButton("▶ Run Query")
        self._run_btn.setMaximumWidth(110)
        self._run_btn.clicked.connect(self._run_query)
        options_row.addWidget(self._run_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setMaximumWidth(90)
        self._clear_btn.clicked.connect(self._clear_output)
        options_row.addWidget(self._clear_btn)

        layout.addLayout(options_row)

        self._status = QLabel("Ready")
        self._status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self._status)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("I risultati JSON della query compariranno qui...")
        layout.addWidget(self._output, 1)

    def refresh(self):
        """Page refresh hook."""
        # Intentionally no auto-query.
        return

    def _run_query(self):
        endpoint = self._endpoint_input.text().strip()
        if not endpoint:
            QMessageBox.information(self, "Graph Query", "Inserisci un endpoint Graph da interrogare.")
            return

        api_version = self._api_combo.currentText()
        collect_all = self._mode_combo.currentText().startswith("Paged")
        max_items = self._max_items.value()

        self._run_btn.setEnabled(False)
        self._status.setText("Running query...")

        try:
            from app.graph.client import get_client

            client = get_client()
            if collect_all:
                data = list(client.get_paged(endpoint, api_version=api_version, max_items=max_items))
                payload = {
                    "mode": "paged",
                    "count": len(data),
                    "items": data,
                }
            else:
                payload = client.get(endpoint, api_version=api_version)

            self._output.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

            if collect_all:
                self._status.setText(f"Done. Retrieved {len(payload['items'])} items.")
            else:
                self._status.setText("Done.")
        except Exception as e:
            self._status.setText("Query failed")
            QMessageBox.warning(self, "Graph Query Failed", str(e))
        finally:
            self._run_btn.setEnabled(True)

    def _clear_output(self):
        self._output.clear()
        self._status.setText("Ready")
