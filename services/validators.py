"""Small, dependency-free helpers for parsing and classifying customer input.

Kept deliberately simple: plain Python string/date handling rather than a
heavyweight natural-language parser, so the booking flow stays maintainable.
"""

from __future__ import annotations

import datetime
import re

_DATE_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %I:%M %p",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M %p",
    "%Y-%m-%d",
    "%d/%m/%Y",
]

# Single tokens are matched on word boundaries; multi-word phrases as substrings.
_CANCEL_TERMS = ["cancel", "never mind", "nevermind", "forget it", "forget about it", "stop it"]
_RESTART_TERMS = ["start over", "start again", "restart", "reset", "begin again"]
_BOOKING_TERMS = ["book", "booking", "appointment", "appointments", "schedule", "reserve", "reservation"]
_AFFIRMATIVE_TERMS = [
    "yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "correct", "confirm",
    "confirmed", "that's right", "thats right", "sounds good", "go ahead", "book it", "please do",
]
_NEGATIVE_TERMS = ["no", "n", "nope", "nah", "not", "don't", "dont"]

_CHANGE_SERVICE_TERMS = [
    "different service", "change service", "change the service", "wrong service",
    "another service", "other service",
]
_CHANGE_DATE_TERMS = [
    "different date", "change date", "change the date", "wrong date", "another date",
    "different time", "change time", "change the time", "wrong time", "another time",
    "reschedule",
]
_CHANGE_NAME_TERMS = [
    "different name", "change name", "change the name", "wrong name", "another name",
]


def normalize(text: str | None) -> str:
    """Lower-case and collapse whitespace for keyword matching."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def parse_datetime(value: str | None) -> datetime.datetime | None:
    """Parse a customer-supplied date/time, returning None when unrecognised."""
    if not value:
        return None
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            return parsed.replace(hour=9, minute=0)
        return parsed
    return None


def _contains_term(text: str, term: str) -> bool:
    if " " in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _matches_any(text: str, terms: list[str]) -> bool:
    norm = normalize(text)
    return any(_contains_term(norm, term) for term in terms)


def is_cancel(text: str) -> bool:
    return _matches_any(text, _CANCEL_TERMS)


def is_restart(text: str) -> bool:
    return _matches_any(text, _RESTART_TERMS)


def is_booking_intent(text: str) -> bool:
    return _matches_any(text, _BOOKING_TERMS)


def is_affirmative(text: str) -> bool:
    norm = normalize(text).strip(" .!")
    if not norm:
        return False
    if norm in _AFFIRMATIVE_TERMS:
        return True
    first = norm.split(" ", 1)[0]
    return first in {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "correct"}


def is_negative(text: str) -> bool:
    norm = normalize(text).strip(" .!")
    if not norm:
        return False
    if norm in _NEGATIVE_TERMS:
        return True
    first = norm.split(" ", 1)[0]
    return first in {"no", "nope", "nah"}


def wants_change_service(text: str) -> bool:
    return _matches_any(text, _CHANGE_SERVICE_TERMS)


def wants_change_date(text: str) -> bool:
    return _matches_any(text, _CHANGE_DATE_TERMS)


def wants_change_name(text: str) -> bool:
    return _matches_any(text, _CHANGE_NAME_TERMS)


def match_service(message: str, service_names: list[str]) -> str | None:
    """Match free-text against configured service names, case-insensitively.

    Returns the canonical configured name, or None when nothing matches.
    """
    norm = normalize(message)
    if not norm:
        return None
    normalized_pairs = [(name, normalize(name)) for name in service_names]
    for name, lowered in normalized_pairs:
        if norm == lowered:
            return name
    for name, lowered in normalized_pairs:
        if lowered and (lowered in norm or norm in lowered):
            return name
    return None
