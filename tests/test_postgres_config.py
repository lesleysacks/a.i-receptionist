"""Database configuration: URL normalization and backend-appropriate pooling."""

from __future__ import annotations

from sqlalchemy.pool import QueuePool

from database import _create_engine, _normalize_url


def test_postgres_scheme_alias_is_normalized():
    assert _normalize_url("postgres://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"
    assert _normalize_url("postgresql://u:p@host/db") == "postgresql://u:p@host/db"
    assert _normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_postgres_engine_uses_connection_pool():
    # Building an engine does not open a connection, so this needs no live server.
    engine = _create_engine("postgresql://u:p@localhost:5432/db")
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_sqlite_engine_does_not_use_server_pool():
    engine = _create_engine("sqlite:///:memory:")
    assert not isinstance(engine.pool, QueuePool)
    engine.dispose()
