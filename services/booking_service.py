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
    def list_bookings() -> list[Booking]:
        """Return all bookings for the legacy dashboard, newest first."""
        with get_session() as session:
            return list(session.scalars(
                select(Booking).options(joinedload(Booking.customer)).order_by(Booking.created_at.desc())
            ))

    @staticmethod
    def mark_reminder_sent(booking_id: int) -> None:
        """Mark a successfully delivered reminder so it is not resent."""
        with get_session() as session:
            booking = session.get(Booking, booking_id)
            if booking:
                booking.reminder_sent = True
