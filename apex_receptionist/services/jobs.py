"""Background-job infrastructure (RQ + Redis) with a safe inline fallback.

Redis/RQ are used only for ephemeral infrastructure coordination; PostgreSQL
remains the source of truth. When Redis is not configured or unreachable, jobs
run inline so the feature still works in single-process/dev environments (the
job functions themselves are idempotent, so this is safe).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

QUEUE_NAME = os.getenv("RQ_QUEUE", "default")

# Bounded Redis I/O for jobs and /ready. Defaults match DB_CONNECT_TIMEOUT and
# Compose healthcheck timeouts so a probe cannot hang until GUNICORN_TIMEOUT.
DEFAULT_REDIS_CONNECT_TIMEOUT = 3
DEFAULT_REDIS_SOCKET_TIMEOUT = 3


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def redis_url() -> str | None:
    return os.getenv("REDIS_URL")


def redis_client_kwargs() -> dict:
    """Timeouts passed to ``redis.Redis.from_url``. Never includes the URL."""
    return {
        "socket_connect_timeout": _positive_int_env(
            "REDIS_CONNECT_TIMEOUT", DEFAULT_REDIS_CONNECT_TIMEOUT
        ),
        "socket_timeout": _positive_int_env(
            "REDIS_SOCKET_TIMEOUT", DEFAULT_REDIS_SOCKET_TIMEOUT
        ),
        "retry_on_timeout": False,
    }


def _close_redis_client(conn) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def get_redis_connection():
    """Return a Redis connection, or None when Redis is not configured/reachable."""
    url = redis_url()
    if not url:
        return None
    conn = None
    try:
        import redis

        conn = redis.Redis.from_url(url, **redis_client_kwargs())
        conn.ping()
        return conn
    except Exception:
        logger.warning("Redis is configured but unreachable; falling back to inline execution.")
        _close_redis_client(conn)
        return None


def redis_is_reachable() -> bool:
    """PING Redis when configured, then close the client.

    Used by ``GET /ready`` so probes do not leak connections. Job enqueue still
    uses :func:`get_redis_connection` and keeps the client open.
    """
    conn = get_redis_connection()
    if conn is None:
        return False
    _close_redis_client(conn)
    return True


def get_queue():
    """Return an RQ queue, or None when Redis is unavailable."""
    conn = get_redis_connection()
    if conn is None:
        return None
    from rq import Queue

    return Queue(QUEUE_NAME, connection=conn)


def _enqueue(func_path: str, *args) -> str:
    """Enqueue a job with bounded retries, or run inline as a safe fallback."""
    queue = get_queue()
    if queue is None:
        return _run_inline(func_path, *args)
    try:
        from rq import Retry

        queue.enqueue(func_path, *args, retry=Retry(max=3, interval=[10, 30, 60]))
        logger.info("Enqueued job %s args=%s", func_path, args)
        return "enqueued"
    except Exception:
        logger.exception("Failed to enqueue %s; running inline instead", func_path)
        return _run_inline(func_path, *args)


def _run_inline(func_path: str, *args) -> str:
    from services import notifications

    func = getattr(notifications, func_path.rsplit(".", 1)[-1])
    try:
        func(*args)
    except Exception:
        logger.exception("Inline job %s failed", func_path)
        return "inline_error"
    return "inline"


def enqueue_owner_notification(booking_id: int) -> str:
    return _enqueue("services.notifications.send_owner_notification", booking_id)


def enqueue_booking_reminder(booking_id: int) -> str:
    return _enqueue("services.notifications.send_booking_reminder", booking_id)
