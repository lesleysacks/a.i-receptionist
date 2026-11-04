"""Write and query redacted intelligence outcomes.

Persistence failures are swallowed so the receptionist can still reply.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.intelligence.models import IntelligenceOutcome
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import user_is_platform_admin

logger = logging.getLogger(__name__)

_FORBIDDEN_FIELD_NAMES = {
    "message",
    "body",
    "phone",
    "sender",
    "transcript",
    "prompt",
    "password",
    "token",
    "api_key",
}


def record_pipeline_outcome(
    *,
    business_id: int,
    intent: str,
    classification_method: str,
    confidence: float | None,
    decision: str,
    response_type: str,
    ai_required: bool,
    outcome: str,
    duration_ms: float | None,
) -> IntelligenceOutcome | None:
    """Insert one outcome row. Never accepts message text or phone numbers."""
    try:
        tenant = Tenant.objects.filter(receptionist_business_id=business_id).first()
        with transaction.atomic():
            return IntelligenceOutcome.objects.create(
                tenant=tenant,
                receptionist_business_id=int(business_id),
                intent=_clip(intent, 32),
                classification_method=_clip(classification_method, 32),
                confidence=_confidence(confidence),
                decision=_clip(decision, 32),
                response_type=_clip(response_type, 32),
                ai_required=bool(ai_required),
                outcome=_clip(outcome, 32),
                duration_ms=_duration(duration_ms),
            )
    except Exception:
        logger.exception("Failed to persist intelligence outcome business_id=%s", business_id)
        return None


def outcomes_for_user(user):
    """Tenant-scoped queryset. Platform admins see all rows via this helper."""
    empty = IntelligenceOutcome.objects.none()
    if user is None or not getattr(user, "is_active", False):
        return empty
    if user_is_platform_admin(user):
        return IntelligenceOutcome.objects.all()
    tenant_ids = Membership.objects.filter(
        user=user,
        status=Membership.Status.ACTIVE,
        tenant__status=Tenant.Status.ACTIVE,
    ).values_list("tenant_id", flat=True)
    return IntelligenceOutcome.objects.filter(tenant_id__in=tenant_ids)


def assert_no_sensitive_fields() -> None:
    """Raise if the model gains a forbidden PII-shaped column."""
    names = {field.name for field in IntelligenceOutcome._meta.get_fields()}
    leaked = names & _FORBIDDEN_FIELD_NAMES
    if leaked:
        raise RuntimeError(f"IntelligenceOutcome must not store {sorted(leaked)}")


def _clip(value: str, limit: int) -> str:
    return str(value or "")[:limit]


def _confidence(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount < 0:
        return Decimal("0")
    if amount > 1:
        return Decimal("1")
    return amount.quantize(Decimal("0.001"))


def _duration(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount < 0:
        return Decimal("0")
    return amount.quantize(Decimal("0.1"))
