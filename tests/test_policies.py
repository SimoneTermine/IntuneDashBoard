import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def in_memory_db(tmp_path):
    import app.db.database as db_module

    db_module._engine = None
    db_module._SessionFactory = None
    db_module.init_db(str(tmp_path / "test.db"))
    yield
    db_module._engine = None
    db_module._SessionFactory = None


def _run_sync(monkeypatch, client, components):
    import app.collector.sync_engine as sync_engine
    import app.graph.client as graph_client

    monkeypatch.setattr(
        sync_engine,
        "AppConfig",
        lambda: SimpleNamespace(demo_mode=False),
    )
    monkeypatch.setattr(graph_client, "get_client", lambda: client)
    return sync_engine.SyncEngine().run_sync(components=components, force=True)


def test_compliance_policy_record_failures_report_counts_without_sensitive_logs(
    monkeypatch, caplog
):
    from app.collector.policies import PolicyCollector

    sensitive_values = ("synthetic-policy-id", "synthetic-graph-payload")
    client = Mock()
    client.get_paged.return_value = iter([
        {"id": sensitive_values[0], "displayName": "Good synthetic policy"},
        {"id": "synthetic-failing-policy", "displayName": sensitive_values[1]},
    ])
    original_upsert = PolicyCollector._upsert_control

    def upsert(collector, raw, *args, **kwargs):
        if raw.get("displayName") == sensitive_values[1]:
            raise ValueError(f"{sensitive_values[0]} {sensitive_values[1]}")
        return original_upsert(collector, raw, *args, **kwargs)

    monkeypatch.setattr(PolicyCollector, "_upsert_control", upsert)
    with caplog.at_level(logging.ERROR, logger="app.collector.policies"):
        log = _run_sync(monkeypatch, client, ["compliance_policies"])

    result = json.loads(log.details_json)["compliance_policies"]
    assert log.status == "failed"
    assert result["count"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["error_counts"] == {"compliance_policy_record:ValueError": 1}
    assert all(value not in caplog.text for value in sensitive_values)
    assert all(value not in log.details_json for value in sensitive_values)


def test_policy_request_failure_reports_safe_diagnostic(monkeypatch, caplog):
    sensitive_values = ("synthetic-control-id", "synthetic-tenant-data", "synthetic-raw-body")
    client = Mock()

    def fail_request(*args, **kwargs):
        yield {
            "id": "synthetic-policy-before-page-error",
            "displayName": "Synthetic policy before page error",
        }
        raise RuntimeError(" ".join(sensitive_values))

    client.get_paged.side_effect = fail_request
    with caplog.at_level(logging.ERROR, logger="app.collector.policies"):
        log = _run_sync(monkeypatch, client, ["compliance_policies"])

    result = json.loads(log.details_json)["compliance_policies"]
    assert log.status == "failed"
    assert result["count"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["error_counts"] == {"compliance_policy_request:RuntimeError": 1}
    assert all(value not in caplog.text for value in sensitive_values)
    assert all(value not in log.details_json for value in sensitive_values)


def test_config_component_reports_settings_catalog_request_failure_and_successful_config(
    monkeypatch,
):
    from app.graph.endpoints import DEVICE_CONFIGURATIONS

    client = Mock()

    def get_paged(endpoint, *args, **kwargs):
        if endpoint == DEVICE_CONFIGURATIONS:
            return iter([{
                "id": "synthetic-config-id",
                "displayName": "Synthetic config",
                "@odata.type": "#microsoft.graph.macOSGeneralDeviceConfiguration",
            }])
        raise RuntimeError("synthetic request failure")

    client.get_paged.side_effect = get_paged
    log = _run_sync(monkeypatch, client, ["config_policies"])

    result = json.loads(log.details_json)["config_policies"]
    assert log.status == "failed"
    assert result["count"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["error_counts"] == {
        "settings_catalog_request:RuntimeError": 1,
    }


@pytest.mark.parametrize(
    "odata_type",
    [
        "#microsoft.graph.macOSGeneralDeviceConfiguration",
        "#MICROSOFT.GRAPH.MACOSGENERALDEVICECONFIGURATION",
        "#Microsoft.Graph.MacosGeneralDeviceConfiguration",
    ],
)
def test_infer_platform_recognizes_macos_case_insensitively(odata_type):
    from app.collector.policies import _infer_platform

    assert _infer_platform(odata_type) == "macOS"


def _seed_control_and_assignments():
    from app.db.database import session_scope
    from app.db.models import Assignment, Control

    with session_scope() as db:
        db.add(Control(
            id="synthetic-control",
            display_name="Synthetic control",
            control_type="compliance_policy",
            api_source="v1.0",
        ))
        db.add_all([
            Assignment(
                id="synthetic-existing",
                control_id="synthetic-control",
                target_type="group",
                target_id="synthetic-old-group",
            ),
            Assignment(
                id="synthetic-stale",
                control_id="synthetic-control",
                target_type="group",
                target_id="synthetic-stale-group",
            ),
        ])


def test_assignment_snapshot_upserts_current_and_removes_stale_atomically():
    from app.collector.policies import PolicyCollector
    from app.db.database import session_scope
    from app.db.models import Assignment, Control

    _seed_control_and_assignments()
    client = Mock()
    client.get_all.return_value = [
        {
            "id": "synthetic-existing",
            "target": {
                "@odata.type": "#microsoft.graph.groupAssignmentTarget",
                "groupId": "synthetic-current-group",
            },
        },
        {
            "id": "synthetic-new",
            "target": {
                "@odata.type": "#microsoft.graph.allDevicesAssignmentTarget",
            },
        },
    ]

    count = PolicyCollector(client)._sync_assignments_for(
        "synthetic-control", "compliance_policy", "v1.0"
    )

    assert count == 2
    with session_scope() as db:
        existing = db.get(Assignment, "synthetic-existing")
        assert existing.target_id == "synthetic-current-group"
        assert db.get(Assignment, "synthetic-new").target_type == "allDevices"
        assert db.get(Assignment, "synthetic-stale") is None
        control = db.get(Control, "synthetic-control")
        assert control.assignment_count == 2
        assert control.is_assigned is True


def test_assignment_fetch_failure_preserves_existing_snapshot_without_sensitive_details(
    monkeypatch, caplog
):
    from app.collector.policies import PolicyCollector
    from app.db.database import session_scope
    from app.db.models import Assignment

    _seed_control_and_assignments()
    sensitive_values = ("synthetic-control", "synthetic-tenant-id", "synthetic-graph-body")
    client = Mock()
    client.get_all.side_effect = RuntimeError(" ".join(sensitive_values))

    with caplog.at_level(logging.ERROR, logger="app.collector.policies"):
        log = _run_sync(monkeypatch, client, ["assignments"])

    result = json.loads(log.details_json)["assignments"]
    assert log.status == "failed"
    assert result["failed"] == 1
    assert result["error_counts"] == {"assignment_request:RuntimeError": 1}
    assert all(value not in caplog.text for value in sensitive_values)
    assert all(value not in log.details_json for value in sensitive_values)
    with session_scope() as db:
        assert db.get(Assignment, "synthetic-existing").target_id == "synthetic-old-group"
        assert db.get(Assignment, "synthetic-stale") is not None


def test_assignment_snapshot_does_not_remove_stale_rows_when_response_has_invalid_record():
    from app.collector.policies import PolicyCollector, PolicySyncError
    from app.db.database import session_scope
    from app.db.models import Assignment

    _seed_control_and_assignments()
    client = Mock()
    client.get_all.return_value = [
        {
            "id": "synthetic-current",
            "target": {
                "@odata.type": "#microsoft.graph.allDevicesAssignmentTarget",
            },
        },
        {"target": {}},
    ]

    with pytest.raises(PolicySyncError) as raised:
        PolicyCollector(client)._sync_assignments_for(
            "synthetic-control", "compliance_policy", "v1.0"
        )

    assert raised.value.succeeded_count == 1
    assert raised.value.failed_count == 1
    with session_scope() as db:
        assert db.get(Assignment, "synthetic-current") is not None
        assert db.get(Assignment, "synthetic-stale") is not None


def test_compliance_device_status_method_returns_documented_rows_without_guessing_device_id():
    from app.collector.policies import PolicyCollector
    from app.db.database import session_scope
    from app.db.models import DeviceComplianceStatus

    response = [{
        "id": "synthetic-status",
        "deviceDisplayName": "Synthetic device",
        "deviceModel": "Synthetic model",
        "userName": "Synthetic user",
        "status": "compliant",
        "lastReportedDateTime": "2026-01-01T00:00:00Z",
        "userPrincipalName": "synthetic-user@example.invalid",
    }]
    client = Mock()
    client.get_all.return_value = response

    assert PolicyCollector(client).sync_compliance_device_statuses("synthetic-policy") == response
    with session_scope() as db:
        assert db.get(DeviceComplianceStatus, "synthetic-status") is None
