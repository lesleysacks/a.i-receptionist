"""WhatsApp number -> business routing tests."""

from __future__ import annotations

import re

from sqlalchemy import select

from database import get_session
from models.booking import Booking
from tests.conftest import whatsapp_post

NUMBER_A = "whatsapp:+27111111111"
NUMBER_B = "whatsapp:+27222222222"
CUSTOMER = "whatsapp:+27831234567"


def _reply(resp):
    m = re.search(r"<Message>(.*?)</Message>", resp.get_data(as_text=True), re.S)
    return (m.group(1).strip() if m else "")


def test_known_number_routes_to_business_a(make_business, app_client):
    make_business(name="Business A", services=["PLC Programming"], whatsapp_number=NUMBER_A)
    resp = whatsapp_post(app_client, "I want to book", CUSTOMER, NUMBER_A)
    assert resp.status_code == 200
    assert "book" in _reply(resp).lower() or "name" in _reply(resp).lower()


def test_second_known_number_routes_to_business_b(make_business, app_client):
    make_business(name="Business A", services=["PLC Programming"], whatsapp_number=NUMBER_A)
    biz_b = make_business(name="Business B", services=["Photography"], whatsapp_number=NUMBER_B)

    # Drive a booking through Business B's number.
    for msg in ("book", "Bob", "2026-12-30 14:00", "Photography", "yes"):
        whatsapp_post(app_client, msg, CUSTOMER, NUMBER_B)

    with get_session() as session:
        bookings = session.scalars(select(Booking)).all()
        assert len(bookings) == 1
        assert bookings[0].business_id == biz_b
        assert bookings[0].service == "Photography"


def test_unknown_number_is_safely_rejected(make_business, app_client):
    make_business(name="Business A", services=["PLC Programming"], whatsapp_number=NUMBER_A)
    resp = whatsapp_post(app_client, "hello", CUSTOMER, "whatsapp:+27999999999")
    assert resp.status_code == 200
    assert "couldn't match" in _reply(resp).lower()
    # No booking/conversation created for an unknown tenant.
    with get_session() as session:
        assert session.scalars(select(Booking)).all() == []


def test_missing_number_is_handled_safely(make_business, app_client):
    make_business(name="Business A", services=["PLC Programming"], whatsapp_number=NUMBER_A)
    resp = whatsapp_post(app_client, "hello", CUSTOMER, to=None)
    assert resp.status_code == 200
    assert "couldn't match" in _reply(resp).lower()


def test_routing_is_cross_tenant_isolated(make_business, app_client):
    """A customer on Business A's number is offered only Business A's services."""
    make_business(name="Business A", services=["PLC Programming"], whatsapp_number=NUMBER_A)
    make_business(name="Business B", services=["Photography"], whatsapp_number=NUMBER_B)

    whatsapp_post(app_client, "book", CUSTOMER, NUMBER_A)
    whatsapp_post(app_client, "Alice", CUSTOMER, NUMBER_A)
    prompt = _reply(whatsapp_post(app_client, "2026-12-30 14:00", CUSTOMER, NUMBER_A))
    assert "PLC Programming" in prompt
    assert "Photography" not in prompt