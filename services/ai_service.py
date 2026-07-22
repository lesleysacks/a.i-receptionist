"""OpenAI-backed business knowledge engine with tenant-safe conversation memory."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI
from sqlalchemy import select

from database import get_session
from models.conversation import Conversation
from models.customer import Customer
from models.knowledge_document import KnowledgeDocument
from services.context_builder import ContextBuilder

logger = logging.getLogger(__name__)
Action = Literal["answer_question", "start_booking", "handoff_human", "get_business_info", "get_services", "get_hours", "get_contact_details"]
MAX_HISTORY_MESSAGES = 15


@dataclass(frozen=True)
class AIResponse:
    """Safe, backend-controlled result of a customer knowledge request."""

    message: str
    action: Action
    customer_id: int


class AIService:
    """Answer customer messages using only tenant context and recent history."""

    def __init__(self, context_builder: ContextBuilder | None = None, client: OpenAI | None = None) -> None:
        self.context_builder = context_builder or ContextBuilder()
        self.client = client
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    def respond(self, business_id: int, sender: str, message: str, channel: str = "whatsapp") -> AIResponse:
        """Persist an inbound message, request structured AI output, then persist it."""
        customer = self._get_or_create_customer(business_id, sender)
        history = self._history(business_id, customer.id)
        self.record_message(business_id, customer.id, channel, "user", message)
        try:
            result = self._ask_model(business_id, customer.id, message, history)
        except Exception:
            logger.exception("AI fallback used for business_id=%s customer_id=%s", business_id, customer.id)
            result = AIResponse(
                message="Thanks for your message. A team member will assist you shortly.",
                action="handoff_human",
                customer_id=customer.id,
            )
        self.record_message(business_id, customer.id, channel, "assistant", result.message)
        return result

    def record_booking_exchange(self, business_id: int, sender: str, customer_message: str, assistant_message: str, channel: str = "whatsapp") -> None:
        """Persist deterministic booking-form messages without calling the model."""
        customer = self._get_or_create_customer(business_id, sender)
        self.record_message(business_id, customer.id, channel, "user", customer_message)
        self.record_message(business_id, customer.id, channel, "assistant", assistant_message)

    def record_message(self, business_id: int, customer_id: int | None, channel: str, role: str, content: str) -> None:
        """Store one inbound or outbound message for future sliding-window context."""
        with get_session() as session:
            session.add(Conversation(
                business_id=business_id,
                customer_id=customer_id,
                channel=channel,
                role=role,
                content=content,
            ))

    def _ask_model(self, business_id: int, customer_id: int, current_message: str, history: list[dict[str, str]]) -> AIResponse:
        started = time.perf_counter()
        context = self.context_builder.build(business_id)
        documents = self._knowledge_documents(business_id)
        client = self._client()
        completion = client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._system_instructions()},
                {"role": "system", "content": "BUSINESS CONTEXT\n" + json.dumps(context, ensure_ascii=False)},
                {"role": "system", "content": "KNOWLEDGE DOCUMENTS\n" + json.dumps(documents, ensure_ascii=False)},
                *history,
                {"role": "user", "content": current_message},
            ],
        )
        raw = completion.choices[0].message.content or "{}"
        parsed = self._parse_response(raw)
        usage = getattr(completion, "usage", None)
        logger.info(
            "AI request completed business_id=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s",
            business_id,
            (time.perf_counter() - started) * 1000,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )
        return AIResponse(message=parsed["message"], action=parsed["action"], customer_id=customer_id)

    def _client(self) -> OpenAI:
        if self.client is not None:
            return self.client
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.client = OpenAI()
        return self.client

    def _get_or_create_customer(self, business_id: int, phone: str) -> Customer:
        with get_session() as session:
            customer = session.scalar(select(Customer).where(Customer.business_id == business_id, Customer.phone == phone))
            if customer is None:
                customer = Customer(business_id=business_id, phone=phone)
                session.add(customer)
                session.flush()
            return customer

    def _history(self, business_id: int, customer_id: int) -> list[dict[str, str]]:
        with get_session() as session:
            records = list(session.scalars(
                select(Conversation).where(
                    Conversation.business_id == business_id,
                    Conversation.customer_id == customer_id,
                ).order_by(Conversation.timestamp.desc()).limit(MAX_HISTORY_MESSAGES)
            ))
        records.reverse()
        return [{"role": item.role, "content": item.content} for item in records]

    @staticmethod
    def _knowledge_documents(business_id: int) -> list[dict[str, str]]:
        """Load document text directly today; retrieval can replace this seam later."""
        with get_session() as session:
            documents = session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.business_id == business_id)).all()
            return [{"filename": item.filename, "content": item.content or ""} for item in documents]

    @staticmethod
    def _system_instructions() -> str:
        return """You are a business receptionist. Use only the supplied BUSINESS CONTEXT,
KNOWLEDGE DOCUMENTS, recent conversation, and the customer's current message. Do not invent
facts, availability, pricing, policies, or contact details. If the information is missing,
choose handoff_human and politely say that a team member will assist. Reply in the configured
business language when it is available in context. Return JSON only with exactly:
{"action":"answer_question|start_booking|handoff_human|get_business_info|get_services|get_hours|get_contact_details","message":"customer-facing reply"}.
Choose start_booking whenever the customer wants an appointment, availability, a visit, or a technician.
For start_booking, ask the customer to share their name so the backend booking flow can continue.
Never claim that a booking has been saved; the backend handles booking collection."""

    @staticmethod
    def _parse_response(raw: str) -> dict[str, Action | str]:
        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("OpenAI did not return valid JSON") from exc
        action = payload.get("action")
        message = payload.get("message")
        allowed_actions = {"answer_question", "start_booking", "handoff_human", "get_business_info", "get_services", "get_hours", "get_contact_details"}
        if action not in allowed_actions or not isinstance(message, str) or not message.strip():
            raise ValueError("OpenAI returned an invalid response schema")
        return {"action": action, "message": message.strip()}
