"""
Database initialization and session factory.
Uses SQLAlchemy 2.x with SQLite.

On startup, _migrate_db() checks for schema changes in tables that have
been restructured across versions and performs the minimum ALTER/DROP+CREATE
needed to bring the existing DB up to date without losing data.

Tables that are safe to drop+recreate (fully derived from Graph data):
  - outcomes      (rebuilt by compliance_status collector on every sync)
  - remediations  (rebuilt by remediations collector on every sync)
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

    # Enable WAL mode and foreign keys
    @event.listens_for(_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    # Migrate schema before create_all so old tables are fixed first
    _migrate_db(_engine)

    Base.metadata.create_all(_engine)
    _SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    logger.info(f"Database initialized at: {db_path}")


def _get_columns(engine, table_name: str) -> set[str]:
    """Return the set of column names for a table, or empty set if table doesn't exist."""
    try:
        insp = inspect(engine)
        if table_name not in insp.get_table_names():
            return set()
        return {col["name"] for col in insp.get_columns(table_name)}
    except Exception as e:
        logger.debug(f"_get_columns({table_name}) failed: {e}")
        return set()


def _migrate_db(engine) -> None:
    """
    Run schema migrations for existing databases.

    Strategy per table:
      - outcomes:     derived data → drop and recreate if schema is outdated
      - remediations: new table → create_all handles it; no migration needed
      - drift_reports: new table → create_all handles it; no migration needed
    """
    with engine.begin() as conn:

        # ── outcomes ────────────────────────────────────────────────────────
        # v1.0.0 schema: id, device_id, control_id, applies (bool), reason_code,
        #                reason_detail, computed_at
        # v1.1.0 schema: id, control_id, device_id, status (str), reason_code,
        #                reason_detail, error_code, source, raw_json, synced_at
        #
        # 'outcomes' is fully derived — safe to drop+recreate.
        cols = _get_columns(engine, "outcomes")
        if cols and "status" not in cols:
            logger.warning(
                "outcomes table has outdated schema (missing 'status' column). "
                "Dropping and recreating — all data will be rebuilt on next sync."
            )
            # Disable FK constraints temporarily so the drop succeeds
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("DROP TABLE IF EXISTS outcomes"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            logger.info("outcomes table dropped — will be recreated by create_all()")

        # ── Add missing columns to existing tables (non-destructive) ────────
        # These are additive changes that don't require recreating the table.

        # device_compliance_status: add user_principal_name if missing (v1.0 → v1.1)
        _add_column_if_missing(conn, "device_compliance_status", "user_principal_name", "TEXT")

        # controls: add api_source if missing
        _add_column_if_missing(conn, "controls", "api_source", "TEXT")
        _add_column_if_missing(conn, "controls", "is_assigned", "INTEGER DEFAULT 0")

        # devices: add azure_ad_device_id if missing
        _add_column_if_missing(conn, "devices", "azure_ad_device_id", "TEXT")

    logger.info("Database migration check complete")


def _add_column_if_missing(conn, table: str, column: str, col_type: str) -> None:
    """Add a column to a table if it doesn't already exist. No-op if table doesn't exist."""
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
    """Return a new database session. Caller must close it."""
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
