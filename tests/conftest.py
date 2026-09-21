"""Shared pytest fixtures.

Sets up an isolated temporary SQLite database and required environment
variables *before* the application modules are imported, so tests never touch a
real database or make external calls.
"""

from __future__ import annotations

import os
import tempfile

# Configure the environment before importing any application module.
os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC" + "x" * 32)
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_auth_token")
os.environ.setdefault("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
os.environ.setdefault("OWNER_PHONE_NUMBER", "whatsapp:+10000000000")
# Ensure no live OpenAI calls unless a test explicitly injects a fake client.
os.environ["OPENAI_API_KEY"] = ""

_db_fd, _db_path = tempfile.mkstemp(suffix="_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

import pytest  # noqa: E402

import models  # noqa: E402,F401  (registers all tables on Base.metadata)
from database import Base, engine, get_session  # noqa: E402
from models.business import Business  # noqa: E402
from models.faq import FAQ  # noqa: E402
from models.service import Service  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    """Give every test a clean schema and clear any in-memory conversation state."""
    import sys

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app_module = sys.modules.get("app")
    if app_module is not None:
        app_module.conversation_service._states.clear()
    yield


@pytest.fixture
def make_business():
    """Factory that creates a business (plus optional services/FAQs) and returns its id."""

    def _make(name="Test Business", services=None, faqs=None, booking_enabled=True, owner_phone=None):
        with get_session() as session:
            business = Business(name=name, booking_enabled=booking_enabled, owner_phone=owner_phone)
            session.add(business)
            session.flush()
            for service_name in services or []:
                session.add(Service(business_id=business.id, name=service_name, active=True))
            for question, answer in faqs or []:
                session.add(FAQ(business_id=business.id, question=question, answer=answer))
            session.flush()
            return business.id

    return _make
