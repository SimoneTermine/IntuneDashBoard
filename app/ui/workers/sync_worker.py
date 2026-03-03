"""
Qt background worker for sync operations.
Uses QThread so the UI stays responsive.

v1.2.6: SyncWorker gains device_code_ready signal so that when a sync
        triggers a device code flow (token expired / missing scopes),
        the main window can show the same sign-in dialog used by
        Settings -> Test Graph Connection.
"""

from PySide6.QtCore import QThread, Signal

from app.collector.sync_engine import SyncEngine, SyncEvent


class SyncWorker(QThread):
    """Runs a sync in a background thread, emits progress signals."""

    progress          = Signal(str, int, str, bool)  # stage, percent, message, is_error
    finished          = Signal(bool, str)             # success, message
    device_code_ready = Signal(str, str)              # user_code, verification_uri

    def __init__(self, components=None, parent=None):
        super().__init__(parent)
        self.components = components

    def run(self):
        def on_progress(event: SyncEvent):
            self.progress.emit(event.stage, event.progress, event.message, event.error)

        def on_device_code(flow):
            self.device_code_ready.emit(
                flow.get("user_code", ""),
                flow.get("verification_uri", ""),
            )

        engine = SyncEngine(progress_callback=on_progress)
        try:
            log = engine.run_sync(
                self.components,
                device_code_callback=on_device_code,
            )
            self.finished.emit(log.status == "success", f"Sync {log.status}")
        except RuntimeError as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, f"Sync error: {e}")


class AuthWorker(QThread):
    """Runs device code authentication in background."""

    device_code_ready = Signal(str, str)  # user_code, verification_uri
    finished          = Signal(bool, str) # success, message

    def run(self):
        from app.graph.client import get_client, reset_client
        reset_client()
        client = get_client()

        def on_device_code(flow):
            self.device_code_ready.emit(
                flow.get("user_code", ""),
                flow.get("verification_uri", ""),
            )

        try:
            client.authenticate(device_code_callback=on_device_code)
            self.finished.emit(True, "Authentication successful")
        except Exception as e:
            self.finished.emit(False, str(e))


class GraphWorker(QThread):
    """Generic background Graph query worker."""

    result = Signal(object)
    error  = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.result.emit(result)
        except Exception as e:
            self.error.emit(str(e))
