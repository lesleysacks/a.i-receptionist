"""Booking flow error handling: bad input, unknown service, cancel, restart, corrections."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from database import get_session
from models.booking import Booking
from services.conversation_service import (
    ASK_DATE,
    ASK_NAME,
    ASK_SERVICE,
    CONFIRM,
    IDLE,
    ConversationService,
)
from tests.helpers import FakeAI

SENDER = "whatsapp:+27831234567"


def _service():
    return ConversationService(ai_service=FakeAI(), state_store={})


def _start_to_date(cs, business_id):
    cs.handle(business_id, SENDER, "book")
    cs.handle(business_id, SENDER, "John Smith")


@pytest.mark.parametrize("bad_date", ["banana", "tomorrow maybe", "25:99", "99/99/9999 99:99"])
def test_invalid_date_is_rejected_without_crashing(make_business, bad_date):
    business_id = make_business(services=["PLC Programming"])
    cs = _service()
    _start_to_date(cs, business_id)

    reply = cs.handle(business_id, SENDER, bad_date)
    assert "date" in reply.lower()
    assert cs._states[(business_id, SENDER)].step == ASK_DATE


def test_past_date_is_rejected(make_business):
    business_id = make_business(services=["PLC Programming"])
    cs = _service()
    _start_to_date(cs, business_id)

    reply = cs.handle(business_id, SENDER, "2000-01-01 09:00")
    assert "past" in reply.lower()
    assert cs._states[(business_id, SENDER)].step == ASK_DATE


def test_unknown_service_is_rejected(make_business):
    business_id = make_business(services=["PLC Programming", "Factory Automation"])
    cs = _service()
    _start_to_date(cs, business_id)
    cs.handle(business_id, SENDER, "2026-12-30 14:00")

    reply = cs.handle(business_id, SENDER, "Photography")
    assert "couldn't find that service" in reply.lower()
    assert cs._states[(business_id, SENDER)].step == ASK_SERVICE
    # A valid service then advances the flow.
    reply2 = cs.handle(business_id, SENDER, "PLC Programming")
    assert "confirm" in reply2.lower()


def test_cancel_resets_state(make_business):
    business_id = make_business(services=["PLC Programming"])
    cs = _service()
    _start_to_date(cs, business_id)

    reply = cs.handle(business_id, SENDER, "cancel")
    assert "cancel" in reply.lower()
    assert cs._states[(business_id, SENDER)].step == IDLE


def test_never_mind_cancels(make_business):
    business_id = make_business(services=["PLC Programming"])
    cs = _service()
    _start_to_date(cs, business_id)
    reply = cs.handle(business_id, SENDER, "never mind")
    assert cs._states[(business_id, SENDER)].step == IDLE
    assert "cancel" in reply.lower()


def test_start_over_restarts_flow(make_business):
    business_id = make_business(services=["PLC Programming"])
    cs = _service()
    _start_to_date(cs, business_id)
    cs.handle(business_id, SENDER, "2026-12-30 14:00")

    reply = cs.handle(business_id, SENDER, "start over")
    assert cs._states[(business_id, SENDER)].step == ASK_NAME
    assert "start over" in reply.lower() or "name" in reply.lower()


def test_change_service_at_confirmation_does_not_corrupt_state(make_business):
    business_id = make_business(services=["PLC Programming", "Factory Automation"])
    cs = _service()
    _start_to_date(cs, business_id)
    cs.handle(business_id, SENDER, "2026-12-30 14:00")
    cs.handle(business_id, SENDER, "PLC Programming")  # now at CONFIRM

    reply = cs.handle(business_id, SENDER, "Actually, I want a different service")
    assert cs._states[(business_id, SENDER)].step == ASK_SERVICE
    assert "service" in reply.lower()

    # Choosing a new service should keep name and date intact.
    state = cs._states[(business_id, SENDER)]
    assert state.name == "John Smith"
    assert state.appointment_at is not None

    reply2 = cs.handle(business_id, SENDER, "Factory Automation")
    assert "Factory Automation" in reply2
    assert "John Smith" in reply2


def test_decline_at_confirmation_cancels(make_business):
    business_id = make_business(services=["PLC Programming"])
    cs = _service()
    _start_to_date(cs, business_id)
    cs.handle(business_id, SENDER, "2026-12-30 14:00")
    cs.handle(business_id, SENDER, "PLC Programming")

    reply = cs.handle(business_id, SENDER, "no")
    assert cs._states[(business_id, SENDER)].step == IDLE
    with get_session() as session:
        assert session.scalars(select(Booking)).all() == []
    assert "won't book" in reply.lower() or "wont book" in reply.lower()


def test_empty_message_is_handled(make_business):
    business_id = make_business(services=["PLC Programming"])
    cs = _service()
    reply = cs.handle(business_id, SENDER, "   ")
    assert "didn't catch" in reply.lower()


def test_flow_requests_missing_fields_in_order(make_business):
    """The receptionist collects name -> date -> service, requesting each in turn."""
    business_id = make_business(services=["PLC Programming"])
    cs = _service()

    ask_name = cs.handle(business_id, SENDER, "book")
    assert "name" in ask_name.lower()
    assert cs._states[(business_id, SENDER)].step == ASK_NAME

    ask_date = cs.handle(business_id, SENDER, "John Smith")
    assert "date" in ask_date.lower()
    assert cs._states[(business_id, SENDER)].step == ASK_DATE

    ask_service = cs.handle(business_id, SENDER, "2026-12-30 14:00")
    assert "service" in ask_service.lower()
    assert cs._states[(business_id, SENDER)].step == ASK_SERVICE


def test_missing_business_configuration_is_safe(make_business):
    """Handling a message for a non-existent business must not crash."""
    cs = _service()
    reply = cs.handle(9999, SENDER, "hello there")
    assert reply  # safe, non-empty message
    assert "wrong" in reply.lower() or "set up" in reply.lower()
