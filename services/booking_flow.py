"""Deterministic, database-backed booking conversation (name -> date -> service)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select

from database import get_session
from models.booking_draft import BookingDraft
from models.business import Business
from services.booking_service import BookingService
from services.business_service import BusinessService

CANCEL_WORDS = {"cancel", "stop", "quit", "exit", "nevermind", "never mind"}
DRAFT_TTL = timedelta(hours=24)
DATE_EXAMPLE = "YYYY-MM-DD HH:MM (e.g. 2026-09-30 14:30) or DD/MM/YYYY HH:MM"
START_PROMPT = "Happy to help you book! What name should the booking be under?\n(Reply CANCEL at any time to stop.)"

DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I:%M%p", "%Y-%m-%d %H%M",
    "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %I:%M%p", "%d-%m-%Y %H:%M",
]
DATE_ONLY_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]


def business_now(business: Business) -> datetime:
    """Current wall-clock time in the business's timezone, as a naive datetime."""
    return datetime.now(business_zone(business)).replace(tzinfo=None)


def business_zone(business: Business) -> ZoneInfo:
    try:
        return ZoneInfo(business.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def parse_datetime(value: str) -> datetime | None:
    """Parse common customer date formats; a bare date defaults to 09:00."""
    value = " ".join(value.strip().upper().split()).replace(".", ":")
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    for fmt in DATE_ONLY_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(hour=9, minute=0)
        except ValueError:
            continue
    return None


class BookingFlow:
    """Collects booking details across messages and creates the booking at the end."""

    def __init__(self, on_booking_created=None) -> None:
        # Callback(business, booking) used to notify the owner; injected by the app.
        self.on_booking_created = on_booking_created

    def start(self, business: Business, phone: str) -> str:
        with get_session() as session:
            session.execute(delete(BookingDraft).where(BookingDraft.business_id == business.id, BookingDraft.phone == phone))
            session.add(BookingDraft(business_id=business.id, phone=phone, step="ask_name"))
        return START_PROMPT

    def has_active_draft(self, business: Business, phone: str) -> bool:
        return self._load(business.id, phone) is not None

    def handle(self, business: Business, phone: str, message: str) -> str | None:
        """Advance an open booking. Returns None when the customer has no open booking."""
        draft = self._load(business.id, phone)
        if draft is None:
            return None

        text = message.strip()
        if text.lower().strip(" .!") in CANCEL_WORDS:
            self._clear(business.id, phone)
            return "No problem, I've cancelled that booking request. Is there anything else I can help with?"

        if draft.step == "ask_name":
            if len(text) < 2 or len(text) > 160:
                return "Please send the name the booking should be under."
            self._update(draft.id, name=text, step="ask_date")
            return f"Thanks {text}! What date and time would you like?\nPlease use {DATE_EXAMPLE}."

        if draft.step == "ask_date":
            parsed = parse_datetime(text)
            if parsed is None:
                return f"Sorry, I couldn't read that date. Please use {DATE_EXAMPLE}."
            if parsed <= business_now(business):
                return "That time is in the past. Please send a future date and time."
            self._update(draft.id, appointment_at=parsed, step="ask_service")
            services = BusinessService.get_services(business.id, active_only=True)
            if services:
                options = "\n".join(f"{i}. {s.name}" for i, s in enumerate(services, start=1))
                return f"Great. Which service do you need? Reply with a number or name:\n{options}"
            return "Great. What service do you need?"

        if draft.step == "ask_service":
            service_name = self._match_service(business.id, text)
            if service_name is None:
                services = BusinessService.get_services(business.id, active_only=True)
                options = "\n".join(f"{i}. {s.name}" for i, s in enumerate(services, start=1))
                return f"Please choose one of these services (reply with the number or name):\n{options}"
            booking = BookingService.create_booking(business.id, draft.name or "", draft.appointment_at, phone, service_name)
            self._clear(business.id, phone)
            if self.on_booking_created:
                self.on_booking_created(business, booking)
            return (
                "✅ Booking request received!\n\n"
                f"Name: {draft.name}\n"
                f"Date: {draft.appointment_at:%Y-%m-%d %H:%M}\n"
                f"Service: {service_name}\n\n"
                "The team will confirm with you shortly."
            )

        # Unknown step: drop the draft and fall back to normal handling.
        self._clear(business.id, phone)
        return None

    @staticmethod
    def _match_service(business_id: int, text: str) -> str | None:
        services = BusinessService.get_services(business_id, active_only=True)
        if not services:
            return text if text else None
        if text.isdigit() and 1 <= int(text) <= len(services):
            return services[int(text) - 1].name
        lowered = text.lower()
        exact = [s for s in services if s.name.lower() == lowered]
        if exact:
            return exact[0].name
        partial = [s for s in services if lowered in s.name.lower() or s.name.lower() in lowered]
        return partial[0].name if len(partial) == 1 else None

    @staticmethod
    def _load(business_id: int, phone: str) -> BookingDraft | None:
        with get_session() as session:
            draft = session.scalar(select(BookingDraft).where(BookingDraft.business_id == business_id, BookingDraft.phone == phone))
            if draft is not None and datetime.utcnow() - draft.updated_at > DRAFT_TTL:
                session.delete(draft)
                return None
            return draft

    @staticmethod
    def _update(draft_id: int, **fields) -> None:
        with get_session() as session:
            draft = session.get(BookingDraft, draft_id)
            for key, value in fields.items():
                setattr(draft, key, value)

    @staticmethod
    def _clear(business_id: int, phone: str) -> None:
        with get_session() as session:
            session.execute(delete(BookingDraft).where(BookingDraft.business_id == business_id, BookingDraft.phone == phone))

