import json
import logging
import os
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def in_memory_db(tmp_path):
    import app.db.database as db_module

    db_module._engine = None
    db_module._SessionFactory = None
    db_module.init_db(str(tmp_path / "test.db"))
    yield
    db_module._engine = None
    db_module._SessionFactory = None


def _configure_sync(monkeypatch, client):
    import app.collector.sync_engine as sync_engine
    import app.graph.client as graph_client

    monkeypatch.setattr(
        sync_engine,
        "AppConfig",
        lambda: SimpleNamespace(demo_mode=False),
    )
    monkeypatch.setattr(graph_client, "get_client", lambda: client)


def _run_sync(monkeypatch, components, client, component_results):
    from app.collector.sync_engine import SyncEngine

    _configure_sync(monkeypatch, client)
    engine = SyncEngine()

    def sync_component(component):
        result = component_results[component]
        if isinstance(result, Exception):
            raise result
        return result

    engine._sync_component = sync_component
    return engine.run_sync(components=components, force=True)


def test_successful_device_sync_returns_count_and_persists_device():
    from app.collector.devices import DeviceCollector
    from app.db.database import session_scope
    from app.db.models import Device

    client = Mock()
    client.get_paged.return_value = iter([
        {"id": "synthetic-device-1", "deviceName": "Synthetic device"},
    ])

    count = DeviceCollector(client).sync_all()

    assert count == 1
    with session_scope() as db:
        assert db.get(Device, "synthetic-device-1").device_name == "Synthetic device"


def test_all_successful_components_set_success_status(monkeypatch):
    log = _run_sync(
        monkeypatch,
        ["devices", "groups"],
        Mock(),
        {"devices": 2, "groups": 3},
    )

    assert log.status == "success"
    assert json.loads(log.details_json) == {
        "devices": {"count": 2, "status": "ok"},
        "groups": {"count": 3, "status": "ok"},
    }


@pytest.mark.parametrize(
    ("components", "valid_component_results", "expected_status"),
    [
        (["unknown_component"], {}, "failed"),
        (["unknown_component", "groups"], {"groups": 2}, "partial"),
    ],
)
def test_unknown_component_is_error_with_sanitized_details(
    monkeypatch, components, valid_component_results, expected_status
):
    from app.collector.sync_engine import SyncEngine

    client = Mock()
    _configure_sync(monkeypatch, client)
    engine = SyncEngine()
    actual_sync_component = engine._sync_component

    def sync_component(component):
        if component in valid_component_results:
            return valid_component_results[component]
        return actual_sync_component(component)

    engine._sync_component = sync_component
    log = engine.run_sync(components=components, force=True)

    details = json.loads(log.details_json)
    assert log.status == expected_status
    assert details["unknown_component"] == {
        "count": 0,
        "status": "error",
        "error_type": "ValueError",
    }
    assert log.error_message == (
        "All requested components failed"
        if expected_status == "failed"
        else "One or more components failed"
    )
    assert "tenant" not in log.details_json.lower()
    if "groups" in valid_component_results:
        assert details["groups"] == {"count": 2, "status": "ok"}


def test_partial_device_failures_preserve_success_and_produce_partial_status(
    monkeypatch, caplog
):
    from app.collector.devices import DeviceCollector
    from app.db.database import session_scope
    from app.db.models import Device
    from app.collector.sync_engine import SyncEngine

    sensitive_id = "synthetic-device-secret"
    client = Mock()
    client.get_paged.return_value = iter([
        {"id": "synthetic-device-good", "deviceName": "Good synthetic device"},
        {"id": sensitive_id, "deviceName": "Failing synthetic device"},
    ])
    original_upsert = DeviceCollector._upsert_device

    def upsert(collector, raw):
        if raw["id"] == sensitive_id:
            raise ValueError(f"database failure for {sensitive_id}")
        return original_upsert(collector, raw)

    monkeypatch.setattr(DeviceCollector, "_upsert_device", upsert)
    _configure_sync(monkeypatch, client)
    engine = SyncEngine()
    engine._sync_component = lambda component: (
        DeviceCollector(client).sync_all()
        if component == "devices"
        else 3
    )

    with caplog.at_level(logging.ERROR, logger="app.collector.devices"):
        log = engine.run_sync(components=["devices", "groups"], force=True)

    details = json.loads(log.details_json)
    assert log.status == "partial"
    assert details["devices"] == {
        "count": 1,
        "status": "error",
        "succeeded": 1,
        "failed": 1,
        "record_error_types": {"ValueError": 1},
    }
    assert details["groups"] == {"count": 3, "status": "ok"}
    assert log.devices_synced == 1
    assert sensitive_id not in caplog.text
    assert sensitive_id not in log.details_json
    assert "ValueError" in caplog.text

    with session_scope() as db:
        assert db.get(Device, "synthetic-device-good") is not None
        assert db.get(Device, sensitive_id) is None


def test_all_component_failures_set_failed_and_sanitize_diagnostics(monkeypatch, caplog):
    sensitive_value = "synthetic-tenant-data"
    client = Mock()
    with caplog.at_level(logging.ERROR, logger="app.collector.sync_engine"):
        log = _run_sync(
            monkeypatch,
            ["devices", "groups"],
            client,
            {
                "devices": ValueError(sensitive_value),
                "groups": RuntimeError(sensitive_value),
            },
        )

    details = json.loads(log.details_json)
    assert log.status == "failed"
    assert details["devices"]["status"] == "error"
    assert details["groups"]["status"] == "error"
    assert sensitive_value not in caplog.text
    assert sensitive_value not in log.details_json
    assert log.error_message == "All requested components failed"


def test_paging_error_keeps_successful_writes_and_reports_partial_collection(
    monkeypatch, caplog
):
    from app.collector.devices import DeviceCollector
    from app.db.database import session_scope
    from app.db.models import Device

    sensitive_value = "synthetic-sensitive-paging-detail"

    def paged_devices(*args, **kwargs):
        yield {"id": "synthetic-device-before-page-error"}
        raise RuntimeError(sensitive_value)

    client = Mock()
    client.get_paged.side_effect = paged_devices
    _configure_sync(monkeypatch, client)
    from app.collector.sync_engine import SyncEngine

    engine = SyncEngine()
    engine._sync_component = lambda component: DeviceCollector(client).sync_all()
    with caplog.at_level(logging.ERROR):
        log = engine.run_sync(components=["devices"], force=True)

    details = json.loads(log.details_json)
    assert log.status == "failed"
    assert details["devices"] == {
        "count": 1,
        "status": "error",
        "succeeded": 1,
        "failed": 0,
        "record_error_types": {},
        "paging_error_type": "RuntimeError",
    }
    assert sensitive_value not in caplog.text
    assert sensitive_value not in log.details_json
    with session_scope() as db:
        assert db.get(Device, "synthetic-device-before-page-error") is not None


@pytest.mark.parametrize("status", ["success", "partial", "failed"])
def test_sync_worker_emits_status_string(monkeypatch, status, qapp):
    import app.ui.workers.sync_worker as sync_worker

    class Engine:
        def __init__(self, progress_callback=None):
            pass

        def run_sync(self, *args, **kwargs):
            return SimpleNamespace(status=status)

    monkeypatch.setattr(sync_worker, "SyncEngine", Engine)
    worker = sync_worker.SyncWorker()
    emitted = []
    worker.finished.connect(lambda emitted_status, message: emitted.append((emitted_status, message)))

    worker.run()

    assert emitted == [(status, f"Sync {status}")]


def test_sync_worker_emits_failed_status_for_exceptions(monkeypatch, qapp):
    import app.ui.workers.sync_worker as sync_worker

    class Engine:
        def __init__(self, progress_callback=None):
            pass

        def run_sync(self, *args, **kwargs):
            raise ValueError("sensitive detail")

    monkeypatch.setattr(sync_worker, "SyncEngine", Engine)
    worker = sync_worker.SyncWorker()
    emitted = []
    worker.finished.connect(lambda status, message: emitted.append((status, message)))

    worker.run()

    assert emitted == [("failed", "Sync error (ValueError)")]


def test_device_code_dialog_accepts_status_payload(qapp):
    from PySide6.QtWidgets import QDialog
    from app.ui.workers.sync_worker import SyncWorker

    worker = SyncWorker()
    dialog = QDialog()
    worker.finished.connect(dialog.accept)

    worker.finished.emit("partial", "Sync partial")

    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.mark.parametrize(
    ("status", "warning_title", "refresh_expected"),
    [
        ("success", None, True),
        ("partial", "Sync Partially Complete", True),
        ("failed", "Sync Failed", False),
    ],
)
def test_main_window_handles_sync_status(
    monkeypatch, status, warning_title, refresh_expected, qapp
):
    from app.ui import main_window

    page = SimpleNamespace(refresh=Mock())
    window = SimpleNamespace(
        _sync_widget=SimpleNamespace(set_syncing=Mock()),
        _status_bar=SimpleNamespace(showMessage=Mock()),
        _stack=SimpleNamespace(currentWidget=Mock(return_value=page)),
    )
    warnings = []
    monkeypatch.setattr(
        main_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args[1]),
    )

    main_window.MainWindow._on_sync_finished(window, status, f"Sync {status}")

    assert page.refresh.called is refresh_expected
    assert warnings == ([] if warning_title is None else [warning_title])
    if status == "partial":
        window._status_bar.showMessage.assert_called_once_with(
            "Sync partially complete — Sync partial"
        )


def test_overview_uses_warning_icon_for_partial_status(monkeypatch, qapp):
    from app.ui.pages.overview_page import OverviewPage
    import app.analytics.queries as queries

    monkeypatch.setattr(queries, "get_overview_kpis", lambda: {
        "total_devices": 1,
        "compliant": 1,
        "noncompliant": 0,
        "unknown": 0,
        "total_controls": 0,
        "total_apps": 0,
    })
    monkeypatch.setattr(queries, "get_compliance_breakdown", lambda: {})
    monkeypatch.setattr(queries, "get_os_breakdown", lambda: {})
    monkeypatch.setattr(queries, "get_recent_sync_logs", lambda limit: [{
        "started_at": datetime(2026, 1, 1),
        "status": "partial",
        "devices_synced": 1,
        "error_message": "One or more components failed",
    }])

    page = OverviewPage()
    page._sync_log_text.clear()
    page.refresh()

    assert "⚠ PARTIAL" in page._sync_log_text.toPlainText()
