"""Structured, machine-readable logging.

Emits one JSON object per log record with a stable set of fields plus any
whitelisted structured ``extra`` fields. Never logs secrets or request bodies;
callers are responsible for masking customer identifiers before logging.
"""

from __future__ import annotations

import datetime
import json
import logging
import os

# Fields we allow through from `logger.info(..., extra={...})`.
_ALLOWED_EXTRA = {
    "event", "method", "path", "status", "latency_ms",
    "business_id", "booking_id", "outcome", "client",
}

_BASE_RECORD_KEYS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.datetime.fromtimestamp(record.created, datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _ALLOWED_EXTRA and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Configure root logging from LOG_LEVEL and LOG_FORMAT (json|plain)."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "json").lower()

    handler = logging.StreamHandler()
    if log_format == "plain":
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
