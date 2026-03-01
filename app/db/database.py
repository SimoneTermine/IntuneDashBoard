"""
Database initialization and session factory.
Uses SQLAlchemy 2.x with SQLite.
"""

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionFactory = None


def init_db(db_path: str | None = None):
    """Initialize the database engine and create all tables."""
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

    Base.metadata.create_all(_engine)
    _SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    logger.info(f"Database initialized at: {db_path}")


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
