import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_db_dir = tempfile.mkdtemp()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_db_dir}/test.db",
    "TWILIO_ACCOUNT_SID": "ACtest",
    "TWILIO_AUTH_TOKEN": "test-token",
    "TWILIO_WHATSAPP_NUMBER": "whatsapp:+14155238886",
    "ADMIN_PASSWORD": "secret",
    "RUN_SCHEDULER": "false",
    "TWILIO_VALIDATE_SIGNATURE": "true",
    "OWNER_PHONE_NUMBER": "",
    "PUBLIC_BASE_URL": "",
})
os.environ.pop("OPENAI_API_KEY", None)

import app as app_module  # noqa: E402
from database import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app_module.ai_service.client = None
    yield


@pytest.fixture
def twilio(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(app_module, "client", fake)
    return fake


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.fixture
def send(client):
    """Post a correctly signed Twilio webhook and return the reply text."""
    from twilio.request_validator import RequestValidator

    validator = RequestValidator("test-token")

    def _send(body, sender="whatsapp:+27111111111"):
        data = {"Body": body, "From": sender}
        url = "http://localhost/whatsapp"
        signature = validator.compute_signature(url, data)
        resp = client.post("/whatsapp", data=data, headers={"X-Twilio-Signature": signature})
        assert resp.status_code == 200, resp.data
        import re
        match = re.search(r"<Message>(.*)</Message>", resp.data.decode(), re.S)
        return match.group(1) if match else ""

    return _send


ADMIN = {"Authorization": "Bearer secret"}
