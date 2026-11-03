"""Tenant-scoped leads: an admin only ever sees their own business's leads."""

from __future__ import annotations

from services.conversation_service import ConversationService
from tests.conftest import login
from tests.helpers import FakeAI

CUSTOMER = "whatsapp:+27831234567"


def _book(business_id, name, service):
    cs = ConversationService(ai_service=FakeAI(), state_store={})
    for msg in ("book", name, "2026-12-30 14:00", service, "yes"):
        cs.handle(business_id, CUSTOMER, msg)


def test_admins_only_see_their_own_leads(make_business, make_admin, app_client):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])
    _book(biz_a, "Alice", "PLC Programming")
    _book(biz_b, "Bob", "Photography")

    email_a, pw_a = make_admin(biz_a, email="a@example.com")
    email_b, pw_b = make_admin(biz_b, email="b@example.com")

    # Business A admin sees only A.
    login(app_client, email_a, pw_a)
    html_a = app_client.get("/leads").get_data(as_text=True)
    assert "Alice" in html_a
    assert "Bob" not in html_a
    app_client.get("/logout")

    # Business B admin sees only B.
    login(app_client, email_b, pw_b)
    html_b = app_client.get("/leads").get_data(as_text=True)
    assert "Bob" in html_b
    assert "Alice" not in html_b


def test_leads_query_is_scoped_at_database_level(make_business):
    from services.booking_service import BookingService

    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])
    _book(biz_a, "Alice", "PLC Programming")
    _book(biz_b, "Bob", "Photography")

    a_leads = BookingService.list_bookings(biz_a)
    b_leads = BookingService.list_bookings(biz_b)
    assert [b.customer.name for b in a_leads] == ["Alice"]
    assert [b.customer.name for b in b_leads] == ["Bob"]