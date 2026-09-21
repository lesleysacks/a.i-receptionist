"""Test doubles for the AI seam (kept out of conftest to avoid double-import)."""

from __future__ import annotations

from services.ai_service import AIResponse


class FakeAI:
    """Minimal stand-in for AIService used by conversation FSM tests.

    `respond` is only reached for free-form questions; the deterministic booking
    flow never calls it. Records are captured in-memory for assertions.
    """

    def __init__(self, action="answer_question", message="Here is some info."):
        self._response = AIResponse(message=message, action=action, customer_id=1)
        self.recorded: list[tuple] = []
        self.respond_calls: list[tuple] = []

    def respond(self, business_id, sender, message, channel="whatsapp"):
        self.respond_calls.append((business_id, sender, message))
        return self._response

    def record_booking_exchange(self, business_id, sender, customer_message, assistant_message, channel="whatsapp"):
        self.recorded.append((business_id, sender, customer_message, assistant_message))


def make_completion(content: str):
    """Build a minimal object shaped like an OpenAI chat completion."""

    class _Msg:
        def __init__(self, c):
            self.content = c

    class _Choice:
        def __init__(self, c):
            self.message = _Msg(c)

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 5

    class _Completion:
        def __init__(self, c):
            self.choices = [_Choice(c)]
            self.usage = _Usage()

    return _Completion(content)


class FakeOpenAI:
    """Fake OpenAI client whose behaviour is controlled per test."""

    def __init__(self, content=None, exc=None):
        outer = self

        class _Completions:
            def create(self, **kwargs):
                if outer._exc is not None:
                    raise outer._exc
                return make_completion(outer._content)

        class _Chat:
            completions = _Completions()

        self._content = content
        self._exc = exc
        self.chat = _Chat()
