"""
Intune Dashboard — Main Entry Point

A local desktop application to monitor and explore Microsoft Intune data
via the Microsoft Graph API.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app.logging_config import setup_logging
from app.config import AppConfig

# Logging must be configured before any import that could log
setup_logging()

import logging
logger = logging.getLogger(__name__)


def main():
    from app.version import __version__, APP_NAME

    logger.info(f"Starting {APP_NAME} {__version__}")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QCoreApplication
    from app.db.database import init_db
    from app.ui.main_window import MainWindow

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("IntuneTools")
    app.setOrganizationDomain("intunetools.local")

    _apply_stylesheet(app)

    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}", exc_info=True)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Fatal Error", f"Failed to initialize database:\n{e}")
        sys.exit(1)

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    logger.info(f"Application exiting with code {exit_code}")
    sys.exit(exit_code)


def _apply_stylesheet(app):
    """Apply the Catppuccin Mocha dark stylesheet."""
    app.setStyleSheet("""
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Inter", "SF Pro Text", sans-serif;
    font-size: 13px;
}
QFrame#Sidebar {
    background-color: #181825;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover  { background-color: #45475a; }
QPushButton:pressed { background-color: #585b70; }
QPushButton#SidebarButton {
    text-align: left;
    border: none;
    border-radius: 6px;
    margin: 1px 6px;
    padding: 8px 10px;
}
QPushButton#SidebarButton:hover   { background-color: #313244; }
QPushButton#SidebarButton:checked { background-color: #45475a; color: #cba6f7; }
QPushButton#DangerButton {
    background-color: #3b1c2a;
    color: #f38ba8;
    border-color: #f38ba8;
}
QPushButton#DangerButton:hover { background-color: #5a1c2c; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 5px 8px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border-color: #cba6f7;
}
QTableWidget, QTableView {
    background-color: #1e1e2e;
    alternate-background-color: #252535;
    gridline-color: #313244;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 6px;
    selection-background-color: #45475a;
}
QHeaderView::section {
    background-color: #181825;
    color: #a6adc8;
    border: none;
    padding: 6px 8px;
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 0.5px;
}
QTabWidget::pane { border: 1px solid #313244; border-radius: 6px; }
QTabBar::tab {
    background-color: #181825;
    color: #6c7086;
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #cba6f7; border-bottom-color: #cba6f7; }
QTabBar::tab:hover { color: #cdd6f4; }
QGroupBox {
    border: 1px solid #313244;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
    color: #a6adc8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
QScrollBar:vertical {
    background: #181825;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #181825; color: #6c7086; font-size: 11px; }
""")


if __name__ == "__main__":
    main()
