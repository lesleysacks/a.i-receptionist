"""Uniqueness and ownership constraints across core tables."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from database import get_session
from models.business import Business
from models.conversation_state import ConversationState
from services.business_service import BusinessService, ValidationError


def test_whatsapp_number_is_unique(make_business):
    make_business(name="Business A", whatsapp_number="whatsapp:+27111111111")
    with pytest.raises(ValidationError):
        BusinessService.create_business({"name": "Business B", "whatsapp_number": "whatsapp:+27111111111"})


def test_conversation_state_unique_per_business_and_sender(make_business):
    business_id = make_business(name="Business A")
    with get_session() as session:
        session.add(ConversationState(business_id=business_id, sender="whatsapp:+27831234567", step="ask_name"))
    with pytest.raises(IntegrityError):
        with get_session() as session:
            session.add(ConversationState(business_id=business_id, sender="whatsapp:+27831234567", step="ask_date"))


def test_service_name_unique_per_business(make_business):
    business_id = make_business(name="Business A", services=["PLC Programming"])
    with pytest.raises(ValidationError):
        BusinessService.add_service(business_id, {"name": "PLC Programming"})


def test_same_service_name_allowed_across_businesses(make_business):
    biz_a = make_business(name="Business A")
    biz_b = make_business(name="Business B")
    BusinessService.add_service(biz_a, {"name": "Consulting"})
    # Same name under a different tenant is fine.
    BusinessService.add_service(biz_b, {"name": "Consulting"})
    assert [s.name for s in BusinessService.get_services(biz_a)] == ["Consulting"]
    assert [s.name for s in BusinessService.get_services(biz_b)] == ["Consulting"]
