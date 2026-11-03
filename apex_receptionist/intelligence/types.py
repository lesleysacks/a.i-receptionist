"""Shared types for intent classification and the response pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class Intent(str, Enum):
    GREETING = "GREETING"
    OPENING_HOURS = "OPENING_HOURS"
    LOCATION = "LOCATION"
    CONTACT = "CONTACT"
    SERVICES = "SERVICES"
    PRICING = "PRICING"
    BOOKING = "BOOKING"
    GENERAL_QUESTION = "GENERAL_QUESTION"
    HUMAN_REQUEST = "HUMAN_REQUEST"
    UNKNOWN = "UNKNOWN"


class PipelineDecision(str, Enum):
    START_BOOKING = "start_booking"
    DETERMINISTIC = "deterministic"
    HANDOFF = "handoff"
    AI = "ai"


@dataclass(frozen=True)
class Classification:
    intent: Intent
    confidence: float
    method: str
    extracted: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceFact:
    name: str
    description: str | None
    price: Decimal | None


@dataclass(frozen=True)
class FaqFact:
    question: str
    answer: str


@dataclass(frozen=True)
class TenantFacts:
    """Approved, tenant-scoped facts. Never mix businesses in one instance."""

    business_id: int
    name: str
    opening_hours: str | None
    address: str | None
    city: str | None
    country: str | None
    phone: str | None
    email: str | None
    website: str | None
    currency: str
    booking_enabled: bool
    services: tuple[ServiceFact, ...]
    faqs: tuple[FaqFact, ...]


@dataclass(frozen=True)
class PipelineResult:
    decision: PipelineDecision
    message: str | None
    classification: Classification
    response_type: str
    ai_required: bool
    outcome: str
    duration_ms: float
