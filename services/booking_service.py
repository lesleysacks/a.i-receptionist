"""Tenant-aware booking persistence services."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from database import get_session
from models.booking import Booking
from models.customer import Customer


class BookingService:
    """Create and query bookings without exposing database details to routes."""

    @staticmethod
    def create_booking(business_id: int, name: str, appointment_at: datetime, phone: str, service: str) -> Booking:
        """Create an appointment and upsert its customer for the given tenant.

        Idempotent: an identical booking (same business, customer, time and
        service) is returned instead of being duplicated, so a retried or
        double-sent confirmation does not create two bookings.
        """
        with get_session() as session:
            customer = session.scalar(select(Customer).where(Customer.business_id == business_id, Customer.phone == phone))
            if customer is None:
                customer = Customer(business_id=business_id, name=name, phone=phone)
                session.add(customer)
                session.flush()
            elif name:
                customer.name = name

            existing = session.scalar(
                select(Booking).where(
                    Booking.business_id == business_id,
                    Booking.customer_id == customer.id,
                    Booking.appointment_at == appointment_at,
                    Booking.service == service,
                )
            )
            if existing is not None:
                return existing

            booking = Booking(business_id=business_id, customer=customer, appointment_at=appointment_at, service=service)
            session.add(booking)
            session.flush()
            return booking

    @staticmethod
    def bookings_due_for_reminder(now: datetime) -> list[Booking]:
        """Return unsent bookings occurring within the following 24 hours."""
        with get_session() as session:
            return list(session.scalars(
                select(Booking).options(joinedload(Booking.customer)).where(
                    Booking.reminder_sent.is_(False),
                    Booking.appointment_at >= now,
                    Booking.appointment_at <= now + timedelta(hours=24),
                )
            ))

    @staticmethod
    def list_bookings(business_id: int | None = None) -> list[Booking]:
        """Return bookings newest first.

        When ``business_id`` is provided the query is scoped to that tenant at the
        database level. Callers serving an authenticated admin MUST pass their
        business id so one tenant can never read another tenant's leads.
        """
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
