"""
Database initialization and session factory.
Uses SQLAlchemy 2.x with SQLite.

v1.2.2: Added migration to drop and recreate device_app_statuses table —
        the old schema had a FK constraint on device_id which caused all
        insert attempts to fail silently (Graph returns AAD Device IDs,
        not Intune Managed Device IDs).
"""

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionFactory = None


def init_db(db_path: str | None = None):
    """Initialize the database engine, run migrations, and create all tables."""
    global _engine, _SessionFactory

    if db_path is None:
        from app.config import AppConfig
        db_path = AppConfig().db_path

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
        echo=False,
    )

    @event.listens_for(_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    _migrate_db(_engine)

    Base.metadata.create_all(_engine)
    _SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    logger.info(f"Database initialized at: {db_path}")


def _get_columns(engine, table_name: str) -> set[str]:
    """Return column names for a table, or empty set if table doesn't exist."""
    try:
        insp = inspect(engine)
        if table_name not in insp.get_table_names():
            return set()
        return {col["name"] for col in insp.get_columns(table_name)}
    except Exception as e:
        logger.debug(f"_get_columns({table_name}) failed: {e}")
        return set()


def _table_has_fk(engine, table_name: str, target_table: str) -> bool:
    """Return True if table has a FK constraint pointing to target_table."""
    try:
        insp = inspect(engine)
        if table_name not in insp.get_table_names():
            return False
        fks = insp.get_foreign_keys(table_name)
        return any(fk.get("referred_table") == target_table for fk in fks)
    except Exception as e:
        logger.debug(f"_table_has_fk({table_name}) failed: {e}")
        return False


def _migrate_db(engine) -> None:
    """
    Run schema migrations for existing databases.
    """
    with engine.begin() as conn:

        # ── outcomes ────────────────────────────────────────────────────────
        # v1.0 schema missing 'status' column — safe to drop (derived data).
        cols = _get_columns(engine, "outcomes")
        if cols and "status" not in cols:
            logger.warning(
                "outcomes: outdated schema detected — dropping and recreating."
            )
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("DROP TABLE IF EXISTS outcomes"))
            conn.execute(text("PRAGMA foreign_keys=ON"))

        # ── device_app_statuses ─────────────────────────────────────────────
        # v1.2.1 and earlier had a FK constraint on device_id → devices.id.
        # This caused every insert to fail silently because Graph returns
        # AAD Device IDs (not Intune Managed Device IDs) in /deviceStatuses.
        # The table is fully derived — safe to drop and recreate.
        if _table_has_fk(engine, "device_app_statuses", "devices"):
            logger.warning(
                "device_app_statuses: FK constraint on device_id detected — "
                "dropping and recreating table. Install status data will be "
                "repopulated on next sync."
            )
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("DROP TABLE IF EXISTS device_app_statuses"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            logger.info("device_app_statuses dropped — will be recreated by create_all()")

        # ── remediations (orphaned from v1.1.x) ─────────────────────────────
        insp = inspect(engine)
        if "remediations" in insp.get_table_names():
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("DROP TABLE IF EXISTS remediations"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            logger.info("remediations table dropped (feature removed in v1.2.1)")

        # ── Additive ALTER TABLE migrations (non-destructive) ───────────────
        _add_column_if_missing(conn, "device_compliance_status",
                               "user_principal_name", "TEXT")
        _add_column_if_missing(conn, "controls", "api_source", "TEXT")
        _add_column_if_missing(conn, "controls", "is_assigned", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "controls", "assignment_count", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "devices", "azure_ad_device_id", "TEXT")
        _add_column_if_missing(conn, "assignments", "raw_json", "TEXT")
        _add_column_if_missing(conn, "assignments", "target_display_name", "TEXT")

    logger.info("Database migration check complete")


def _add_column_if_missing(conn, table: str, column: str, col_type: str) -> None:
    """Add a column if it doesn't already exist. No-op if table doesn't exist."""
    try:
        cols = {
            row[1]
            for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        }
        if cols and column not in cols:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            logger.info(f"Migration: added column {table}.{column}")
    except Exception as e:
        logger.debug(f"_add_column_if_missing({table}.{column}): {e}")


def get_engine():
    if _engine is None:
        init_db()
    return _engine


def get_session() -> Session:
    if _SessionFactory is None:
        init_db()
    return _SessionFactory()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Context manager for a DB session with auto-commit/rollback."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
