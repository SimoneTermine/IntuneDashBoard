"""
app/collector/sync_engine.py

Sync Engine — orchestrates all collectors and manages sync lifecycle.

Pipeline (v1.2.1):
  1. devices           - device metadata + overall compliance state
  2. compliance_status - per-device per-policy compliance
  3. compliance_policies
  4. config_policies   - config + settings catalog + endpoint security
  5. apps              - app metadata + install status
  6. assignments       - control → group/allDevices assignments
  7. groups            - group metadata
  8. memberships       - user/device → group memberships

Note: Proactive Remediations removed in v1.2.1.
"""

import json
import logging
from datetime import datetime
from typing import Callable, Optional

from app.config import AppConfig
from app.db.database import session_scope
from app.db.models import SyncLog

logger = logging.getLogger(__name__)

MIN_SYNC_INTERVAL_SECONDS = 90


class SyncEvent:
    def __init__(self, stage: str, progress: int, message: str, error: bool = False):
        self.stage = stage
        self.progress = progress
        self.message = message
        self.error = error


class SyncEngine:
    _last_sync_time: Optional[datetime] = None

    def __init__(self, progress_callback: Optional[Callable[[SyncEvent], None]] = None):
        self.progress_callback = progress_callback
        self._running = False
        self._current_log_id: Optional[int] = None

    def _emit(self, stage: str, progress: int, message: str, error: bool = False):
        event = SyncEvent(stage, progress, message, error)
        logger.debug(f"Sync: {stage} {progress}% {message}")
        if self.progress_callback:
            try:
                self.progress_callback(event)
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    def is_running(self) -> bool:
        return self._running

    @classmethod
    def seconds_since_last_sync(cls) -> Optional[float]:
        if cls._last_sync_time is None:
            return None
        return (datetime.utcnow() - cls._last_sync_time).total_seconds()

    def run_sync(self, components: Optional[list] = None, force: bool = False) -> SyncLog:
        if self._running:
            raise RuntimeError("Sync already running")

        if not force:
            elapsed = SyncEngine.seconds_since_last_sync()
            if elapsed is not None and elapsed < MIN_SYNC_INTERVAL_SECONDS:
                remaining = int(MIN_SYNC_INTERVAL_SECONDS - elapsed)
                raise RuntimeError(
                    f"Sync cooldown active — last sync {int(elapsed)}s ago. "
                    f"Wait {remaining}s."
                )

        self._running = True
        sync_log = self._start_log()

        try:
            self._emit("init", 0, "Starting sync...")
            cfg = AppConfig()

            if cfg.demo_mode:
                return self._run_demo_sync(sync_log)

            all_components = components or [
                "devices",
                "compliance_status",
                "compliance_policies",
                "config_policies",
                "apps",
                "assignments",
                "groups",
                "memberships",
            ]
            steps = len(all_components)
            results = {}

            for i, comp in enumerate(all_components):
                base_progress = int((i / steps) * 90)
                self._emit(comp, base_progress, f"Syncing {comp}...")
                try:
                    count = self._sync_component(comp)
                    results[comp] = {"count": count, "status": "ok"}
                    self._emit(comp, base_progress + int(90 / steps),
                               f"{comp}: {count} items synced")
                except Exception as e:
                    logger.error(f"Sync component '{comp}' failed: {e}", exc_info=True)
                    results[comp] = {"count": 0, "status": "error", "error": str(e)}
                    self._emit(comp, base_progress, f"{comp} failed: {e}", error=True)

            SyncEngine._last_sync_time = datetime.utcnow()
            self._emit("done", 100, "Sync complete")
            return self._finish_log(sync_log, "success", results)

        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            self._emit("error", 0, f"Sync failed: {e}", error=True)
            return self._finish_log(sync_log, "failed", {}, error_message=str(e))
        finally:
            self._running = False

    def _sync_component(self, component: str) -> int:
        from app.graph.client import get_client
        client = get_client()

        if component == "devices":
            from app.collector.devices import DeviceCollector
            return DeviceCollector(client).sync_all()
        elif component == "compliance_status":
            from app.collector.compliance_status import ComplianceStatusCollector
            return ComplianceStatusCollector(client).sync_all()
        elif component == "compliance_policies":
            from app.collector.policies import PolicyCollector
            return PolicyCollector(client).sync_compliance_policies()
        elif component == "config_policies":
            from app.collector.policies import PolicyCollector
            return PolicyCollector(client).sync_config_policies()
        elif component == "apps":
            from app.collector.apps import AppCollector
            return AppCollector(client).sync_apps()
        elif component == "assignments":
            from app.collector.policies import PolicyCollector
            return PolicyCollector(client).sync_all_assignments()
        elif component == "groups":
            from app.collector.groups import GroupCollector
            return GroupCollector(client).sync_groups()
        elif component == "memberships":
            from app.collector.memberships import MembershipCollector
            return MembershipCollector(client).sync_all_memberships()

        logger.warning(f"Unknown sync component: {component}")
        return 0

    def _run_demo_sync(self, sync_log: SyncLog) -> SyncLog:
        import time
        from app.demo.demo_data import load_demo_data
        self._emit("demo", 10, "Loading demo data...")
        time.sleep(0.3)
        self._emit("demo", 60, "Inserting demo devices, policies, apps...")
        count = load_demo_data()
        self._emit("demo", 100, f"Demo data loaded: {count} objects")
        SyncEngine._last_sync_time = datetime.utcnow()
        return self._finish_log(sync_log, "success", {"demo": {"count": count, "status": "ok"}})

    def _start_log(self) -> SyncLog:
        with session_scope() as db:
            log = SyncLog(started_at=datetime.utcnow(), status="running")
            db.add(log)
            db.flush()
            self._current_log_id = log.id
            db.expunge(log)
            return log

    def _finish_log(
        self,
        sync_log: SyncLog,
        status: str,
        results: dict,
        error_message: Optional[str] = None,
    ) -> SyncLog:
        with session_scope() as db:
            log = db.get(SyncLog, self._current_log_id)
            if log:
                log.finished_at = datetime.utcnow()
                log.status = status
                log.error_message = error_message
                log.details = json.dumps(results)
                log.details_json = json.dumps(results)
                log.devices_synced = results.get("devices", {}).get("count", 0)
                log.controls_synced = (
                    results.get("compliance_policies", {}).get("count", 0)
                    + results.get("config_policies", {}).get("count", 0)
                )
                log.apps_synced = results.get("apps", {}).get("count", 0)
                db.flush()
                # Expunge before session closes so the object can be returned
                db.expunge(log)
                return log
        return sync_log


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
    return _scheduler


def start_scheduler(sync_callback: Optional[Callable] = None):
    cfg = AppConfig()
    if not cfg.sync_enabled:
        return
    scheduler = get_scheduler()
    if scheduler.running:
        return
    interval = max(cfg.sync_interval_minutes, 5)

    def _scheduled_sync():
        engine = SyncEngine()
        try:
            engine.run_sync(force=True)
            if sync_callback:
                sync_callback()
        except Exception as e:
            logger.error(f"Scheduled sync error: {e}")

    scheduler.add_job(
        _scheduled_sync, "interval", minutes=interval,
        id="intune_sync", replace_existing=True, coalesce=True, max_instances=1,
    )
    scheduler.start()
    logger.info(f"Sync scheduler started (every {interval} min)")


def stop_scheduler():
    scheduler = get_scheduler()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Sync scheduler stopped")
