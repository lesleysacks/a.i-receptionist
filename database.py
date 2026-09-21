"""Database engine and session lifecycle for the receptionist application.

Supports SQLite (local development/tests) and PostgreSQL (production) via a
single ``DATABASE_URL``. Connection pooling is configured for server databases;
SQLite uses SQLAlchemy's default single-file connection handling.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for every persistence model."""


def _normalize_url(url: str) -> str:
    """Accept the common ``postgres://`` alias used by some hosts."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _create_engine(url: str):
    """Create an engine with settings appropriate to the backend."""
    url = _normalize_url(url)
    if url.startswith("sqlite"):
        # A single-file DB; keep cross-thread access working for the dev server.
        return create_engine(url, connect_args={"check_same_thread": False}, future=True)
    # Server databases (e.g. PostgreSQL): pool with liveness checks and recycling.
    return create_engine(
        url,
        pool_size=_int_env("DB_POOL_SIZE", 5),
        max_overflow=_int_env("DB_MAX_OVERFLOW", 10),
        pool_timeout=_int_env("DB_POOL_TIMEOUT", 30),
        pool_recycle=_int_env("DB_POOL_RECYCLE", 1800),
        pool_pre_ping=True,
        future=True,
    )


DATABASE_URL = _normalize_url(os.getenv("DATABASE_URL", "sqlite:///receptionist.db"))
engine = _create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        """SQLite ignores foreign keys unless enabled per connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_database() -> None:
    """Ensure the schema exists for local development and tests.

    In production (``APP_ENV=production``) the schema is owned by Alembic
    migrations, so this becomes a no-op and never rebuilds or drops tables.
    """
    if os.getenv("APP_ENV", "development").strip().lower() == "production":
        logger.info("APP_ENV=production: skipping create_all; schema is managed by Alembic migrations.")
        return

    import models  # noqa: F401  (registers every table on Base.metadata)

    Base.metadata.create_all(bind=engine)
    _migrate_legacy_conversations()


def _migrate_legacy_conversations() -> None:
    """Upgrade the Step 1 conversation column names on existing SQLite databases."""
    if engine.dialect.name != "sqlite" or "conversations" not in inspect(engine).get_table_names():
        return
    columns = {column["name"] for column in inspect(engine).get_columns("conversations")}
    with engine.begin() as connection:
        if "role" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN role VARCHAR(16)"))
            connection.execute(text("UPDATE conversations SET role = CASE direction WHEN 'inbound' THEN 'user' ELSE 'assistant' END"))
        if "content" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN content TEXT"))
            connection.execute(text("UPDATE conversations SET content = message"))
        if "timestamp" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN timestamp DATETIME"))
            connection.execute(text("UPDATE conversations SET timestamp = created_at"))


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a transaction and guarantee commit/rollback/close behaviour."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
