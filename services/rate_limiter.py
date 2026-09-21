"""Lightweight in-memory login abuse protection (rate limit + temporary lockout).

Keyed by client identifier (IP). Thresholds are read from the Flask app config
so they are tunable via environment variables. This is intentionally simple; a
multi-process/production deployment should back this with a shared store
(e.g. Redis). No credentials or passwords are ever stored or logged here.
"""

from __future__ import annotations

import threading
import time


class LoginRateLimiter:
    def __init__(self, time_func=time.monotonic) -> None:
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._time = time_func

    def _thresholds(self) -> tuple[int, int, int]:
        from flask import current_app

        cfg = current_app.config
        return (
            int(cfg.get("LOGIN_MAX_ATTEMPTS", 5)),
            int(cfg.get("LOGIN_WINDOW_SECONDS", 300)),
            int(cfg.get("LOGIN_LOCKOUT_SECONDS", 300)),
        )

    def is_blocked(self, key: str) -> bool:
        max_attempts, window, lockout = self._thresholds()
        horizon = max(window, lockout)
        now = self._time()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t <= horizon]
            self._failures[key] = recent
            if len(recent) < max_attempts:
                return False
            # Blocked until `lockout` seconds have elapsed since the last failure.
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
