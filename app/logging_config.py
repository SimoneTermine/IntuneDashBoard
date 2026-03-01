"""
app/logging_config.py

Logging configuration — rotating file handler (main) + per-subsystem files.

Log files written to %APPDATA%/IntuneDashboard/logs/:
  intune_dashboard.log   ← everything (root logger)
  ui.log                 ← app.ui.*
  graph.log              ← app.graph.*
  collector.log          ← app.collector.*
  db.log                 ← app.db.*
  context_menus.log      ← app.ui.widgets.context_menus (right-click actions)
"""

import logging
import logging.handlers
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Formatters
# ─────────────────────────────────────────────────────────────────────────────

_FILE_FMT = logging.Formatter(
    "%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_CONSOLE_FMT = logging.Formatter(
    "[%(levelname)-8s] %(name)s - %(message)s"
)


def _rotating(path: Path, level: int = logging.DEBUG) -> logging.handlers.RotatingFileHandler:
    h = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    h.setLevel(level)
    h.setFormatter(_FILE_FMT)
    return h


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(log_level: str = "INFO"):
    """
    Configure application logging.

    Call once from main.py before any other import that might log.
    """
    from app.config import LOGS_DIR

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ── Main catch-all file ───────────────────────────────────────────────────
    root.addHandler(_rotating(LOGS_DIR / "intune_dashboard.log"))

    # ── Console (respects log_level arg) ─────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    ch.setFormatter(_CONSOLE_FMT)
    root.addHandler(ch)

    # ── Per-subsystem files ───────────────────────────────────────────────────
    _add_subsystem("app.ui",                    LOGS_DIR / "ui.log")
    _add_subsystem("app.graph",                 LOGS_DIR / "graph.log")
    _add_subsystem("app.collector",             LOGS_DIR / "collector.log")
    _add_subsystem("app.db",                    LOGS_DIR / "db.log")

    # Suppress noisy third-party libs
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("msal").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        f"Logging initialised — main log: {LOGS_DIR / 'intune_dashboard.log'}"
    )


def _add_subsystem(logger_name: str, path: Path):
    """Attach a dedicated rotating file to a named logger (propagate stays True)."""
    lgr = logging.getLogger(logger_name)
    # Avoid duplicate handlers if setup_logging() is called more than once
    if any(isinstance(h, logging.handlers.RotatingFileHandler) and
           getattr(h, 'baseFilename', None) == str(path)
           for h in lgr.handlers):
        return
    lgr.addHandler(_rotating(path))
