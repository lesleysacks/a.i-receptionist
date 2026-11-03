"""Deterministic intent classification. No LLM calls."""

from __future__ import annotations

import re
from dataclasses import dataclass

from apex_receptionist.intelligence.types import Classification, Intent, TenantFacts
from apex_receptionist.services import validators

_GREETING_PREFIX = re.compile(
    r"^(hi|hello|hey|howdy|hiya|good morning|good afternoon|good evening)"
    r"( there)?[\s,!.]*",
    re.IGNORECASE,
)
_GREETING_ONLY = re.compile(
    r"^(hi|hello|hey|howdy|hiya|good morning|good afternoon|good evening)"
    r"( there)?[\s,!.?]*$",
    re.IGNORECASE,
)

_HUMAN_PHRASES = (
    "speak to a human",
    "talk to a human",
    "speak to a person",
    "talk to a person",
    "real person",
    "human please",
    "speak to someone",
    "talk to someone",
    "speak to an agent",
    "talk to an agent",
    "speak to a consultant",
    "talk to a consultant",
    "speak to an operator",
    "talk to an operator",
    "customer service",
    "speak to staff",
    "talk to staff",
)

_HOURS_PHRASES = (
    "opening hours",
    "opening times",
    "trading hours",
    "business hours",
    "operating hours",
    "your hours",
    "what time do you open",
    "what time do you close",
    "when are you open",
    "when do you open",
    "when do you close",
    "are you open",
    "are you closed",
)
_HOURS_SHORT = ("hours", "open", "closed")
_HOURS_QUESTION = re.compile(
    r"\b(what(?:'s| is| are)? (?:your |the )?(?:hours|opening)|when (?:are|do) you (?:open|close)|are you open)\b"
)

_LOCATION_PHRASES = (
    "where are you",
    "where is your",
    "your address",
    "your location",
    "how do i get there",
    "directions",
)
_LOCATION_SHORT = ("address", "location", "where")
_LOCATION_QUESTION = re.compile(r"\b(where (?:are|is)|(?:your |the )?(?:address|location)|directions)\b")

_CONTACT_PHRASES = (
    "contact details",
    "contact info",
    "phone number",
    "email address",
    "whatsapp number",
    "how can i contact",
    "how do i contact",
    "how do i reach",
)
_CONTACT_SHORT = ("contact", "email", "phone", "website")
_CONTACT_QUESTION = re.compile(
    r"\b(what(?:'s| is)? (?:your |the )?(?:email|phone|number|website)|(?:contact|reach) you)\b"
)

_SERVICE_PHRASES = (
    "what do you offer",
    "what services",
    "which services",
    "list of services",
    "services do you",
    "what do you do",
)
_SERVICE_SHORT = ("services", "service")
_SERVICE_QUESTION = re.compile(r"\b(what (?:do you offer|services)|which services|your services)\b")

_PRICE_PHRASES = (
    "how much",
    "what does it cost",
    "price list",
    "your prices",
    "your pricing",
    "cost of",
    "fee for",
)
_PRICE_SHORT = ("price", "prices", "pricing", "cost", "costs", "fee", "fees", "rate", "rates")
_PRICE_QUESTION = re.compile(
    r"\b(how much|what(?:'s| is| are)? (?:the |your )?(?:price|prices|pricing|cost|costs|fee|fees|rate|rates)|"
    r"(?:price|prices|pricing|cost)s? (?:of|for|list))\b"
)

_STOPWORDS = {
    "a", "an", "the", "is", "are", "do", "does", "you", "your", "what", "whats",
    "when", "where", "how", "can", "i", "we", "to", "of", "for", "and", "or",
    "please", "me", "my", "our", "about", "on", "in", "it", "this", "that",
}

ACT_THRESHOLD = 0.75
BOOKING_THRESHOLD = 0.85


@dataclass(frozen=True)
class _Candidate:
    intent: Intent
    confidence: float
    method: str
    extracted: dict


def classify(message: str, facts: TenantFacts | None = None) -> Classification:
    """Return the best intent for an idle customer message."""
    text = validators.normalize(message)
    if not text:
        return Classification(Intent.UNKNOWN, 0.0, "none")

    candidates: list[_Candidate] = []

    if validators.is_booking_intent(message):
        candidates.append(_Candidate(Intent.BOOKING, 0.95, "keyword", {}))

    if _matches_any(text, _HUMAN_PHRASES):
        candidates.append(_Candidate(Intent.HUMAN_REQUEST, 0.92, "keyword", {}))

    remainder = _strip_greeting(text)
    if _GREETING_ONLY.match(text):
        candidates.append(_Candidate(Intent.GREETING, 0.95, "keyword", {}))
    elif remainder != text and not remainder:
        candidates.append(_Candidate(Intent.GREETING, 0.9, "keyword", {}))

    target = remainder or text
    candidates.extend(_info_candidates(target, facts))

    if facts is not None:
        faq = _best_faq(text, facts)
        if faq is not None:
            candidates.append(faq)

    if not candidates:
        return Classification(Intent.UNKNOWN, 0.0, "none")

    chosen = _pick(candidates)
    return Classification(chosen.intent, chosen.confidence, chosen.method, chosen.extracted)


def _info_candidates(text: str, facts: TenantFacts | None) -> list[_Candidate]:
    found: list[_Candidate] = []
    service_name = _extract_service(text, facts) if facts else None
    extracted = {"service_name": service_name} if service_name else {}

    hours = _phrase_or_short(text, _HOURS_PHRASES, _HOURS_SHORT, _HOURS_QUESTION)
    if hours:
        found.append(_Candidate(Intent.OPENING_HOURS, hours, "keyword", {}))

    location = _phrase_or_short(text, _LOCATION_PHRASES, _LOCATION_SHORT, _LOCATION_QUESTION)
    if location:
        found.append(_Candidate(Intent.LOCATION, location, "keyword", {}))

    contact = _phrase_or_short(text, _CONTACT_PHRASES, _CONTACT_SHORT, _CONTACT_QUESTION)
    if contact:
        found.append(_Candidate(Intent.CONTACT, contact, "keyword", {}))

    services = _phrase_or_short(text, _SERVICE_PHRASES, _SERVICE_SHORT, _SERVICE_QUESTION)
    if services:
        found.append(_Candidate(Intent.SERVICES, services, "keyword", extracted if service_name else {}))
    elif service_name and not _looks_like_question_about_other_topic(text):
        # A named catalogue item, without booking/price language, is a service query.
        if not validators.is_booking_intent(text) and _phrase_or_short(
            text, _PRICE_PHRASES, _PRICE_SHORT, _PRICE_QUESTION
        ) == 0:
            found.append(_Candidate(Intent.SERVICES, 0.8, "keyword", extracted))

    pricing = _phrase_or_short(text, _PRICE_PHRASES, _PRICE_SHORT, _PRICE_QUESTION)
    if pricing:
        found.append(_Candidate(Intent.PRICING, pricing, "keyword", extracted if service_name else {}))

    return found


def _phrase_or_short(
    text: str,
    phrases: tuple[str, ...],
    shorts: tuple[str, ...],
    question_re: re.Pattern[str] | None = None,
) -> float:
    if _matches_any(text, phrases):
        return 0.9
    tokens = set(re.findall(r"[a-z0-9]+", text))
    if tokens <= set(shorts) | {"please", "your", "the"} and tokens & set(shorts):
        return 0.88
    if question_re is not None and question_re.search(text):
        return 0.86
    if any(re.search(rf"\b{re.escape(word)}\b", text) for word in shorts):
        return 0.45
    return 0.0


def _looks_like_question_about_other_topic(text: str) -> bool:
    return bool(
        _matches_any(text, _HOURS_PHRASES)
        or _matches_any(text, _LOCATION_PHRASES)
        or _matches_any(text, _CONTACT_PHRASES)
        or _matches_any(text, _PRICE_PHRASES)
        or _matches_any(text, _HUMAN_PHRASES)
    )


def _extract_service(text: str, facts: TenantFacts) -> str | None:
    names = [item.name for item in facts.services]
    return validators.match_service(text, names)


@dataclass(frozen=True)
class _FaqHit:
    question: str
    answer: str


def _best_faq(text: str, facts: TenantFacts) -> _Candidate | None:
    best_score = 0.0
    best_hit: _FaqHit | None = None
    for faq in facts.faqs:
        score = _faq_score(text, faq.question)
        if score > best_score:
            best_score = score
            best_hit = _FaqHit(faq.question, faq.answer)
    if best_hit is None or best_score < 0.7:
        return None
    return _Candidate(
        Intent.GENERAL_QUESTION,
        min(0.93, 0.7 + best_score * 0.2),
        "faq_overlap",
        {"faq_question": best_hit.question, "faq_answer": best_hit.answer},
    )


def _faq_score(message: str, question: str) -> float:
    msg = validators.normalize(message)
    q = validators.normalize(question)
    if not msg or not q:
        return 0.0
    if msg == q or q in msg:
        return 1.0
    msg_tokens = _content_tokens(msg)
    q_tokens = _content_tokens(q)
    if len(q_tokens) < 2 or not msg_tokens:
        return 0.0
    overlap = msg_tokens & q_tokens
    if len(overlap) < 2:
        return 0.0
    return len(overlap) / len(q_tokens)


def _content_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text) if token not in _STOPWORDS and len(token) > 1}


def _strip_greeting(text: str) -> str:
    return _GREETING_PREFIX.sub("", text, count=1).strip(" ,!.?")


def _matches_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _pick(candidates: list[_Candidate]) -> _Candidate:
    booking = [item for item in candidates if item.intent == Intent.BOOKING]
    if booking:
        return booking[0]
    human = [item for item in candidates if item.intent == Intent.HUMAN_REQUEST]
    if human:
        return human[0]
    ranked = sorted(candidates, key=lambda item: item.confidence, reverse=True)
    top = ranked[0]
    if top.intent == Intent.GREETING:
        others = [item for item in ranked if item.intent != Intent.GREETING]
        if others and others[0].confidence >= ACT_THRESHOLD:
            return others[0]
    return top
