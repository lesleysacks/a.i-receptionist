"""Bounded database and Redis timeouts for readiness (and shared Redis clients)."""

from __future__ import annotations

import socket
import threading
import time

import pytest
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as SATimeout
from sqlalchemy.pool import QueuePool

from apex_receptionist.services import jobs as jobs_mod
from database import _create_engine
from services.jobs import get_redis_connection, redis_client_kwargs, redis_is_reachable


class _SilentTCPServer:
    """Accept TCP connections and never speak. Forces handshake/read timeouts."""

    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self._conns: list[socket.socket] = []

        def _hold():
            self.sock.settimeout(0.2)
            while not self._stop:
                try:
                    conn, _addr = self.sock.accept()
                    conn.settimeout(None)
                    self._conns.append(conn)
                except socket.timeout:
                    continue
                except OSError:
                    break

        self._thread = threading.Thread(target=_hold, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop = True
        for conn in self._conns:
            try:
                conn.close()
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass


def _run_with_deadline(fn, deadline_s: float):
    box: dict = {}

    def _target():
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 — test helper captures any failure
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    started = time.perf_counter()
    thread.start()
    thread.join(deadline_s)
    elapsed = time.perf_counter() - started
    assert not thread.is_alive(), f"operation exceeded {deadline_s}s failsafe"
    return box, elapsed


def test_live_postgres_connect_timeout_against_silent_listener(monkeypatch):
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "1")
    with _SilentTCPServer() as server:
        engine = _create_engine(f"postgresql://u:p@127.0.0.1:{server.port}/db")

        def _connect():
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))

        box, elapsed = _run_with_deadline(_connect, 8)
        engine.dispose()
    assert "error" in box
    assert elapsed < 5, elapsed
    assert elapsed >= 0.4, elapsed


def test_pool_checkout_timeout_is_bounded_independently():
    """QueuePool checkout wait is pool_timeout, not connect_timeout.

    Uses SQLite plus an explicit QueuePool so the test does not need PostgreSQL.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
        connect_args={"check_same_thread": False},
    )
    first = engine.connect()
    start = time.perf_counter()
    with pytest.raises(SATimeout):
        engine.connect()
    elapsed = time.perf_counter() - start
    first.close()
    engine.dispose()
    assert elapsed < 5, elapsed
    assert elapsed >= 0.4, elapsed


def test_ready_maps_database_timeout_to_unavailable_without_leaking(app_client, monkeypatch):
    class _TimedOutEngine:
        def connect(self):
            raise SATimeout("QueuePool limit of size 5 overflow 10 elapsed, timeout 30")

    monkeypatch.setattr("routes.ops.engine", _TimedOutEngine())
    resp = app_client.get("/ready")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body == {"status": "not_ready", "checks": {"database": "unavailable"}}
    text = resp.get_data(as_text=True)
    assert "QueuePool" not in text
    assert "timeout 30" not in text


def test_redis_client_kwargs_are_passed_to_from_url(monkeypatch):
    seen: dict = {}

    class _Fake:
        def ping(self):
            return True

        def close(self):
            pass

    def _from_url(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return _Fake()

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("REDIS_CONNECT_TIMEOUT", "2")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "4")
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(_from_url))
    conn = get_redis_connection()
    assert conn is not None
    assert seen["kwargs"]["socket_connect_timeout"] == 2
    assert seen["kwargs"]["socket_timeout"] == 4
    assert seen["kwargs"]["retry_on_timeout"] is False
    assert "redis://localhost:6379/0" not in str(redis_client_kwargs())


def test_redis_client_kwargs_reject_zero_and_invalid(monkeypatch):
    monkeypatch.setenv("REDIS_CONNECT_TIMEOUT", "0")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "nope")
    kwargs = redis_client_kwargs()
    assert kwargs["socket_connect_timeout"] == jobs_mod.DEFAULT_REDIS_CONNECT_TIMEOUT
    assert kwargs["socket_timeout"] == jobs_mod.DEFAULT_REDIS_SOCKET_TIMEOUT


def test_get_redis_connection_closes_client_when_ping_fails(monkeypatch):
    closed: list[bool] = []

    class _Fake:
        def ping(self):
            raise TimeoutError("redis timed out talking to redis://secret@host/0")

        def close(self):
            closed.append(True)

    monkeypatch.setenv("REDIS_URL", "redis://secret@localhost:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(lambda url, **kwargs: _Fake()))
    assert get_redis_connection() is None
    assert closed == [True]


def test_redis_is_reachable_closes_successful_client(monkeypatch):
    closed: list[bool] = []

    class _Fake:
        def ping(self):
            return True

        def close(self):
            closed.append(True)

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(lambda url, **kwargs: _Fake()))
    assert redis_is_reachable() is True
    assert closed == [True]


def test_live_redis_connect_timeout_against_silent_listener(monkeypatch):
    monkeypatch.setenv("REDIS_CONNECT_TIMEOUT", "1")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "1")
    with _SilentTCPServer() as server:
        monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{server.port}/0")

        def _ping():
            return get_redis_connection()

        box, elapsed = _run_with_deadline(_ping, 8)
    assert box.get("value") is None
    assert "error" not in box
    assert elapsed < 5, elapsed
    assert elapsed >= 0.4, elapsed


def test_redis_connection_refused_returns_none(monkeypatch):
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()
    monkeypatch.setenv("REDIS_URL", f"redis://127.0.0.1:{port}/0")
    monkeypatch.setenv("REDIS_CONNECT_TIMEOUT", "1")
    monkeypatch.setenv("REDIS_SOCKET_TIMEOUT", "1")
    start = time.perf_counter()
    assert get_redis_connection() is None
    assert time.perf_counter() - start < 3


def test_ready_uses_timeout_kwargs_and_closes_on_success(app_client, monkeypatch):
    closed: list[bool] = []
    seen: dict = {}

    class _Fake:
        def ping(self):
            return True

        def close(self):
            closed.append(True)

    def _from_url(url, **kwargs):
        seen.update(kwargs)
        return _Fake()

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(_from_url))
    resp = app_client.get("/ready")
    assert resp.status_code == 200
    assert resp.get_json()["checks"]["redis"] == "ok"
    assert seen["socket_connect_timeout"] == jobs_mod.DEFAULT_REDIS_CONNECT_TIMEOUT
    assert seen["socket_timeout"] == jobs_mod.DEFAULT_REDIS_SOCKET_TIMEOUT
    assert closed == [True]


def test_ready_redis_timeout_error_is_unavailable_without_leak(app_client, monkeypatch):
    class _Fake:
        def ping(self):
            raise TimeoutError("timed out contacting redis://secret:pass@redis:6379/0")

        def close(self):
            pass

    monkeypatch.setenv("REDIS_URL", "redis://secret:pass@redis:6379/0")
    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(lambda url, **kwargs: _Fake()))
    resp = app_client.get("/ready")
    assert resp.status_code == 503
    assert resp.get_json()["checks"]["redis"] == "unavailable"
    text = resp.get_data(as_text=True)
    assert "secret" not in text
    assert "redis://" not in text
    assert "timed out" not in text
