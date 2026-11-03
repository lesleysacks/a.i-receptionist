"""Customer-facing strings. Decision code must not embed business copy here."""

from __future__ import annotations

from decimal import Decimal

from apex_receptionist.intelligence.types import ServiceFact, TenantFacts

_MISSING = (
    "I don't have {topic} on file for {name}. "
    "A team member will confirm that for you."
)


def missing(facts: TenantFacts, topic: str) -> str:
    return _MISSING.format(topic=topic, name=facts.name)


def greeting(facts: TenantFacts) -> str:
    return f"Hello from {facts.name}! How can I help you today?"


def opening_hours(facts: TenantFacts) -> str:
    if not facts.opening_hours:
        return missing(facts, "opening hours")
    return f"{facts.name} opening hours: {facts.opening_hours}."


def location(facts: TenantFacts) -> str:
    parts = [part for part in (facts.address, facts.city, facts.country) if part]
    if not parts:
        return missing(facts, "location")
    return f"{facts.name} is at {', '.join(parts)}."


def contact(facts: TenantFacts) -> str:
    lines: list[str] = []
    if facts.phone:
        lines.append(f"Phone: {facts.phone}")
    if facts.email:
        lines.append(f"Email: {facts.email}")
    if facts.website:
        lines.append(f"Website: {facts.website}")
    if not lines:
        return missing(facts, "contact details")
    return f"You can reach {facts.name} here:\n" + "\n".join(lines)


def services(facts: TenantFacts, service_name: str | None = None) -> str:
    if service_name:
        matched = _named_service(facts, service_name)
        if matched is None:
            return missing(facts, f"details for {service_name}")
        if matched.description:
            return f"{matched.name}: {matched.description}"
        return f"{facts.name} offers {matched.name}."
    if not facts.services:
        return missing(facts, "a service list")
    names = ", ".join(item.name for item in facts.services)
    return f"{facts.name} offers: {names}."


def pricing(facts: TenantFacts, service_name: str | None = None) -> str:
    if service_name:
        matched = _named_service(facts, service_name)
        if matched is None:
            return missing(facts, f"a price for {service_name}")
        if matched.price is None:
            return missing(facts, f"a price for {matched.name}")
        return f"{matched.name}: {_money(matched.price, facts.currency)}."
    priced = [item for item in facts.services if item.price is not None]
    if not priced:
        return missing(facts, "pricing")
    lines = [f"{item.name}: {_money(item.price, facts.currency)}" for item in priced]
    unpriced = [item.name for item in facts.services if item.price is None]
    text = f"{facts.name} prices:\n" + "\n".join(lines)
    if unpriced:
        text += (
            f"\nI don't have prices on file for {', '.join(unpriced)}; "
            "a team member will confirm those."
        )
    return text


def faq_answer(answer: str) -> str:
    return answer.strip()


def human_handoff(facts: TenantFacts) -> str:
    return f"I'll connect you with a team member from {facts.name}."


def ai_unavailable(facts: TenantFacts) -> str:
    return (
        f"Thanks for your message. A team member from {facts.name} "
        "will assist you shortly."
    )


def _named_service(facts: TenantFacts, service_name: str) -> ServiceFact | None:
    wanted = service_name.strip().lower()
    for item in facts.services:
        if item.name.lower() == wanted:
            return item
    return None


def _money(amount: Decimal, currency: str) -> str:
    return f"{amount:.2f} {currency}"
