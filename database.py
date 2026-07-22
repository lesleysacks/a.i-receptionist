"""Database engine and session lifecycle for the receptionist application."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for every persistence model."""


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///receptionist.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_database() -> None:
    """Create tables on first boot.

    SQLAlchemy metadata creation is intentionally idempotent, which provides a
    lightweight migration path for the initial SQLite release.
    """
    from models import business, booking, conversation, customer, faq, knowledge_document, service  # noqa: F401

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
