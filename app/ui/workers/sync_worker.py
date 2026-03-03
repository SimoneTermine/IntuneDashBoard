"""
Qt background worker for sync operations.
Uses QThread so the UI stays responsive.

v1.2.2:
  SyncWorker now emits device_code_ready(user_code, verification_uri) when
  authentication is needed during a sync (e.g. token missing / scope mismatch).
  MainWindow connects this signal to show the sign-in dialog.
"""

from PySide6.QtCore import QThread, Signal

from app.collector.sync_engine import SyncEngine, SyncEvent


class SyncWorker(QThread):
    """Runs a sync in a background thread, emits progress signals."""

    progress         = Signal(str, int, str, bool)  # stage, percent, message, is_error
    finished         = Signal(bool, str)             # success, message
    device_code_ready = Signal(str, str)             # user_code, verification_uri  ← NEW

    def __init__(self, components=None, parent=None):
        super().__init__(parent)
        self.components = components

    def run(self):
        def on_progress(event: SyncEvent):
            self.progress.emit(event.stage, event.progress, event.message, event.error)

        # ── Register device-code callback on the GraphClient singleton ────────
        # If the token is missing or scopes changed, get_token() will call this
        # callback with the flow dict so we can emit the Qt signal and show a
        # dialog in the main thread.
        def on_device_code(flow: dict):
            self.device_code_ready.emit(
                flow.get("user_code", ""),
                flow.get("verification_uri", "https://microsoft.com/devicelogin"),
            )

        try:
            from app.graph.client import get_client
            get_client().set_device_code_callback(on_device_code)
        except Exception:
            pass  # client not yet initialised — will be created during sync

        engine = SyncEngine(progress_callback=on_progress)
        try:
            log = engine.run_sync(self.components)
            self.finished.emit(log.status == "success", f"Sync {log.status}")
        except RuntimeError as e:
            self.finished.emit(False, str(e))
        except Exception as e:
            self.finished.emit(False, f"Sync error: {e}")

        # Clear the callback after sync so it doesn't linger
        try:
            from app.graph.client import get_client
            get_client().set_device_code_callback(None)
        except Exception:
            pass


class AuthWorker(QThread):
    """Runs device code authentication in background (used by Settings page)."""

    device_code_ready = Signal(str, str)  # user_code, verification_uri
    finished          = Signal(bool, str) # success, message

    def run(self):
        from app.graph.client import get_client, reset_client
        reset_client()
        client = get_client()

        def on_device_code(flow):
            self.device_code_ready.emit(
                flow.get("user_code", ""),
                flow.get("verification_uri", "https://microsoft.com/devicelogin"),
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
