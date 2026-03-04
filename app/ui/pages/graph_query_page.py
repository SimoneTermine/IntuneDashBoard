"""
app/ui/pages/graph_query_page.py

Graph Query Lab — v1.3.0.

Changes vs v1.2.x:
  - Method selector: GET / POST / PATCH / DELETE
  - Request Body editor (QPlainTextEdit) shown for POST / PATCH
  - "Format JSON" button validates and pretty-prints the body
  - "Copy Result" button for quick clipboard export
  - Paged mode restricted to GET (disabled for POST/PATCH/DELETE)
  - Syntax error feedback in status bar when body JSON is invalid
"""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QMessageBox,
    QFrame, QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

# ─────────────────────────────────────────────────────────────────────────────
# Palette (matches Catppuccin Mocha used across the app)
# ─────────────────────────────────────────────────────────────────────────────
_C = {
    "base":     "#1e1e2e",
    "mantle":   "#181825",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "overlay0": "#6c7086",
    "subtext":  "#a6adc8",
    "text":     "#cdd6f4",
    "mauve":    "#cba6f7",
    "green":    "#a6e3a1",
    "red":      "#f38ba8",
    "yellow":   "#f9e2af",
    "blue":     "#89dceb",
    "peach":    "#fab387",
}

_BTN_STYLE = """
    QPushButton {{
        background:{bg}; color:{fg};
        border:1px solid {border}; border-radius:6px;
        padding:6px 14px; font-size:12px;
    }}
    QPushButton:hover {{ background:{hover}; }}
    QPushButton:disabled {{ color:{disabled}; }}
"""

_PRIMARY_BTN = _BTN_STYLE.format(
    bg=_C["mauve"], fg=_C["base"], border=_C["mauve"],
    hover="#b89cf5", disabled=_C["overlay0"]
)
_SECONDARY_BTN = _BTN_STYLE.format(
    bg=_C["surface0"], fg=_C["text"], border=_C["surface1"],
    hover=_C["surface1"], disabled=_C["overlay0"]
)

_COMBO_STYLE = f"""
    QComboBox {{
        background:{_C["surface0"]}; color:{_C["text"]};
        border:1px solid {_C["surface1"]}; border-radius:5px;
        padding:4px 8px; font-size:12px;
    }}
    QComboBox::drop-down {{ border:none; }}
    QComboBox QAbstractItemView {{
        background:{_C["surface0"]}; color:{_C["text"]};
        selection-background-color:{_C["surface1"]};
    }}
"""

_TEXTEDIT_STYLE = f"""
    QPlainTextEdit, QLineEdit {{
        background:{_C["mantle"]}; color:{_C["text"]};
        border:1px solid {_C["surface1"]}; border-radius:6px;
        padding:6px; font-family: monospace; font-size:12px;
        selection-background-color:{_C["surface0"]};
    }}
    QPlainTextEdit:focus, QLineEdit:focus {{
        border:1px solid {_C["mauve"]};
    }}
"""

# Method colour hints
_METHOD_COLORS = {
    "GET":    _C["green"],
    "POST":   _C["blue"],
    "PATCH":  _C["yellow"],
    "DELETE": _C["red"],
}

# Example bodies shown when switching method
_EXAMPLE_BODIES = {
    "POST": json.dumps(
        {
            "filter": "(ApplicationId eq 'YOUR-APP-ID')",
            "top": 50,
            "skip": 0,
        },
        indent=2,
    ),
    "PATCH": json.dumps({"displayName": "New Name"}, indent=2),
    "DELETE": "",
}

# Preset endpoints
_PRESETS: list[tuple[str, str, str]] = [
    ("GET",   "v1.0",  "deviceManagement/managedDevices?$top=10"),
    ("GET",   "v1.0",  "deviceManagement/deviceCompliancePolicies"),
    ("GET",   "beta",  "deviceAppManagement/mobileApps"),
    ("GET",   "v1.0",  "groups?$top=20"),
    ("GET",   "v1.0",  "organization"),
    ("POST",  "beta",  "deviceManagement/reports/getAppStatusOverviewReport"),
    ("POST",  "beta",  "deviceManagement/reports/getDeviceInstallStatusReport"),
]


class GraphQueryPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # ── Title ─────────────────────────────────────────────────────────────
        title = QLabel("Graph Query Lab")
        title.setStyleSheet(
            f"font-size:22px; font-weight:bold; color:{_C['mauve']};"
        )
        root.addWidget(title)

        help_text = QLabel(
            "Execute ad-hoc Microsoft Graph queries. "
            "Use relative endpoints (<code>deviceManagement/managedDevices?$top=5</code>) "
            "or absolute URLs (<code>https://graph.microsoft.com/v1.0/...</code>). "
            "POST / PATCH requests accept a JSON body."
        )
        help_text.setWordWrap(True)
        help_text.setTextFormat(Qt.RichText)
        help_text.setStyleSheet(
            f"color:{_C['subtext']}; font-size:12px; padding:8px 12px; "
            f"background:{_C['surface0']}; border-radius:7px;"
        )
        root.addWidget(help_text)

        # ── Preset picker ─────────────────────────────────────────────────────
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_lbl = QLabel("Preset:")
        preset_lbl.setStyleSheet(f"color:{_C['subtext']}; font-size:12px;")
        preset_row.addWidget(preset_lbl)

        self._preset_combo = QComboBox()
        self._preset_combo.setMaximumWidth(420)
        self._preset_combo.setStyleSheet(_COMBO_STYLE)
        self._preset_combo.addItem("— select a preset —", None)
        for method, api, ep in _PRESETS:
            self._preset_combo.addItem(f"[{method}] {api}  →  {ep}", (method, api, ep))
        self._preset_combo.currentIndexChanged.connect(self._apply_preset)
        preset_row.addWidget(self._preset_combo)
        preset_row.addStretch()
        root.addLayout(preset_row)

        # ── Endpoint row ──────────────────────────────────────────────────────
        ep_row = QHBoxLayout()
        ep_row.setSpacing(8)

        self._method_combo = QComboBox()
        self._method_combo.setFixedWidth(90)
        self._method_combo.setStyleSheet(_COMBO_STYLE)
        self._method_combo.addItems(["GET", "POST", "PATCH", "DELETE"])
        self._method_combo.currentTextChanged.connect(self._on_method_changed)
        ep_row.addWidget(self._method_combo)

        self._endpoint_input = QLineEdit()
        self._endpoint_input.setPlaceholderText(
            "deviceManagement/managedDevices?$top=10"
        )
        self._endpoint_input.setStyleSheet(_TEXTEDIT_STYLE)
        self._endpoint_input.returnPressed.connect(self._run_query)
        ep_row.addWidget(self._endpoint_input, 1)
        root.addLayout(ep_row)

        # ── Options row ───────────────────────────────────────────────────────
        opts = QHBoxLayout()
        opts.setSpacing(12)

        self._api_combo = QComboBox()
        self._api_combo.setFixedWidth(90)
        self._api_combo.setStyleSheet(_COMBO_STYLE)
        self._api_combo.addItems(["v1.0", "beta"])
        opts.addWidget(QLabel("API:"))
        opts.addWidget(self._api_combo)

        self._mode_combo = QComboBox()
        self._mode_combo.setFixedWidth(200)
        self._mode_combo.setStyleSheet(_COMBO_STYLE)
        self._mode_combo.addItems(["Single response", "Paged (collect all)"])
        opts.addWidget(QLabel("Mode:"))
        opts.addWidget(self._mode_combo)

        self._max_items = QSpinBox()
        self._max_items.setMinimum(1)
        self._max_items.setMaximum(5000)
        self._max_items.setValue(250)
        self._max_items.setFixedWidth(90)
        self._max_items.setStyleSheet(
            f"QSpinBox {{ background:{_C['surface0']}; color:{_C['text']}; "
            f"border:1px solid {_C['surface1']}; border-radius:5px; padding:4px; }}"
        )
        opts.addWidget(QLabel("Max:"))
        opts.addWidget(self._max_items)

        for lbl in root.findChildren(QLabel):
            pass  # labels inside opts already styled by parent

        opts.addStretch()

        self._run_btn = QPushButton("▶  Run")
        self._run_btn.setFixedWidth(100)
        self._run_btn.setStyleSheet(_PRIMARY_BTN)
        self._run_btn.clicked.connect(self._run_query)
        opts.addWidget(self._run_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedWidth(80)
        self._clear_btn.setStyleSheet(_SECONDARY_BTN)
        self._clear_btn.clicked.connect(self._clear_output)
        opts.addWidget(self._clear_btn)

        root.addLayout(opts)

        # ── Request body (POST / PATCH only) ──────────────────────────────────
        self._body_frame = QFrame()
        self._body_frame.setStyleSheet(
            f"QFrame {{ background:{_C['surface0']}; border-radius:8px; "
            f"border:1px solid {_C['surface1']}; }}"
        )
        body_lay = QVBoxLayout(self._body_frame)
        body_lay.setContentsMargins(10, 8, 10, 10)
        body_lay.setSpacing(6)

        body_hdr = QHBoxLayout()
        body_title = QLabel("Request Body (JSON)")
        body_title.setStyleSheet(
            f"color:{_C['mauve']}; font-size:12px; font-weight:bold; "
            "background:transparent; border:none;"
        )
        body_hdr.addWidget(body_title)
        body_hdr.addStretch()

        self._fmt_btn = QPushButton("⟳  Format JSON")
        self._fmt_btn.setFixedWidth(120)
        self._fmt_btn.setStyleSheet(_SECONDARY_BTN)
        self._fmt_btn.clicked.connect(self._format_body)
        body_hdr.addWidget(self._fmt_btn)

        self._body_valid_lbl = QLabel("")
        self._body_valid_lbl.setStyleSheet("border:none; background:transparent;")
        body_hdr.addWidget(self._body_valid_lbl)
        body_lay.addLayout(body_hdr)

        self._body_edit = QPlainTextEdit()
        self._body_edit.setMinimumHeight(120)
        self._body_edit.setMaximumHeight(220)
        self._body_edit.setStyleSheet(_TEXTEDIT_STYLE)
        self._body_edit.setPlaceholderText(
            '{\n  "filter": "(ApplicationId eq \'YOUR-APP-ID\')",\n  "top": 50\n}'
        )
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self._body_edit.setFont(font)
        self._body_edit.textChanged.connect(self._validate_body)
        body_lay.addWidget(self._body_edit)

        self._body_frame.setVisible(False)  # hidden by default (GET selected)
        root.addWidget(self._body_frame)

        # ── Status bar ────────────────────────────────────────────────────────
        status_row = QHBoxLayout()
        self._status = QLabel("Ready")
        self._status.setStyleSheet(f"color:{_C['subtext']}; font-size:11px;")
        status_row.addWidget(self._status)
        status_row.addStretch()

        self._copy_btn = QPushButton("📋  Copy Result")
        self._copy_btn.setFixedWidth(120)
        self._copy_btn.setStyleSheet(_SECONDARY_BTN)
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy_result)
        status_row.addWidget(self._copy_btn)
        root.addLayout(status_row)

        # ── Output ────────────────────────────────────────────────────────────
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText(
            "JSON results will appear here after running a query…"
        )
        self._output.setStyleSheet(_TEXTEDIT_STYLE)
        output_font = QFont("Consolas", 11)
        output_font.setStyleHint(QFont.Monospace)
        self._output.setFont(output_font)
        root.addWidget(self._output, 1)

        # Style labels inside the widget
        for lbl in self.findChildren(QLabel):
            if not lbl.styleSheet():
                lbl.setStyleSheet(f"color:{_C['subtext']}; font-size:12px;")

    # ─────────────────────────────────────────────────────────────────────────
    # Public
    # ─────────────────────────────────────────────────────────────────────────

    def refresh(self):
        """Page refresh hook — intentionally no auto-query."""
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_preset(self, idx: int):
        data = self._preset_combo.currentData()
        if not data:
            return
        method, api, ep = data
        self._method_combo.setCurrentText(method)
        self._api_combo.setCurrentText(api)
        self._endpoint_input.setText(ep)
        # Set example body for POST presets
        if method == "POST" and ep in (
            "deviceManagement/reports/getAppStatusOverviewReport",
            "deviceManagement/reports/getDeviceInstallStatusReport",
        ):
            self._body_edit.setPlainText(
                json.dumps(
                    {"filter": "(ApplicationId eq 'YOUR-APP-ID')", "top": 50},
                    indent=2,
                )
            )
        # Reset combo to placeholder after applying
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)

    def _on_method_changed(self, method: str):
        is_write = method in ("POST", "PATCH")
        self._body_frame.setVisible(is_write)

        # Paged mode only makes sense for GET
        self._mode_combo.setEnabled(method == "GET")
        if method != "GET":
            self._mode_combo.setCurrentIndex(0)

        # Pre-fill example body when switching to POST/PATCH for the first time
        if is_write and not self._body_edit.toPlainText().strip():
            example = _EXAMPLE_BODIES.get(method, "")
            if example:
                self._body_edit.setPlainText(example)

        # Update Run button colour hint
        color = _METHOD_COLORS.get(method, _C["mauve"])
        self._run_btn.setStyleSheet(
            _BTN_STYLE.format(
                bg=color, fg=_C["base"], border=color,
                hover=color, disabled=_C["overlay0"]
            )
        )

    def _validate_body(self):
        text = self._body_edit.toPlainText().strip()
        if not text:
            self._body_valid_lbl.setText("")
            return
        _green = _C["green"]
        _red   = _C["red"]
        try:
            json.loads(text)
            self._body_valid_lbl.setText(
                f"<span style='color:{_green}'>✓ valid JSON</span>"
            )
        except json.JSONDecodeError as e:
            self._body_valid_lbl.setText(
                f"<span style='color:{_red}'>✗ {e.msg} (line {e.lineno})</span>"
            )

    def _format_body(self):
        text = self._body_edit.toPlainText().strip()
        if not text:
            return
        try:
            parsed = json.loads(text)
            self._body_edit.setPlainText(
                json.dumps(parsed, indent=2, ensure_ascii=False)
            )
        except json.JSONDecodeError as e:
            QMessageBox.warning(
                self, "Invalid JSON",
                f"Cannot format: {e.msg} at line {e.lineno}, column {e.colno}."
            )

    def _run_query(self):
        endpoint = self._endpoint_input.text().strip()
        if not endpoint:
            QMessageBox.information(
                self, "Graph Query Lab",
                "Enter a Graph API endpoint to query."
            )
            return

        method      = self._method_combo.currentText()
        api_version = self._api_combo.currentText()
        collect_all = (
            method == "GET"
            and self._mode_combo.currentText().startswith("Paged")
        )
        max_items = self._max_items.value()

        # Validate body for write methods
        body = None
        if method in ("POST", "PATCH"):
            body_text = self._body_edit.toPlainText().strip()
            if body_text:
                try:
                    body = json.loads(body_text)
                except json.JSONDecodeError as e:
                    QMessageBox.warning(
                        self, "Invalid Request Body",
                        f"The request body is not valid JSON:\n{e.msg} at line {e.lineno}."
                    )
                    return

        self._run_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._status.setText(f"Running {method} query…")
        self._output.clear()

        try:
            from app.graph.client import get_client
            client = get_client()

            if method == "GET":
                if collect_all:
                    data = list(
                        client.get_paged(endpoint, api_version=api_version, max_items=max_items)
                    )
                    payload = {"mode": "paged", "count": len(data), "items": data}
                else:
                    payload = client.get(endpoint, api_version=api_version)

            elif method == "POST":
                payload = client.post(endpoint, json=body, api_version=api_version)

            elif method == "PATCH":
                # GraphClient.patch() if available, else raw _request
                if hasattr(client, "patch"):
                    payload = client.patch(endpoint, json=body, api_version=api_version)
                else:
                    from app.graph.client import GRAPH_BASE_URL_V1, GRAPH_BASE_URL_BETA
                    base = GRAPH_BASE_URL_V1 if api_version == "v1.0" else GRAPH_BASE_URL_BETA
                    url = endpoint if endpoint.startswith("http") else f"{base}/{endpoint}"
                    client._ensure_token()
                    payload = client._request("PATCH", url, json_body=body)

            elif method == "DELETE":
                if hasattr(client, "delete"):
                    payload = client.delete(endpoint, api_version=api_version)
                else:
                    from app.graph.client import GRAPH_BASE_URL_V1, GRAPH_BASE_URL_BETA
                    base = GRAPH_BASE_URL_V1 if api_version == "v1.0" else GRAPH_BASE_URL_BETA
                    url = endpoint if endpoint.startswith("http") else f"{base}/{endpoint}"
                    client._ensure_token()
                    payload = client._request("DELETE", url)

            else:
                payload = {}

            result_text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            self._output.setPlainText(result_text)

            count_hint = ""
            if isinstance(payload, dict) and "count" in payload:
                count_hint = f" — {payload['count']} items"
            elif isinstance(payload, dict) and "value" in payload:
                count_hint = f" — {len(payload['value'])} items"

            _green = _C["green"]
            self._status.setText(
                f"<span style='color:{_green}'>✓ {method} completed{count_hint}</span>"
            )
            self._copy_btn.setEnabled(True)

        except Exception as e:
            _red = _C["red"]
            self._status.setText(
                f"<span style='color:{_red}'>✗ Query failed: {type(e).__name__}</span>"
            )
            QMessageBox.warning(self, "Graph Query Failed", str(e))

        finally:
            self._run_btn.setEnabled(True)

    def _clear_output(self):
        self._output.clear()
        self._status.setText("Ready")
        self._copy_btn.setEnabled(False)

    def _copy_result(self):
        text = self._output.toPlainText()
        if text:
            _green = _C["green"]
            QApplication.clipboard().setText(text)
            self._status.setText(
                f"<span style='color:{_green}'>✓ Copied to clipboard</span>"
            )
