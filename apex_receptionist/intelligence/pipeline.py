"""Idle-message decision pipeline: facts → classify → deterministic or AI.

Does not resolve tenants. ``business`` must already be the trusted tenant.
Does not call OpenAI; the conversation service invokes ``AIService`` only when
this pipeline returns ``PipelineDecision.AI``.
"""

from __future__ import annotations

import logging
import os
import time

from apex_receptionist.intelligence.classifier import ACT_THRESHOLD, BOOKING_THRESHOLD, classify
from apex_receptionist.intelligence.engine import respond as deterministic_respond
from apex_receptionist.intelligence.facts import facts_from_business
from apex_receptionist.intelligence.templates import ai_unavailable
from apex_receptionist.intelligence.types import (
    Classification,
    Intent,
    PipelineDecision,
    PipelineResult,
)

logger = logging.getLogger(__name__)


class ResponsePipeline:
    """Code-first interpreter for idle receptionist messages."""

    def decide(self, business, message: str) -> PipelineResult:
        started = time.perf_counter()
        facts = facts_from_business(business)
        if facts.business_id != int(business.id):
            raise RuntimeError("Tenant facts do not match the resolved business.")
        classification = classify(message, facts)
        result = self._route(facts, classification)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        finished = PipelineResult(
            decision=result.decision,
            message=result.message,
            classification=classification,
            response_type=result.response_type,
            ai_required=result.ai_required,
            outcome=result.outcome,
            duration_ms=duration_ms,
        )
        logger.info(
            "response pipeline",
            extra={
                "event": "response_pipeline",
                "business_id": facts.business_id,
                "intent": classification.intent.value,
                "classification_method": classification.method,
                "response_type": finished.response_type,
                "ai_required": finished.ai_required,
                "outcome": finished.outcome,
                "latency_ms": duration_ms,
            },
        )
        return finished

    def _route(self, facts, classification: Classification) -> PipelineResult:
        intent = classification.intent
        confidence = classification.confidence

        if intent == Intent.BOOKING and confidence >= BOOKING_THRESHOLD:
            if facts.booking_enabled:
                return _partial(
                    PipelineDecision.START_BOOKING,
                    None,
                    "booking",
                    False,
                    "success",
                    classification,
                )
            return _partial(
                PipelineDecision.DETERMINISTIC,
                "Bookings aren't available right now, but I'm happy to answer any questions.",
                "booking_disabled",
                False,
                "success",
                classification,
            )

        if confidence >= ACT_THRESHOLD:
            reply = deterministic_respond(classification, facts)
            if reply.handled:
                decision = (
                    PipelineDecision.HANDOFF
                    if reply.response_type == "handoff"
                    else PipelineDecision.DETERMINISTIC
                )
                return _partial(
                    decision,
                    reply.message,
                    reply.response_type,
                    False,
                    reply.outcome,
                    classification,
                )

        if not _ai_enabled():
            return _partial(
                PipelineDecision.HANDOFF,
                ai_unavailable(facts),
                "ai_disabled",
                False,
                "handoff",
                classification,
            )

        return _partial(
            PipelineDecision.AI,
            None,
            "ai_fallback",
            True,
            "fallback",
            classification,
        )


def _ai_enabled() -> bool:
    return os.getenv("APEX_AI_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _partial(decision, message, response_type, ai_required, outcome, classification) -> PipelineResult:
    return PipelineResult(
        decision=decision,
        message=message,
        classification=classification,
        response_type=response_type,
        ai_required=ai_required,
        outcome=outcome,
        duration_ms=0.0,
    )
