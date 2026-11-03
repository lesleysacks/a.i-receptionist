"""Shared pytest fixtures.

Sets up an isolated temporary SQLite database and required environment
variables *before* the application modules are imported, so tests never touch a
real database or make external calls.
"""

from __future__ import annotations

import os
import tempfile

# Configure the environment before importing any application module.
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC" + "x" * 32)
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_auth_token")
os.environ.setdefault("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
# No owner phone in tests so background notification jobs never attempt a real
# Twilio call (they resolve to a safe "no owner phone" no-op).
os.environ["OWNER_PHONE_NUMBER"] = ""
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# Ensure tests never target a real Redis unless a test opts in explicitly.
os.environ.pop("REDIS_URL", None)
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
from services import validators  # noqa: E402
from services.auth_service import AuthService  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    """Give every test a clean schema (also clears durable conversation state)."""
    import sys

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app_module = sys.modules.get("app")
    if app_module is not None:
        app_module.login_rate_limiter.reset()
    yield


@pytest.fixture
def make_business():
    """Factory that creates a business (plus optional services/FAQs) and returns its id."""

    def _make(name="Test Business", services=None, faqs=None, booking_enabled=True,
              owner_phone=None, whatsapp_number=None):
        with get_session() as session:
            business = Business(
                name=name,
                booking_enabled=booking_enabled,
                owner_phone=owner_phone,
                whatsapp_number=validators.normalize_phone(whatsapp_number) or None,
            )
            session.add(business)
            session.flush()
            for service_name in services or []:
                session.add(Service(business_id=business.id, name=service_name, active=True))
            for question, answer in faqs or []:
                session.add(FAQ(business_id=business.id, question=question, answer=answer))
            session.flush()
            return business.id

    return _make


@pytest.fixture
def make_admin():
    """Factory that creates an admin user for a business and returns (email, password)."""

    def _make(business_id, email="admin@example.com", password="password123"):
        AuthService.create_admin(business_id, email, password)
        return email, password

    return _make


@pytest.fixture
def app_client():
    """Return a Flask test client for the application."""
    import app as app_module

    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def login(client, email, password):
    """Log a test client in via the login form; returns the response."""
    return client.post("/login", data={"email": email, "password": password})


def whatsapp_post(client, body, sender, to, base_url="http://localhost"):
    """POST a Twilio webhook request with a valid signature."""
    from twilio.request_validator import RequestValidator

    url = base_url + "/whatsapp"
    params = {"Body": body, "From": sender}
    if to is not None:
        params["To"] = to
    validator = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
    signature = validator.compute_signature(url, params)
    return client.post(
        "/whatsapp",
        data=params,
        headers={"X-Twilio-Signature": signature},
        base_url=base_url,
    )
