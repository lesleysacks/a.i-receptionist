"""Load approved business facts for one tenant.

Callers must already have resolved ``business_id`` from trusted routing
(WhatsApp ``To`` number or an authenticated membership). This module never
falls back to another tenant.
"""

from __future__ import annotations

from decimal import Decimal

from apex_receptionist.intelligence.types import FaqFact, ServiceFact, TenantFacts
from apex_receptionist.services.business_service import BusinessService


def load_tenant_facts(business_id: int) -> TenantFacts:
    """Fetch facts for an already-resolved business id."""
    business = BusinessService.get_business(business_id)
    return facts_from_business(business)


def facts_from_business(business) -> TenantFacts:
    """Build facts from a loaded Business row plus that tenant's catalogue."""
    business_id = int(business.id)
    services = BusinessService.get_services(business_id, active_only=True)
    faqs = BusinessService.get_faq(business_id)
    return TenantFacts(
        business_id=business_id,
        name=business.name,
        opening_hours=_text(business.opening_hours),
        address=_text(business.address),
        city=_text(business.city),
        country=_text(business.country),
        phone=_text(business.phone),
        email=_text(business.email),
        website=_text(business.website),
        currency=(business.currency or "USD").strip() or "USD",
        booking_enabled=bool(business.booking_enabled),
        services=tuple(
            ServiceFact(
                name=item.name,
                description=_text(item.description),
                price=_decimal(item.price),
            )
            for item in services
        ),
        faqs=tuple(FaqFact(question=item.question, answer=item.answer) for item in faqs),
    )


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
