"""Distributed (Redis-backed) login rate limiting and safe fallback."""

from __future__ import annotations

import os

import pytest

from services.rate_limiter import LoginRateLimiter, RedisLoginRateLimiter


def _redis_or_skip():
    url = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis

        conn = redis.Redis.from_url(url)
        conn.ping()
        return conn
    except Exception:
        pytest.skip("Redis not available for distributed rate-limit test")


@pytest.fixture
def ctx(app_client):
    import app as app_module

    with app_module.app.app_context():
        app_module.app.config["LOGIN_MAX_ATTEMPTS"] = 3
        app_module.app.config["LOGIN_WINDOW_SECONDS"] = 60
        app_module.app.config["LOGIN_LOCKOUT_SECONDS"] = 60
        yield app_module.app


def test_redis_limiter_blocks_after_threshold(ctx):
    conn = _redis_or_skip()
    limiter = RedisLoginRateLimiter(conn, key_prefix="test_rl")
    key = "1.2.3.4"
    limiter.reset(key)
    try:
        assert limiter.is_blocked(key) is False
        for _ in range(3):
            limiter.register_failure(key)
        assert limiter.is_blocked(key) is True
        # A successful login resets the counter.
        limiter.reset(key)
        assert limiter.is_blocked(key) is False
    finally:
        limiter.reset(key)


def test_redis_limiter_falls_back_when_redis_errors(ctx):
    class _BrokenRedis:
        def exists(self, *a):
            raise RuntimeError("redis down")

        def incr(self, *a):
            raise RuntimeError("redis down")

        def expire(self, *a):
            raise RuntimeError("redis down")

        def set(self, *a, **k):
            raise RuntimeError("redis down")

        def delete(self, *a):
            raise RuntimeError("redis down")

        def scan_iter(self, *a):
            raise RuntimeError("redis down")

    limiter = RedisLoginRateLimiter(_BrokenRedis(), key_prefix="test_rl_fb")
    key = "5.6.7.8"
    # Protection must NOT be silently disabled: the process-local fallback still blocks.
    assert limiter.is_blocked(key) is False
    for _ in range(3):
        limiter.register_failure(key)
    assert limiter.is_blocked(key) is True
