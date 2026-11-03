"""OpenAI integration: business-context isolation (mocked) and optional live test."""

from __future__ import annotations

import json
import os

import pytest

from services.ai_service import AIService
from tests.helpers import FakeOpenAI

SENDER = "whatsapp:+27831234567"


class _ContextEchoClient:
    """Fake client that answers using ONLY the injected BUSINESS CONTEXT."""

    def __init__(self):
        outer = self

        class _Completions:
            def create(self, model, response_format, messages):
                context = {}
                for m in messages:
                    if m["role"] == "system" and m["content"].startswith("BUSINESS CONTEXT"):
                        context = json.loads(m["content"].split("\n", 1)[1])
                services = [s["name"] for s in context.get("services", [])]
                answer = f"We offer: {', '.join(services)}."
                return outer._completion(json.dumps({"action": "get_services", "message": answer}))

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()

    @staticmethod
    def _completion(content):
        return type("C", (), {
            "choices": [type("Ch", (), {"message": type("M", (), {"content": content})()})()],
            "usage": type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})(),
        })()


def test_business_context_is_tenant_isolated(make_business):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])

    ai = AIService(client=_ContextEchoClient())
    answer_a = ai.respond(biz_a, SENDER, "What services do you offer?").message
    answer_b = ai.respond(biz_b, SENDER, "What services do you offer?").message

    assert "PLC Programming" in answer_a and "Photography" not in answer_a
    assert "Photography" in answer_b and "PLC Programming" not in answer_b


def test_malformed_response_falls_back(make_business):
    biz = make_business(name="Business A")
    ai = AIService(client=FakeOpenAI(content="not json"))
    assert ai.respond(biz, SENDER, "hi").action == "handoff_human"


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="No real OPENAI_API_KEY configured; live OpenAI test skipped")
def test_live_openai_uses_business_context(make_business):
    biz = make_business(name="Business A", services=["PLC Programming", "Factory Automation"])
    ai = AIService()  # real client from OPENAI_API_KEY
    result = ai.respond(biz, SENDER, "What services do you offer?")
    assert result.message
    # A real answer should reference the configured services.
    assert ("PLC" in result.message) or ("Factory" in result.message)
