"""Operational endpoints: liveness (/health) and readiness (/ready)."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify
from sqlalchemy import text

from database import engine
from services.jobs import get_redis_connection, redis_url

logger = logging.getLogger(__name__)

ops_bp = Blueprint("ops", __name__)


@ops_bp.get("/health")
def health():
    """Liveness: the process is up. Deliberately does NOT touch the database."""
    return jsonify({"status": "ok"}), 200


@ops_bp.get("/ready")
def ready():
    """Readiness: required dependencies are available to serve traffic."""
    checks: dict[str, str] = {}
    ready_ok = True

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("Readiness check failed: database")
        checks["database"] = "unavailable"
        ready_ok = False

    # Redis is only required when configured (jobs / shared rate limiting).
    if redis_url():
        checks["redis"] = "ok" if get_redis_connection() is not None else "unavailable"
        if checks["redis"] != "ok":
            ready_ok = False

    status = "ready" if ready_ok else "not_ready"
    return jsonify({"status": status, "checks": checks}), (200 if ready_ok else 503)
