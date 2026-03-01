"""
Intune Dashboard - Main Entry Point
A local desktop application to monitor and explore Microsoft Intune data via Graph API.
"""

import sys
import os

# Ensure app directory is in path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app.logging_config import setup_logging
from app.config import AppConfig

# Setup logging before anything else
setup_logging()

import logging
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Intune Dashboard")
    
    # Late import to allow logging setup first
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QCoreApplication
    from PySide6.QtGui import QIcon
    from app.db.database import init_db
    from app.ui.main_window import MainWindow

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    
    app = QApplication(sys.argv)
    app.setApplicationName("Intune Dashboard")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("IntuneTools")
    app.setOrganizationDomain("intunetools.local")
    
    # Apply dark/light theme stylesheet
    _apply_stylesheet(app)

    # Initialize database
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
    """Apply a professional dark stylesheet."""
    stylesheet = """
    QMainWindow {
        background-color: #1e1e2e;
    }
    QWidget {
        background-color: #1e1e2e;
        color: #cdd6f4;
        font-family: "Segoe UI", Arial, sans-serif;
        font-size: 13px;
    }
    QFrame#Sidebar {
        background-color: #181825;
        border-right: 1px solid #313244;
    }
    QPushButton#SidebarButton {
        text-align: left;
        padding: 10px 16px;
        border: none;
        border-radius: 6px;
        background-color: transparent;
        color: #a6adc8;
        font-size: 13px;
    }
    QPushButton#SidebarButton:hover {
        background-color: #313244;
        color: #cdd6f4;
    }
    QPushButton#SidebarButton:checked {
        background-color: #45475a;
        color: #cba6f7;
        font-weight: bold;
    }
    QPushButton {
        background-color: #7c3aed;
        color: #ffffff;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #6d28d9;
    }
    QPushButton:pressed {
        background-color: #5b21b6;
    }
    QPushButton:disabled {
        background-color: #45475a;
        color: #6c7086;
    }
    QPushButton#DangerButton {
        background-color: #f38ba8;
        color: #1e1e2e;
    }
    QPushButton#SuccessButton {
        background-color: #a6e3a1;
        color: #1e1e2e;
    }
    QTableWidget, QTableView {
        background-color: #181825;
        alternate-background-color: #1e1e2e;
        border: 1px solid #313244;
        border-radius: 6px;
        gridline-color: #313244;
        selection-background-color: #45475a;
    }
    QHeaderView::section {
        background-color: #313244;
        color: #cba6f7;
        padding: 6px 8px;
        border: none;
        border-right: 1px solid #45475a;
        font-weight: bold;
    }
    QLineEdit, QComboBox, QSpinBox {
        background-color: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 6px;
        padding: 6px 10px;
    }
    QLineEdit:focus, QComboBox:focus {
        border: 1px solid #cba6f7;
    }
    QComboBox::drop-down {
        border: none;
        padding-right: 8px;
    }
    QTabWidget::pane {
        border: 1px solid #313244;
        border-radius: 6px;
    }
    QTabBar::tab {
        background-color: #313244;
        color: #a6adc8;
        padding: 8px 16px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #45475a;
        color: #cba6f7;
        font-weight: bold;
    }
    QScrollBar:vertical {
        background-color: #1e1e2e;
        width: 8px;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical {
        background-color: #45475a;
        border-radius: 4px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background-color: #585b70;
    }
    QGroupBox {
        border: 1px solid #313244;
        border-radius: 6px;
        margin-top: 10px;
        padding-top: 10px;
        color: #cba6f7;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }
    QProgressBar {
        background-color: #313244;
        border: none;
        border-radius: 4px;
        text-align: center;
        color: #cdd6f4;
        height: 8px;
    }
    QProgressBar::chunk {
        background-color: #cba6f7;
        border-radius: 4px;
    }
    QLabel#KpiCard {
        background-color: #313244;
        border-radius: 8px;
        padding: 12px;
    }
    QTextEdit {
        background-color: #181825;
        color: #cdd6f4;
        border: 1px solid #313244;
        border-radius: 6px;
        font-family: "Consolas", monospace;
        font-size: 12px;
    }
    QSplitter::handle {
        background-color: #313244;
        width: 1px;
    }
    QToolBar {
        background-color: #181825;
        border-bottom: 1px solid #313244;
        spacing: 4px;
        padding: 4px;
    }
    QStatusBar {
        background-color: #181825;
        color: #a6adc8;
        border-top: 1px solid #313244;
    }
    QDialog {
        background-color: #1e1e2e;
    }
    QCheckBox {
        color: #cdd6f4;
        spacing: 8px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 2px solid #45475a;
        border-radius: 3px;
        background-color: #313244;
    }
    QCheckBox::indicator:checked {
        background-color: #cba6f7;
        border-color: #cba6f7;
    }
    """
    app.setStyleSheet(stylesheet)


if __name__ == "__main__":
    main()
