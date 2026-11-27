"""Tenant-aware booking persistence services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from database import get_session
from models.booking import Booking
from models.customer import Customer


class BookingService:
    """Create and query bookings without exposing database details to routes."""

    @staticmethod
    def create_booking(business_id: int, name: str, appointment_at: datetime, phone: str, service: str) -> Booking:
        """Create an appointment and upsert its customer for the given tenant."""
        with get_session() as session:
            customer = session.scalar(select(Customer).where(Customer.business_id == business_id, Customer.phone == phone))
            if customer is None:
                customer = Customer(business_id=business_id, name=name, phone=phone)
                session.add(customer)
            elif name:
                customer.name = name
            booking = Booking(business_id=business_id, customer=customer, appointment_at=appointment_at, service=service)
            session.add(booking)
            session.flush()
            return booking

    @staticmethod
    def bookings_due_for_reminder(now_utc: datetime | None = None) -> list[Booking]:
        """Return unsent bookings starting within the next 24 hours of each business's local time.

        ``appointment_at`` is stored as naive wall-clock time in the business timezone.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        now_utc = now_utc or datetime.now(timezone.utc)
        with get_session() as session:
            candidates = list(session.scalars(
                select(Booking).options(joinedload(Booking.customer), joinedload(Booking.business)).where(
                    Booking.reminder_sent.is_(False),
                    # Coarse bound (+/- 1 day covers every UTC offset); exact check below.
                    Booking.appointment_at >= now_utc.replace(tzinfo=None) - timedelta(days=1),
                    Booking.appointment_at <= now_utc.replace(tzinfo=None) + timedelta(days=2),
                )
            ))
        due = []
        for booking in candidates:
            try:
                zone = ZoneInfo(booking.business.timezone or "UTC")
            except ZoneInfoNotFoundError:
                zone = ZoneInfo("UTC")
            local_now = now_utc.astimezone(zone).replace(tzinfo=None)
            if local_now <= booking.appointment_at <= local_now + timedelta(hours=24):
                due.append(booking)
        return due

    @staticmethod
    def list_bookings(business_id: int | None = None) -> list[Booking]:
        """Return bookings (optionally for one tenant), newest first."""
        with get_session() as session:
            statement = select(Booking).options(joinedload(Booking.customer)).order_by(Booking.created_at.desc())
            if business_id is not None:
                statement = statement.where(Booking.business_id == business_id)
            return list(session.scalars(statement))

    @staticmethod
    def mark_reminder_sent(booking_id: int) -> None:
        """Mark a successfully delivered reminder so it is not resent."""
        with get_session() as session:
            booking = session.get(Booking, booking_id)
            if booking:
                booking.reminder_sent = True
