"""
Unit tests for core logic: normalization, drift diff, explainability heuristics.
Run with: pytest tests/
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# DB / config fixtures
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def in_memory_db(tmp_path, monkeypatch):
    """Use an in-memory SQLite DB for every test."""
    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    # Patch config to use temp paths
    import app.config as cfg_module
    cfg_module.APP_DIR = tmp_path
    cfg_module.DB_PATH = tmp_path / "test.db"
    cfg_module.LOGS_DIR = tmp_path / "logs"
    cfg_module.LOGS_DIR.mkdir()
    cfg_module.EXPORT_DIR = tmp_path / "exports"
    cfg_module.EXPORT_DIR.mkdir()
    cfg_module.MSAL_CACHE_PATH = tmp_path / "msal_cache.bin"
    cfg_module.CONFIG_PATH = tmp_path / "config.json"

    # Reset singleton
    from app.config import AppConfig
    AppConfig._instance = None

    from app.db.database import init_db
    import app.db.database as db_module
    db_module._engine = None
    db_module._SessionFactory = None
    init_db(db_file)
    yield
    db_module._engine = None
    db_module._SessionFactory = None


# ─────────────────────────────────────────────────────────────────────────────
# Drift detection tests
# ─────────────────────────────────────────────────────────────────────────────
class TestDriftDetection:

    def _seed_controls(self, db, n=3):
        from app.db.models import Control
        ids = []
        for i in range(n):
            c = Control(
                id=f"ctrl-{i}",
                display_name=f"Policy {i}",
                control_type="compliance_policy",
                last_modified_datetime=datetime.utcnow(),
                synced_at=datetime.utcnow(),
            )
            db.add(c)
            ids.append(f"ctrl-{i}")
        db.flush()
        return ids

    def test_snapshot_creates_items(self):
        from app.db.database import session_scope
        from app.analytics.drift import create_snapshot
        from app.db.models import Snapshot, SnapshotItem

        with session_scope() as db:
            self._seed_controls(db, n=3)

        snap_id = create_snapshot("Test Baseline")

        with session_scope() as db:
            snap = db.get(Snapshot, snap_id)
            assert snap is not None
            assert snap.name == "Test Baseline"
            assert snap.control_count == 3

            items = db.query(SnapshotItem).filter(
                SnapshotItem.snapshot_id == snap_id,
                SnapshotItem.entity_type == "control",
            ).all()
            assert len(items) == 3

    def test_no_drift_same_snapshot(self):
        from app.db.database import session_scope
        from app.analytics.drift import create_snapshot, compare_snapshots

        with session_scope() as db:
            self._seed_controls(db, n=2)

        snap1 = create_snapshot("Snap1")
        snap2 = create_snapshot("Snap2")  # identical state

        report = compare_snapshots(snap1, snap2)
        assert report["summary"]["added"] == 0
        assert report["summary"]["removed"] == 0
        assert report["summary"]["modified"] == 0

    def test_added_control_detected(self):
        from app.db.database import session_scope
        from app.analytics.drift import create_snapshot, compare_snapshots
        from app.db.models import Control

        with session_scope() as db:
            self._seed_controls(db, n=2)

        snap1 = create_snapshot("Before")

        with session_scope() as db:
            db.add(Control(
                id="ctrl-new",
                display_name="New Policy",
                control_type="compliance_policy",
                synced_at=datetime.utcnow(),
            ))

        snap2 = create_snapshot("After")
        report = compare_snapshots(snap1, snap2)
        assert report["summary"]["added"] == 1
        added_ids = [i["entity_id"] for i in report["added"]]
        assert "ctrl-new" in added_ids

    def test_removed_control_detected(self):
        from app.db.database import session_scope
        from app.analytics.drift import create_snapshot, compare_snapshots
        from app.db.models import Control

        with session_scope() as db:
            self._seed_controls(db, n=3)

        snap1 = create_snapshot("Before")

        with session_scope() as db:
            db.query(Control).filter(Control.id == "ctrl-2").delete()

        snap2 = create_snapshot("After")
        report = compare_snapshots(snap1, snap2)
        assert report["summary"]["removed"] == 1
        removed_ids = [i["entity_id"] for i in report["removed"]]
        assert "ctrl-2" in removed_ids

    def test_modified_control_detected(self):
        from app.db.database import session_scope
        from app.analytics.drift import create_snapshot, compare_snapshots
        from app.db.models import Control

        with session_scope() as db:
            self._seed_controls(db, n=2)

        snap1 = create_snapshot("Before")

        with session_scope() as db:
            ctrl = db.get(Control, "ctrl-0")
            ctrl.display_name = "Policy 0 RENAMED"

        snap2 = create_snapshot("After")
        report = compare_snapshots(snap1, snap2)
        assert report["summary"]["modified"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Explainability tests
# ─────────────────────────────────────────────────────────────────────────────
class TestExplainability:

    def _seed_device(self, db, compliance_state="noncompliant"):
        from app.db.models import Device
        d = Device(
            id="dev-001",
            device_name="TEST-PC",
            compliance_state=compliance_state,
            operating_system="Windows",
            synced_at=datetime.utcnow(),
        )
        db.merge(d)
        db.flush()
        return "dev-001"

    def _seed_alldevices_policy(self, db, policy_name="Test Policy", ctrl_type="compliance_policy"):
        from app.db.models import Control, Assignment
        ctrl = Control(
            id="policy-001",
            display_name=policy_name,
            control_type=ctrl_type,
            synced_at=datetime.utcnow(),
        )
        db.merge(ctrl)
        asmt = Assignment(
            id="asmt-001",
            control_id="policy-001",
            target_type="allDevices",
            target_id="allDevices",
            intent="include",
            synced_at=datetime.utcnow(),
        )
        db.merge(asmt)
        db.flush()

    def test_explain_noncompliant_device(self):
        from app.db.database import session_scope
        from app.analytics.explainability import ExplainabilityEngine

        with session_scope() as db:
            self._seed_device(db, "noncompliant")
            self._seed_alldevices_policy(db)

        engine = ExplainabilityEngine()
        result = engine.explain_device("dev-001")

        assert result.device_id == "dev-001"
        assert result.compliance_state == "noncompliant"
        assert len(result.results) >= 1
        # The policy should be found via allDevices
        reasons = [r.reason_code for r in result.results]
        assert any("STATUS_NONCOMPLIANT" in rc or "STATUS_UNKNOWN" in rc for rc in reasons)

    def test_explain_compliant_device(self):
        from app.db.database import session_scope
        from app.analytics.explainability import ExplainabilityEngine

        with session_scope() as db:
            self._seed_device(db, "compliant")
            self._seed_alldevices_policy(db)

        engine = ExplainabilityEngine()
        result = engine.explain_device("dev-001")
        assert result.compliance_state == "compliant"
        reasons = [r.reason_code for r in result.results]
        assert any("STATUS_COMPLIANT" in rc or "STATUS_UNKNOWN" in rc for rc in reasons)

    def test_excluded_group_flagged(self):
        from app.db.database import session_scope
        from app.db.models import Control, Assignment, DeviceGroupMembership, Group
        from app.analytics.explainability import ExplainabilityEngine

        with session_scope() as db:
            self._seed_device(db, "noncompliant")

            # Create group and put device in it
            db.merge(Group(id="grp-001", display_name="ExcludeGroup", synced_at=datetime.utcnow()))
            db.merge(DeviceGroupMembership(device_id="dev-001", group_id="grp-001"))

            ctrl = Control(id="policy-002", display_name="Excluded Policy",
                           control_type="compliance_policy", synced_at=datetime.utcnow())
            db.merge(ctrl)
            asmt = Assignment(id="asmt-002", control_id="policy-002",
                              target_type="group", target_id="grp-001",
                              intent="exclude", synced_at=datetime.utcnow())
            db.merge(asmt)

        engine = ExplainabilityEngine()
        result = engine.explain_device("dev-001")
        excluded = [r for r in result.results if r.intent == "exclude"]
        assert len(excluded) == 1
        assert excluded[0].reason_code == "TARGETING_EXCLUDED"

    def test_conflict_detection_same_category(self):
        from app.analytics.explainability import ExplainabilityEngine, ExplainResult

        engine = ExplainabilityEngine()
        # Feed two results with "bitlocker" in the name
        from app.analytics.explainability import ExplainResult
        results = [
            ExplainResult("c1", "BitLocker Corporate", "config_policy", "applied", "STATUS_UNKNOWN", ""),
            ExplainResult("c2", "BitLocker Strict", "config_policy", "applied", "STATUS_UNKNOWN", ""),
        ]
        conflicts = engine._detect_conflicts(results)
        assert len(conflicts) >= 1
        assert any(c.conflict_type == "same_category" for c in conflicts)

    def test_device_not_found_raises(self):
        from app.analytics.explainability import ExplainabilityEngine
        engine = ExplainabilityEngine()
        with pytest.raises(ValueError, match="not found"):
            engine.explain_device("nonexistent-device-id")


# ─────────────────────────────────────────────────────────────────────────────
# Graph client tests (mocked)
# ─────────────────────────────────────────────────────────────────────────────
class TestGraphClient:

    def test_get_paged_follows_nextlink(self):
        from app.graph.client import GraphClient

        pages = [
            {"value": [{"id": "a"}, {"id": "b"}], "@odata.nextLink": "https://graph/next"},
            {"value": [{"id": "c"}]},
        ]
        call_count = 0

        def mock_request(method, url, params=None, json_body=None, retry_on_401=True):
            nonlocal call_count
            result = pages[call_count]
            call_count += 1
            return result

        client = GraphClient.__new__(GraphClient)
        client._token = "fake_token"
        client._session = MagicMock()
        client._request = mock_request

        items = list(client.get_paged("https://graph/start"))
        assert items == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        assert call_count == 2

    def test_rate_limit_retry(self):
        """Test that 429 is handled via sleep+retry."""
        import time
        from app.graph.client import GraphClient

        responses = []
        # First call: 429
        r429 = MagicMock()
        r429.status_code = 429
        r429.headers = {"Retry-After": "1"}
        r429.ok = False
        # Second call: 200
        r200 = MagicMock()
        r200.status_code = 200
        r200.ok = True
        r200.json.return_value = {"value": [{"id": "x"}]}
        responses.extend([r429, r200])

        session = MagicMock()
        session.request.side_effect = responses

        client = GraphClient.__new__(GraphClient)
        client._token = "fake"
        client._session = session

        with patch("time.sleep") as mock_sleep:
            result = client._request("GET", "https://graph/test")

        assert result == {"value": [{"id": "x"}]}
        mock_sleep.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Demo data tests
# ─────────────────────────────────────────────────────────────────────────────
class TestDemoData:

    def test_demo_load(self):
        from app.demo.demo_data import load_demo_data
        from app.analytics.queries import get_overview_kpis

        count = load_demo_data()
        assert count > 0

        kpis = get_overview_kpis()
        assert kpis["total_devices"] > 0
        assert kpis["total_controls"] > 0
        assert kpis["total_apps"] > 0

    def test_demo_devices_have_required_fields(self):
        from app.demo.demo_data import load_demo_data
        from app.analytics.queries import get_devices

        load_demo_data()
        devices = get_devices()
        assert len(devices) > 0
        for d in devices:
            assert "id" in d
            assert "device_name" in d
            assert "compliance_state" in d

    def test_demo_compliance_breakdown(self):
        from app.demo.demo_data import load_demo_data
        from app.analytics.queries import get_compliance_breakdown

        load_demo_data()
        breakdown = get_compliance_breakdown()
        assert len(breakdown) > 0
        total = sum(b["count"] for b in breakdown)
        assert total > 0


# ─────────────────────────────────────────────────────────────────────────────
# CSV export tests
# ─────────────────────────────────────────────────────────────────────────────
class TestExport:

    def test_csv_export_creates_file(self, tmp_path, monkeypatch):
        import app.config as cfg_module
        cfg_module.EXPORT_DIR = tmp_path / "exports"
        cfg_module.EXPORT_DIR.mkdir()
        # Reset AppConfig singleton
        from app.config import AppConfig
        AppConfig._instance = None
        AppConfig._data = {}

        from app.export.csv_exporter import export_csv
        data = [
            {"name": "Test Device", "state": "compliant", "os": "Windows"},
            {"name": "Device 2", "state": "noncompliant", "os": "iOS"},
        ]
        path = export_csv(data, "test_export.csv")
        assert path.endswith("test_export.csv")

        import os
        assert os.path.exists(path)
        with open(path) as f:
            content = f.read()
        assert "Test Device" in content
        assert "noncompliant" in content

    def test_json_export(self, tmp_path, monkeypatch):
        import app.config as cfg_module
        cfg_module.EXPORT_DIR = tmp_path / "exports"
        cfg_module.EXPORT_DIR.mkdir()
        from app.config import AppConfig
        AppConfig._instance = None

        from app.export.csv_exporter import export_json
        data = {"key": "value", "items": [1, 2, 3]}
        path = export_json(data, "test.json")
        import json, os
        assert os.path.exists(path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["key"] == "value"
