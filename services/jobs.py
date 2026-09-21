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


def redis_url() -> str | None:
    return os.getenv("REDIS_URL")


def get_redis_connection():
    """Return a Redis connection, or None when Redis is not configured/reachable."""
    url = redis_url()
    if not url:
        return None
    try:
        import redis

        conn = redis.Redis.from_url(url)
        conn.ping()
        return conn
    except Exception:
        logger.warning("Redis is configured but unreachable; falling back to inline execution.")
        return None


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
