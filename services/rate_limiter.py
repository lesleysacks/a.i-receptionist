"""Login abuse protection: process-local and Redis-backed (multi-worker) limiters.

Both enforce the same policy: after ``LOGIN_MAX_ATTEMPTS`` failures within
``LOGIN_WINDOW_SECONDS`` the client is locked out for ``LOGIN_LOCKOUT_SECONDS``.
Thresholds are read from the Flask app config so they are env-tunable. No
credentials or passwords are ever stored or logged here.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


def _thresholds() -> tuple[int, int, int]:
    from flask import current_app

    cfg = current_app.config
    return (
        int(cfg.get("LOGIN_MAX_ATTEMPTS", 5)),
        int(cfg.get("LOGIN_WINDOW_SECONDS", 300)),
        int(cfg.get("LOGIN_LOCKOUT_SECONDS", 300)),
    )


class LoginRateLimiter:
    """Process-local limiter (used in dev/tests and as the Redis fallback)."""

    def __init__(self, time_func=time.monotonic) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._time = time_func

    def is_blocked(self, key: str) -> bool:
        max_attempts, window, lockout = _thresholds()
        horizon = max(window, lockout)
        now = self._time()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t <= horizon]
            self._failures[key] = recent
            if len(recent) < max_attempts:
                return False
            return (now - recent[-1]) < lockout

    def register_failure(self, key: str) -> None:
        now = self._time()
        with self._lock:
            self._failures.setdefault(key, []).append(now)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._failures.clear()
            else:
                self._failures.pop(key, None)


class RedisLoginRateLimiter:
    """Shared limiter backed by Redis so limits hold across Gunicorn workers.

    If Redis raises at runtime, it degrades to a process-local limiter rather
    than disabling protection (fail safe, never fail open).
    """

    def __init__(self, connection, key_prefix: str = "loginfail") -> None:
        self._redis = connection
        self._prefix = key_prefix
        self._fallback = LoginRateLimiter()
        self._warned = False

    def _fail_key(self, key: str) -> str:
        return f"{self._prefix}:count:{key}"

    def _lock_key(self, key: str) -> str:
        return f"{self._prefix}:lock:{key}"

    def _on_error(self) -> None:
        if not self._warned:
            logger.warning("Redis rate limiter unavailable; using process-local fallback.")
            self._warned = True

    def is_blocked(self, key: str) -> bool:
        try:
            return bool(self._redis.exists(self._lock_key(key)))
        except Exception:
            self._on_error()
            return self._fallback.is_blocked(key)

    def register_failure(self, key: str) -> None:
        max_attempts, window, lockout = _thresholds()
        try:
            count = self._redis.incr(self._fail_key(key))
            if count == 1:
                self._redis.expire(self._fail_key(key), window)
            if count >= max_attempts:
                self._redis.set(self._lock_key(key), 1, ex=lockout)
        except Exception:
            self._on_error()
            self._fallback.register_failure(key)

    def reset(self, key: str | None = None) -> None:
        try:
            if key is None:
                # Only used in tests; scan-and-delete our namespaced keys.
                for k in self._redis.scan_iter(f"{self._prefix}:*"):
                    self._redis.delete(k)
            else:
                self._redis.delete(self._fail_key(key), self._lock_key(key))
        except Exception:
            self._on_error()
        self._fallback.reset(key)


def build_login_rate_limiter():
    """Return a Redis-backed limiter when REDIS_URL is reachable, else local."""
    from services.jobs import get_redis_connection

    conn = get_redis_connection()
    if conn is not None:
        logger.info("Login rate limiting is Redis-backed (shared across workers).")
        return RedisLoginRateLimiter(conn)
    return LoginRateLimiter()
