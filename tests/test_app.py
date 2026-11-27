import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import app as app_module
from services.booking_flow import parse_datetime
from services.booking_service import BookingService
from tests.conftest import ADMIN


def future(days=3):
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d 10:30")


def fake_openai(action, message):
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"action": action, "message": message})))],
        usage=None,
    )
    fake = MagicMock()
    fake.chat.completions.create.return_value = completion
    return fake


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_rejects_unsigned_webhook(client):
    assert client.post("/whatsapp", data={"Body": "hi", "From": "whatsapp:+1"}).status_code == 403


def test_signature_uses_public_base_url(client, monkeypatch):
    from twilio.request_validator import RequestValidator
    monkeypatch.setattr(app_module, "PUBLIC_BASE_URL", "https://abc.ngrok.app")
    data = {"Body": "hi", "From": "whatsapp:+1"}
    sig = RequestValidator("test-token").compute_signature("https://abc.ngrok.app/whatsapp", data)
    assert client.post("/whatsapp", data=data, headers={"X-Twilio-Signature": sig}).status_code == 200


def test_signature_honours_forwarded_proto(client):
    from twilio.request_validator import RequestValidator
    data = {"Body": "hi", "From": "whatsapp:+1"}
    sig = RequestValidator("test-token").compute_signature("https://public.example/whatsapp", data)
    resp = client.post("/whatsapp", data=data, headers={
        "X-Twilio-Signature": sig, "X-Forwarded-Proto": "https", "X-Forwarded-Host": "public.example"})
    assert resp.status_code == 200


def test_full_booking_without_openai(send, twilio, client):
    client.put("/admin/business", json={"owner_phone": "+27 82 000 0000", "timezone": "Africa/Johannesburg"}, headers=ADMIN)
    client.post("/admin/services", json={"name": "Installation"}, headers=ADMIN)
    client.post("/admin/services", json={"name": "Repairs"}, headers=ADMIN)

    assert "name" in send("I want to book").lower()
    assert "date" in send("John Smith").lower()
    assert "past" in send("2001-01-01 10:00")
    reply = send(future())
    assert "1. Installation" in reply and "2. Repairs" in reply
    assert "choose" in send("Gardening").lower()
    reply = send("2")
    assert "Booking request received" in reply and "Repairs" in reply

    bookings = BookingService.list_bookings()
    assert len(bookings) == 1 and bookings[0].customer.name == "John Smith"
    twilio.messages.create.assert_called_once()
    kwargs = twilio.messages.create.call_args.kwargs
    assert kwargs["to"] == "whatsapp:+27820000000"
    assert "John Smith" in kwargs["body"]


def test_booking_state_survives_restart(send, twilio, monkeypatch):
    send("book please")
    # Simulate a new process: the flow keeps no in-memory state.
    monkeypatch.setattr(app_module, "booking_flow", app_module.BookingFlow(on_booking_created=app_module.notify_owner))
    assert "Thanks Jane" in send("Jane")


def test_cancel_booking(send):
    send("book")
    assert "cancelled" in send("cancel")
    assert "team member" in send("what are your hours?")


def test_openai_answer_and_booking(send):
    app_module.ai_service.client = fake_openai("answer_question", "We open at 8am.")
    assert send("When do you open?") == "We open at 8am."
    app_module.ai_service.client = fake_openai("start_booking", "Sure!")
    assert "What name" in send("Can someone come out on Tuesday?")
    assert "Thanks Sam" in send("Sam")


def test_openai_failure_falls_back(send):
    broken = MagicMock()
    broken.chat.completions.create.side_effect = RuntimeError("down")
    app_module.ai_service.client = broken
    assert "team member" in send("hello")


def test_booking_disabled(send, client):
    client.put("/admin/business", json={"booking_enabled": False}, headers=ADMIN)
    assert "isn't available" in send("book")


def test_admin_requires_auth(client):
    assert client.get("/admin/business").status_code == 401
    assert client.get("/leads").status_code == 401
    assert client.get("/admin/business", headers=ADMIN).status_code == 200
    assert client.get("/leads", headers=ADMIN).status_code == 200


def test_admin_validation(client):
    assert client.put("/admin/business", json={"booking_enabled": "false"}, headers=ADMIN).status_code == 400
    assert client.put("/admin/business", json={"timezone": "Mars/Base"}, headers=ADMIN).status_code == 400
    assert client.post("/admin/services", json={"name": "X", "active": "nope"}, headers=ADMIN).status_code == 400
    resp = client.post("/admin/services", json={"name": "X", "active": "false"}, headers=ADMIN)
    assert resp.status_code == 201 and resp.json["active"] is False


def test_reminders(send, twilio):
    send("book"); send("Ann")
    soon = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")
    send(soon); send("Consultation")
    twilio.reset_mock()
    app_module.send_reminders()
    twilio.messages.create.assert_called_once()
    assert "reminder" in twilio.messages.create.call_args.kwargs["body"]
    app_module.send_reminders()
    twilio.messages.create.assert_called_once()  # not resent


def test_parse_datetime():
    assert parse_datetime("2026-09-30 14:30") == datetime(2026, 9, 30, 14, 30)
    assert parse_datetime("30/09/2026 2:30 pm") == datetime(2026, 9, 30, 14, 30)
    assert parse_datetime("2026-09-30") == datetime(2026, 9, 30, 9, 0)
    assert parse_datetime("next tuesday") is None
