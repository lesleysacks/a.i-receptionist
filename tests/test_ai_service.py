"""AI service tests: mocked success, provider failure, bad output, and no-key fallback."""

from __future__ import annotations

import json

from services.ai_service import AIService
from tests.helpers import FakeOpenAI

SENDER = "whatsapp:+27831234567"


def test_successful_ai_response(make_business):
    business_id = make_business(name="Genai", services=["PLC Programming"])
    payload = json.dumps({"action": "answer_question", "message": "We offer PLC Programming."})
    service = AIService(client=FakeOpenAI(content=payload))

    result = service.respond(business_id, SENDER, "What do you offer?")
    assert result.action == "answer_question"
    assert result.message == "We offer PLC Programming."


def test_provider_failure_falls_back_safely(make_business):
    business_id = make_business(name="Genai", services=["PLC Programming"])
    service = AIService(client=FakeOpenAI(exc=RuntimeError("provider down")))

    result = service.respond(business_id, SENDER, "Are you open?")
    assert result.action == "handoff_human"
    assert "team member" in result.message.lower()


def test_timeout_falls_back_safely(make_business):
    business_id = make_business(name="Genai")
    service = AIService(client=FakeOpenAI(exc=TimeoutError("timed out")))

    result = service.respond(business_id, SENDER, "Hello?")
    assert result.action == "handoff_human"
    # Customer never sees the internal error text.
    assert "timed out" not in result.message.lower()


def test_invalid_json_falls_back_safely(make_business):
    business_id = make_business(name="Genai")
    service = AIService(client=FakeOpenAI(content="this is not json"))

    result = service.respond(business_id, SENDER, "Hi")
    assert result.action == "handoff_human"


def test_missing_api_key_falls_back_safely(make_business):
    business_id = make_business(name="Genai")
    # No client injected and OPENAI_API_KEY is empty (set in conftest).
    service = AIService()

    result = service.respond(business_id, SENDER, "Hi")
    assert result.action == "handoff_human"
