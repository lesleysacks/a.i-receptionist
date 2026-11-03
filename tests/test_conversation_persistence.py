"""Durable, tenant-scoped conversation state and idempotent confirmation."""

from __future__ import annotations

from sqlalchemy import select

from database import get_session
from models.booking import Booking
from services.conversation_service import ASK_SERVICE, ConversationService
from tests.helpers import FakeAI

CUSTOMER = "whatsapp:+27831234567"


def _cs():
    # Default store is the durable DB-backed store.
    return ConversationService(ai_service=FakeAI())


def test_state_survives_application_restart(make_business):
    business_id = make_business(name="Business A", services=["PLC Programming"])

    cs1 = _cs()
    cs1.handle(business_id, CUSTOMER, "book")
    cs1.handle(business_id, CUSTOMER, "Alice")
    cs1.handle(business_id, CUSTOMER, "2026-12-30 14:00")

    # Simulate a restart: a brand-new service instance with no in-memory state.
    cs2 = _cs()
    state = cs2.get_state(business_id, CUSTOMER)
    assert state.step == ASK_SERVICE
    assert state.name == "Alice"
    assert state.appointment_at is not None

    # The conversation resumes correctly and completes.
    reply = cs2.handle(business_id, CUSTOMER, "PLC Programming")
    assert "confirm" in reply.lower()
    cs2.handle(business_id, CUSTOMER, "yes")

    with get_session() as session:
        bookings = session.scalars(select(Booking)).all()
        assert len(bookings) == 1
        assert bookings[0].customer.name == "Alice"


def test_state_is_business_scoped(make_business):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])

    cs = _cs()
    # Same customer number talking to two different businesses.
    cs.handle(biz_a, CUSTOMER, "book")
    cs.handle(biz_a, CUSTOMER, "Alice")

    # Business B conversation is independent and does not resume A's state.
    state_b = cs.get_state(biz_b, CUSTOMER)
    assert state_b.step == "idle"
    assert state_b.name is None

    state_a = cs.get_state(biz_a, CUSTOMER)
    assert state_a.step == "ask_date"
    assert state_a.name == "Alice"


def test_duplicate_confirmation_does_not_duplicate_booking(make_business):
    business_id = make_business(name="Business A", services=["PLC Programming"])
    cs = _cs()
    for msg in ("book", "Alice", "2026-12-30 14:00", "PLC Programming"):
        cs.handle(business_id, CUSTOMER, msg)

    # First and second "yes" (e.g. a network retry).
    cs.handle(business_id, CUSTOMER, "yes")
    cs.handle(business_id, CUSTOMER, "yes")

    with get_session() as session:
        bookings = session.scalars(select(Booking)).all()
        assert len(bookings) == 1


def test_idempotent_create_booking_returns_same_row(make_business):
    from datetime import datetime

    from services.booking_service import BookingService

    business_id = make_business(name="Business A")
    when = datetime(2026, 12, 30, 14, 0)
    first = BookingService.create_booking(business_id, "Alice", when, CUSTOMER, "PLC Programming")
    second = BookingService.create_booking(business_id, "Alice", when, CUSTOMER, "PLC Programming")
    assert first.id == second.id