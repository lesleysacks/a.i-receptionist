"""Helpers to write redacted audit events."""

from __future__ import annotations

import logging
from typing import Any

from apps.audit.models import AuditEvent

logger = logging.getLogger(__name__)

_FORBIDDEN_METADATA_KEYS = {
    "password",
    "token",
    "secret",
    "api_key",
    "auth_token",
    "authorization",
    "body",
    "message",
    "transcript",
    "phone",
    "otp",
}


def _redact(metadata: dict[str, Any] | None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        lowered = str(key).lower()
        if any(part in lowered for part in _FORBIDDEN_METADATA_KEYS):
            continue
        if isinstance(value, str) and len(value) > 200:
            continue
        safe[key] = value
    return safe


def record_audit(
    *,
    actor=None,
    tenant=None,
    action: str,
    target_type: str = "",
    target_id: str = "",
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditEvent | None:
    """Persist an audit row. Failures are logged and never break the caller."""
    try:
        return AuditEvent.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            tenant=tenant if getattr(tenant, "pk", None) else None,
            action=action,
            target_type=target_type or "",
            target_id=str(target_id or ""),
            metadata=_redact(metadata),
            ip_address=ip_address,
        )
    except Exception:
        logger.exception("Failed to record audit event action=%s", action)
        return None
