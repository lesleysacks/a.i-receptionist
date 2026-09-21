"""Twilio webhook signature validation and TwiML response tests."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest
from twilio.request_validator import RequestValidator

BASE_URL = "http://localhost"
WEBHOOK_URL = BASE_URL + "/whatsapp"


@pytest.fixture
def client(make_business):
    import app as app_module

    make_business(name="Webhook Co", services=["PLC Programming"])
    return app_module.app.test_client()


def _sign(params):
    validator = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
    return validator.compute_signature(WEBHOOK_URL, params)


def test_missing_signature_is_rejected(client):
    resp = client.post("/whatsapp", data={"Body": "hi", "From": "whatsapp:+27831234567"}, base_url=BASE_URL)
    assert resp.status_code == 403


def test_invalid_signature_is_rejected(client):
    resp = client.post(
        "/whatsapp",
        data={"Body": "hi", "From": "whatsapp:+27831234567"},
        headers={"X-Twilio-Signature": "definitely-wrong"},
        base_url=BASE_URL,
    )
    assert resp.status_code == 403


def test_valid_signature_returns_valid_twiml(client):
    params = {"Body": "I want to book an appointment", "From": "whatsapp:+27831234567"}
    resp = client.post(
        "/whatsapp",
        data=params,
        headers={"X-Twilio-Signature": _sign(params)},
        base_url=BASE_URL,
    )
    assert resp.status_code == 200

    root = ET.fromstring(resp.get_data(as_text=True))
    assert root.tag == "Response"
    message = root.find("Message")
    assert message is not None and message.text
