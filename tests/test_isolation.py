"""Multi-business isolation: one tenant must never see another tenant's data."""

from __future__ import annotations

from sqlalchemy import select

from database import get_session
from models.booking import Booking
from services.business_service import BusinessService
from services.context_builder import ContextBuilder
from services.conversation_service import CONFIRM, ConversationService
from tests.helpers import FakeAI

CUSTOMER = "whatsapp:+27831234567"


def _service():
    return ConversationService(ai_service=FakeAI(), state_store={})


def test_services_are_isolated_per_business(make_business):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])

    names_a = [s.name for s in BusinessService.get_services(biz_a)]
    names_b = [s.name for s in BusinessService.get_services(biz_b)]

    assert names_a == ["PLC Programming"]
    assert names_b == ["Photography"]
    assert "Photography" not in names_a
    assert "PLC Programming" not in names_b


def test_context_builder_only_exposes_own_services(make_business):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    make_business(name="Business B", services=["Photography"])

    context = ContextBuilder().build(biz_a)
    service_names = [s["name"] for s in context["services"]]
    assert service_names == ["PLC Programming"]


def test_search_does_not_cross_tenants(make_business):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])

    assert BusinessService.search_services(biz_a, "Photography") == []
    assert [s.name for s in BusinessService.search_services(biz_b, "Photography")] == ["Photography"]


def test_customer_of_business_a_cannot_get_business_b_service(make_business):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    make_business(name="Business B", services=["Photography"])

    cs = _service()
    cs.handle(biz_a, CUSTOMER, "book")
    cs.handle(biz_a, CUSTOMER, "Alice")
    prompt = cs.handle(biz_a, CUSTOMER, "2026-12-30 14:00")
    # Business A's service prompt must not advertise Business B's service.
    assert "PLC Programming" in prompt
    assert "Photography" not in prompt

    # Trying to book Business B's service against Business A is rejected.
    rejected = cs.handle(biz_a, CUSTOMER, "Photography")
    assert "couldn't find that service" in rejected.lower()


def test_bookings_are_scoped_to_their_business(make_business):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])

    cs = _service()
    for msg in ("book", "Alice", "2026-12-30 14:00", "PLC Programming", "yes"):
        cs.handle(biz_a, CUSTOMER, msg)

    with get_session() as session:
        a_bookings = session.scalars(select(Booking).where(Booking.business_id == biz_a)).all()
        b_bookings = session.scalars(select(Booking).where(Booking.business_id == biz_b)).all()

    assert len(a_bookings) == 1
    assert a_bookings[0].service == "PLC Programming"
    assert b_bookings == []
