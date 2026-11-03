"""Happy-path booking conversation, persistence, and lead visibility."""

from __future__ import annotations

from sqlalchemy import select

from database import get_session
from models.booking import Booking
from services.conversation_service import CONFIRM, IDLE, ConversationService
from tests.helpers import FakeAI

SENDER = "whatsapp:+27831234567"


def _service():
    return ConversationService(ai_service=FakeAI(), state_store={})


def test_full_booking_flow_persists_lead(make_business):
    business_id = make_business(name="Genai", services=["PLC Programming", "Factory Automation"])
    cs = _service()

    r1 = cs.handle(business_id, SENDER, "I want to book an appointment")
    assert "name" in r1.lower()

    r2 = cs.handle(business_id, SENDER, "John Smith")
    assert "date" in r2.lower()

    r3 = cs.handle(business_id, SENDER, "2026-12-30 14:00")
    assert "service" in r3.lower()
    # Only the configured services should be offered.
    assert "PLC Programming" in r3 and "Factory Automation" in r3

    r4 = cs.handle(business_id, SENDER, "Factory Automation")
    # Summary + confirmation request, before anything is persisted.
    assert "confirm" in r4.lower()
    assert "John Smith" in r4 and "Factory Automation" in r4 and "2026-12-30 14:00" in r4

    # Nothing persisted until the customer confirms.
    with get_session() as session:
        assert session.scalars(select(Booking)).all() == []

    r5 = cs.handle(business_id, SENDER, "yes")
    assert "confirmed" in r5.lower()

    # Booking persisted and associated with the correct business.
    with get_session() as session:
        bookings = session.scalars(select(Booking)).all()
        assert len(bookings) == 1
        booking = bookings[0]
        assert booking.business_id == business_id
        assert booking.service == "Factory Automation"
        assert booking.customer.name == "John Smith"
        assert booking.customer.phone == SENDER

    # Conversation returns to idle so the customer can start again.
    key = (business_id, SENDER)
    assert cs._states[key].step == IDLE


def test_booking_visible_on_leads_dashboard(make_business, make_admin, app_client):
    business_id = make_business(name="Genai", services=["PLC Programming"])
    cs = _service()
    for msg in ("book", "Jane Doe", "2026-12-01 10:00", "PLC Programming", "yes"):
        cs.handle(business_id, SENDER, msg)

    from tests.conftest import login

    email, password = make_admin(business_id)
    login(app_client, email, password)

    resp = app_client.get("/leads")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Jane Doe" in html
    assert "PLC Programming" in html
