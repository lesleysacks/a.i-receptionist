"""Database integrity: SQLite foreign-key enforcement."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from database import engine, get_session
from models.booking import Booking
from models.customer import Customer


def test_foreign_keys_are_enabled():
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_booking_with_invalid_business_is_rejected():
    with pytest.raises(IntegrityError):
        with get_session() as session:
            session.add(Booking(
                business_id=999999,
                customer_id=999999,
                appointment_at=datetime(2026, 12, 30, 14, 0),
                service="PLC Programming",
            ))


def test_customer_with_invalid_business_is_rejected():
    with pytest.raises(IntegrityError):
        with get_session() as session:
            session.add(Customer(business_id=999999, name="Nobody", phone="whatsapp:+27000000000"))


def test_valid_references_are_accepted(make_business):
    business_id = make_business(name="Business A")
    with get_session() as session:
        customer = Customer(business_id=business_id, name="Alice", phone="whatsapp:+27831234567")
        session.add(customer)
        session.flush()
        session.add(Booking(
            business_id=business_id,
            customer_id=customer.id,
            appointment_at=datetime(2026, 12, 30, 14, 0),
            service="PLC Programming",
        ))
    with get_session() as session:
        assert len(session.scalars(select(Booking)).all()) == 1