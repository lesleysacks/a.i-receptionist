"""Compatibility shim."""

from apex_receptionist.services.jobs import (
    QUEUE_NAME,
    enqueue_booking_reminder,
    enqueue_owner_notification,
    get_queue,
    get_redis_connection,
    redis_url,
)

__all__ = [
    "QUEUE_NAME",
    "enqueue_booking_reminder",
    "enqueue_owner_notification",
    "get_queue",
    "get_redis_connection",
    "redis_url",
]
