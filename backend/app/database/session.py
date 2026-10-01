"""SQLAlchemy engine/session management. PostgreSQL in Docker; SQLite fallback for local dev and tests."""
from __future__ import annotations

import logging
import time
from typing import Iterator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("database")


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def configure(database_url: str) -> Engine:
    global _engine, _session_factory
    kwargs = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in database_url or database_url.endswith("sqlite://"):
            kwargs["poolclass"] = StaticPool
    _engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):
        # SQLite ignores foreign keys unless a connection explicitly turns them on. Without this,
        # SQLite-backed dev/test runs would silently allow inserts that PostgreSQL correctly
        # rejects (see analysis_service.create's db.flush() - this pragma is what makes a test
        # actually catch that class of ordering bug instead of passing by accident).
        @event.listens_for(_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def init_db(retries: int = 15, delay: float = 2.0) -> None:
    """Create tables, waiting for the database to accept connections (Postgres may still be starting)."""
    from app.models import orm  # noqa: F401  (register models)

    assert _engine is not None, "configure() must be called first"
    for attempt in range(1, retries + 1):
        try:
            Base.metadata.create_all(_engine)
            return
        except Exception:
            if attempt == retries:
                raise
            logger.warning("database_not_ready attempt=%d", attempt)
            time.sleep(delay)


def new_session() -> Session:
    assert _session_factory is not None, "configure() must be called first"
    return _session_factory()


def get_db() -> Iterator[Session]:
    db = new_session()
    try:
        yield db
    finally:
        db.close()


def ping() -> bool:
    try:
        with new_session() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
