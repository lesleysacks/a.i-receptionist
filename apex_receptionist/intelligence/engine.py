"""Turn a confident classification plus tenant facts into a reply.

Never invents hours, prices, contact details, or availability.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex_receptionist.intelligence import templates
from apex_receptionist.intelligence.types import Classification, Intent, TenantFacts


@dataclass(frozen=True)
class DeterministicReply:
    handled: bool
    message: str
    response_type: str
    outcome: str


def respond(classification: Classification, facts: TenantFacts) -> DeterministicReply:
    """Return a fact-based reply, or ``handled=False`` so the caller may use AI."""
    intent = classification.intent
    extracted = classification.extracted or {}
    service_name = extracted.get("service_name")

    if intent == Intent.GREETING:
        return DeterministicReply(True, templates.greeting(facts), "greeting", "success")
    if intent == Intent.OPENING_HOURS:
        message = templates.opening_hours(facts)
        return _maybe_missing(message, "opening_hours", facts)
    if intent == Intent.LOCATION:
        message = templates.location(facts)
        return _maybe_missing(message, "location", facts)
    if intent == Intent.CONTACT:
        message = templates.contact(facts)
        return _maybe_missing(message, "contact", facts)
    if intent == Intent.SERVICES:
        message = templates.services(facts, service_name)
        return _maybe_missing(message, "services", facts)
    if intent == Intent.PRICING:
        message = templates.pricing(facts, service_name)
        return _maybe_missing(message, "pricing", facts)
    if intent == Intent.GENERAL_QUESTION and extracted.get("faq_answer"):
        return DeterministicReply(True, templates.faq_answer(extracted["faq_answer"]), "faq", "success")
    if intent == Intent.HUMAN_REQUEST:
        return DeterministicReply(True, templates.human_handoff(facts), "handoff", "handoff")
    return DeterministicReply(False, "", "unhandled", "fallback")


def _maybe_missing(message: str, response_type: str, facts: TenantFacts) -> DeterministicReply:
    missing = "don't have" in message.lower() and "on file" in message.lower()
    if missing:
        return DeterministicReply(True, message, response_type, "missing_information")
    return DeterministicReply(True, message, response_type, "success")
