"""Notification work executed by background workers (or inline as a fallback).

These functions are the durable job boundary for owner notifications and booking
reminders. They are idempotent: business state (``owner_notified`` /
``reminder_sent``) is persisted in PostgreSQL so a job that runs twice does not
send duplicate messages. They build their own Twilio client from the
environment, so they run in a worker process independent of the web app.
"""

from __future__ import annotations

import logging
import os

from twilio.rest import Client

from services.booking_service import BookingService

logger = logging.getLogger(__name__)


def _twilio_client() -> Client | None:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        return None
    return Client(sid, token)


def _sender_number() -> str:
    return os.getenv("TWILIO_PHONE_NUMBER") or os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")


def _mask(value: str | None) -> str:
    if not value:
        return "<unknown>"
    return f"***{value[-4:]}"


def send_owner_notification(booking_id: int) -> str:
    """Notify the business owner of a new booking. Idempotent and retry-safe."""
    booking = BookingService.get(booking_id)
    if booking is None:
        logger.warning("owner_notification: booking %s not found", booking_id)
        return "missing"
    if booking.owner_notified:
        logger.info("owner_notification: booking %s already notified; skipping", booking_id)
        return "already_sent"

    owner_phone = booking.business.owner_phone or os.getenv("OWNER_PHONE_NUMBER")
    if not owner_phone:
        logger.info("owner_notification: no owner phone for business_id=%s; nothing to send", booking.business_id)
        BookingService.mark_owner_notified(booking_id)
        return "no_owner_phone"

    client = _twilio_client()
    if client is None:
        # No credentials in this environment: do not retry-storm, do not mark sent.
        logger.warning("owner_notification: Twilio not configured; deferring booking %s", booking_id)
        return "twilio_unconfigured"

    body = (
        "New WhatsApp booking\n\n"
        f"Name: {booking.customer.name}\n"
        f"Phone: {booking.customer.phone}\n"
        f"Date: {booking.appointment_at:%Y-%m-%d %H:%M}\n"
        f"Service: {booking.service}"
    )
    # A Twilio error propagates so the job system can retry (finite retries).
    client.messages.create(from_=_sender_number(), body=body, to=owner_phone)
    BookingService.mark_owner_notified(booking_id)
    logger.info("owner_notification: sent for booking_id=%s to %s", booking_id, _mask(owner_phone))
    return "sent"


def send_booking_reminder(booking_id: int) -> str:
    """Send a customer reminder for an upcoming booking. Idempotent and retry-safe."""
    booking = BookingService.get(booking_id)
    if booking is None:
        logger.warning("reminder: booking %s not found", booking_id)
        return "missing"
    if booking.reminder_sent:
        logger.info("reminder: booking %s already reminded; skipping", booking_id)
        return "already_sent"

    client = _twilio_client()
    if client is None:
        logger.warning("reminder: Twilio not configured; deferring booking %s", booking_id)
        return "twilio_unconfigured"

    body = (
        f"Hello {booking.customer.name}, this is a reminder for your appointment on "
        f"{booking.appointment_at:%Y-%m-%d %H:%M} for {booking.service}."
    )
    client.messages.create(from_=_sender_number(), body=body, to=booking.customer.phone)
    BookingService.mark_reminder_sent(booking_id)
    logger.info("reminder: sent for booking_id=%s to %s", booking_id, _mask(booking.customer.phone))
    return "sent"
