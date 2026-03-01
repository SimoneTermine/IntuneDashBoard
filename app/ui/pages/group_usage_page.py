"""
Group Usage page — show all Intune objects assigned to a given group,
detect dead assignments (group has 0 known members).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTextEdit, QGroupBox,
)
from PySide6.QtCore import Qt

from app.ui.widgets.filterable_table import FilterableTable


CTRL_COLUMNS = [
    ("display_name", "Policy / App", 260),
    ("control_type", "Type", 130),
    ("assignment_intent", "Intent", 80),
    ("platform", "Platform", 90),
    ("last_modified", "Last Modified", 140),
]


class GroupUsagePage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Group Usage")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cba6f7;")
        layout.addWidget(title)

        sub = QLabel(
            "Search for an Entra ID group to see all Intune objects assigned to it "
            "(include and exclude). Dead assignments are flagged when member count = 0."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #a6adc8;")
        layout.addWidget(sub)

        # Group search
        search_row = QHBoxLayout()
        self._group_combo = QComboBox()
        self._group_combo.setEditable(True)
        self._group_combo.setMinimumWidth(340)
        self._group_combo.setPlaceholderText("Search group name or paste group ID…")
        load_btn = QPushButton("↻ Load Groups")
        load_btn.setStyleSheet("background-color: #45475a;")
        load_btn.clicked.connect(self._load_groups)
        analyze_btn = QPushButton("Analyze →")
        analyze_btn.clicked.connect(self._analyze_group)

        search_row.addWidget(QLabel("Group:"))
        search_row.addWidget(self._group_combo)
        search_row.addWidget(load_btn)
        search_row.addWidget(analyze_btn)
        search_row.addStretch()
        layout.addLayout(search_row)

        # Group info banner
        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet(
            "background: #313244; border-radius: 6px; padding: 10px; color: #cdd6f4;"
        )
        self._info_label.hide()
        layout.addWidget(self._info_label)

        # Controls table
        controls_group = QGroupBox("Intune Objects Assigned to This Group")
        cgl = QVBoxLayout(controls_group)
        self._ctrl_table = FilterableTable(CTRL_COLUMNS)
        cgl.addWidget(self._ctrl_table)
        layout.addWidget(controls_group)

    def _load_groups(self):
        from app.analytics.queries import get_groups
        groups = get_groups(limit=500)
        self._group_combo.clear()
        for g in groups:
            label = f"{g['display_name']} ({g['id'][:8]}…)"
            self._group_combo.addItem(label, g["id"])

    def _analyze_group(self):
        group_id = self._group_combo.currentData()
        if not group_id:
            # Try to use the text as a raw group ID
            text = self._group_combo.currentText().strip()
            if len(text) == 36 and text.count("-") == 4:  # looks like a GUID
                group_id = text

        if not group_id:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Group", "Select or enter a group ID.")
            return

        from app.analytics.queries import get_group_controls
        from app.db.database import session_scope
        from app.db.models import Group

        with session_scope() as db:
            group = db.get(Group, group_id)

        controls = get_group_controls(group_id)

        # Banner info
        if group:
            mc = group.member_count
            dynamic = "Dynamic" if group.is_dynamic else "Assigned"
            dead_flag = ""
            if mc is not None and mc == 0:
                dead_flag = "  ⚠️  DEAD ASSIGNMENT — group has 0 members!"
            info = (
                f"<b>{group.display_name}</b> &nbsp; [{dynamic}] &nbsp; "
                f"Members: {'unknown' if mc is None else mc}{dead_flag}"
            )
            self._info_label.setText(info)
            self._info_label.setTextFormat(Qt.RichText)
        else:
            self._info_label.setText(f"Group {group_id} — metadata not in local DB (not synced yet)")
        self._info_label.show()

        self._ctrl_table.load_data(controls)
