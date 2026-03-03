"""
app/logging_config.py

Logging configuration — SCCM-style rotating file handler + per-subsystem files.

Log files written to %APPDATA%/IntuneDashboard/logs/:
  intune_dashboard.log   ← everything (root logger)
  ui.log                 ← app.ui.*
  graph.log              ← app.graph.*
  collector.log          ← app.collector.*
  db.log                 ← app.db.*

Rotation behaviour (v1.2.2):
  When a log file reaches 2 MB it is renamed  <name>_<YYYY-MM-DD>.log
  and a fresh  <name>.log  is started — exactly like SCCM/ConfigMgr logs.
  If a dated archive for today already exists, a numeric suffix is appended:
    intune_dashboard_2026-03-03.log
    intune_dashboard_2026-03-03_1.log
    intune_dashboard_2026-03-03_2.log  …
"""

import logging
import logging.handlers
import sys
from datetime import datetime
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

# Maximum log file size before rotation (2 MB — matches SCCM default)
_MAX_LOG_BYTES = 2 * 1024 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# SCCM-style rotating handler
# ─────────────────────────────────────────────────────────────────────────────

class SccmRotatingFileHandler(logging.handlers.BaseRotatingHandler):
    """
    Rotates log files the same way SCCM/ConfigMgr does:

      When the active log reaches maxBytes:
        1. Rename  <stem>.log  →  <stem>_<YYYY-MM-DD>.log
           (if that archive name exists, append _1, _2, … until unique)
        2. Open a fresh  <stem>.log

    Unlike Python's built-in RotatingFileHandler (which produces .log.1, .log.2),
    this creates clearly dated archives and always keeps the active log name clean.
    """

    def __init__(
        self,
        filename: str | Path,
        maxBytes: int = _MAX_LOG_BYTES,
        encoding: str = "utf-8",
    ):
        self.maxBytes = maxBytes
        # BaseRotatingHandler opens the file in 'a' mode immediately
        super().__init__(str(filename), mode="a", encoding=encoding, delay=False)

    # ── BaseRotatingHandler interface ─────────────────────────────────────────

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        """Return True when the file has grown past maxBytes."""
        if self.maxBytes <= 0:
            return False
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)          # seek to end of file
        return self.stream.tell() >= self.maxBytes

    def doRollover(self) -> None:
        """Rename the current log file and open a fresh one."""
        # Close the current stream first
        if self.stream:
            try:
                self.stream.flush()
                self.stream.close()
            except Exception:
                pass
            self.stream = None  # type: ignore[assignment]

        src = Path(self.baseFilename)

        if src.exists():
            date_str = datetime.now().strftime("%Y-%m-%d")
            dst = src.parent / f"{src.stem}_{date_str}{src.suffix}"

            # Avoid collisions: append _1, _2, … until the name is free
            if dst.exists():
                counter = 1
                while True:
                    dst = src.parent / f"{src.stem}_{date_str}_{counter}{src.suffix}"
                    if not dst.exists():
                        break
                    counter += 1

            try:
                src.rename(dst)
            except OSError as exc:
                # On Windows, the file may be briefly locked; log to stderr and continue.
                # The next write will still go to the same (now oversized) file rather
                # than silently discarding log records.
                print(
                    f"[logging] WARNING: could not rotate {src.name} → {dst.name}: {exc}",
                    file=sys.stderr,
                )

        # Open the fresh log file
        self.stream = self._open()


# ─────────────────────────────────────────────────────────────────────────────
# Internal factory
# ─────────────────────────────────────────────────────────────────────────────

def _sccm_handler(path: Path, level: int = logging.DEBUG) -> SccmRotatingFileHandler:
    """Create a configured SccmRotatingFileHandler for *path*."""
    h = SccmRotatingFileHandler(path, maxBytes=_MAX_LOG_BYTES)
    h.setLevel(level)
    h.setFormatter(_FILE_FMT)
    return h


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure application-wide logging.

    Call **once** from main.py before any other import that might log.
    Calling a second time is safe — duplicate handlers are detected and skipped.
    """
    from app.config import LOGS_DIR

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ── Main catch-all file ───────────────────────────────────────────────────
    _attach_if_absent(root, LOGS_DIR / "intune_dashboard.log")

    # ── Console (honours log_level arg) ──────────────────────────────────────
    if not any(isinstance(h, logging.StreamHandler) and
               not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        ch.setFormatter(_CONSOLE_FMT)
        root.addHandler(ch)

    # ── Per-subsystem dedicated files ────────────────────────────────────────
    _add_subsystem("app.ui",        LOGS_DIR / "ui.log")
    _add_subsystem("app.graph",     LOGS_DIR / "graph.log")
    _add_subsystem("app.collector", LOGS_DIR / "collector.log")
    _add_subsystem("app.db",        LOGS_DIR / "db.log")

    # App Ops dedicated log — receives entries from the UI page, the analytics
    # query layer, and the app collector so drill-down / filter / sync issues
    # are all traceable in a single file.
    _add_subsystem("app.ui.pages.app_ops",                 LOGS_DIR / "app_ops.log")
    _add_subsystem("app.analytics.app_monitoring_queries", LOGS_DIR / "app_ops.log")
    _add_subsystem("app.collector.apps",                   LOGS_DIR / "app_ops.log")

    # ── Suppress noisy third-party libraries ─────────────────────────────────
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("msal").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        f"Logging initialised — log dir: {LOGS_DIR}  max size per file: "
        f"{_MAX_LOG_BYTES // 1024 // 1024} MB"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _attach_if_absent(lgr: logging.Logger, path: Path) -> None:
    """Attach a SccmRotatingFileHandler only if one for *path* is not already present."""
    path_str = str(path)
    if any(
        isinstance(h, SccmRotatingFileHandler) and
        getattr(h, "baseFilename", None) == path_str
        for h in lgr.handlers
    ):
        return
    lgr.addHandler(_sccm_handler(path))


def _add_subsystem(logger_name: str, path: Path) -> None:
    """Attach a dedicated rotating file to a named subsystem logger."""
    lgr = logging.getLogger(logger_name)
    _attach_if_absent(lgr, path)
