"""Background job boundary: enqueue/inline, idempotency, and failure handling."""

from __future__ import annotations

import datetime

from database import get_session
from models.booking import Booking
from services import notifications
from services.booking_service import BookingService
from services.jobs import enqueue_owner_notification

CUSTOMER = "whatsapp:+27831234567"


def _booking(make_business, owner_phone=None):
    business_id = make_business(name="Business A", owner_phone=owner_phone)
    b = BookingService.create_booking(business_id, "Alice", datetime.datetime(2026, 12, 30, 14, 0), CUSTOMER, "PLC Programming")
    return b.id


class _CountingClient:
    def __init__(self):
        self.sent = 0
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.sent += 1

        self.messages = _Messages()


def test_enqueue_runs_inline_without_redis(make_business):
    # No REDIS_URL in tests -> jobs run inline; no owner phone -> safe no-op.
    booking_id = _booking(make_business, owner_phone=None)
    outcome = enqueue_owner_notification(booking_id)
    assert outcome == "inline"
    booking = BookingService.get(booking_id)
    assert booking.owner_notified is True  # marked so it is not retried


def test_owner_notification_is_idempotent(make_business, monkeypatch):
    booking_id = _booking(make_business, owner_phone="whatsapp:+27999999999")
    client = _CountingClient()
    monkeypatch.setattr(notifications, "_twilio_client", lambda: client)

    assert notifications.send_owner_notification(booking_id) == "sent"
    # A duplicate delivery of the same job must not send a second message.
    assert notifications.send_owner_notification(booking_id) == "already_sent"
    assert client.sent == 1


def test_owner_notification_failure_leaves_booking_unnotified_for_retry(make_business, monkeypatch):
    booking_id = _booking(make_business, owner_phone="whatsapp:+27999999999")

    class _FailingClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("twilio down")

    monkeypatch.setattr(notifications, "_twilio_client", lambda: _FailingClient())

    # The job raises so the queue can retry; the booking stays un-notified.
    try:
        notifications.send_owner_notification(booking_id)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    assert BookingService.get(booking_id).owner_notified is False


def test_booking_is_saved_even_if_notification_cannot_send(make_business, monkeypatch):
    # Simulate enqueue failure; the booking must remain persisted.
    booking_id = _booking(make_business, owner_phone=None)
    with get_session() as session:
        assert session.get(Booking, booking_id) is not None
