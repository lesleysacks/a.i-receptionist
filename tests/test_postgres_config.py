"""Database configuration: URL normalization and backend-appropriate pooling."""

from __future__ import annotations

from sqlalchemy.pool import QueuePool

import database
from database import (
    DEFAULT_DB_CONNECT_TIMEOUT,
    DEFAULT_DB_POOL_TIMEOUT,
    _create_engine,
    _normalize_url,
    postgres_connect_args,
)


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


def test_postgres_connect_timeout_is_independent_of_pool_timeout(monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "4")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "7")
    captured = {}
    real = database.create_engine

    def wrapping(url, **kwargs):
        captured["kwargs"] = kwargs
        return real(url, **kwargs)

    monkeypatch.setattr(database, "create_engine", wrapping)
    engine = _create_engine("postgresql://u:p@localhost:5432/db")
    try:
        assert captured["kwargs"]["pool_timeout"] == 7
        assert captured["kwargs"]["connect_args"] == {"connect_timeout": 4}
        assert captured["kwargs"]["pool_pre_ping"] is True
        assert engine.pool._timeout == 7
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_postgres_connect_timeout_defaults_and_rejects_zero(monkeypatch):
    monkeypatch.delenv("DB_CONNECT_TIMEOUT", raising=False)
    assert postgres_connect_args() == {"connect_timeout": DEFAULT_DB_CONNECT_TIMEOUT}
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "0")
    assert postgres_connect_args()["connect_timeout"] == DEFAULT_DB_CONNECT_TIMEOUT
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "not-a-number")
    assert postgres_connect_args()["connect_timeout"] == DEFAULT_DB_CONNECT_TIMEOUT
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "5")
    assert postgres_connect_args()["connect_timeout"] == 5


def test_sqlite_engine_does_not_receive_postgres_connect_timeout(monkeypatch):
    captured = {}
    real = database.create_engine

    def wrapping(url, **kwargs):
        captured["kwargs"] = kwargs
        return real(url, **kwargs)

    monkeypatch.setattr(database, "create_engine", wrapping)
    engine = _create_engine("sqlite:///:memory:")
    try:
        assert captured["kwargs"]["connect_args"] == {"check_same_thread": False}
        assert "pool_timeout" not in captured["kwargs"]
        assert "pool_pre_ping" not in captured["kwargs"]
    finally:
        engine.dispose()


def test_postgres_pool_timeout_default_unchanged(monkeypatch):
    monkeypatch.delenv("DB_POOL_TIMEOUT", raising=False)
    captured = {}
    real = database.create_engine

    def wrapping(url, **kwargs):
        captured["kwargs"] = kwargs
        return real(url, **kwargs)

    monkeypatch.setattr(database, "create_engine", wrapping)
    engine = _create_engine("postgresql://u:p@localhost:5432/db")
    try:
        assert captured["kwargs"]["pool_timeout"] == DEFAULT_DB_POOL_TIMEOUT
    finally:
        engine.dispose()
