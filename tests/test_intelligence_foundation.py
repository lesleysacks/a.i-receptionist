"""Phase 2.1: deterministic intents, AI isolation, tenant isolation, FSM compatibility."""

from __future__ import annotations

import inspect
import logging

from apex_receptionist.intelligence.classifier import classify
from apex_receptionist.intelligence.facts import facts_from_business, load_tenant_facts
from apex_receptionist.intelligence.pipeline import ResponsePipeline
from apex_receptionist.intelligence.types import Intent
from apex_receptionist.services.business_service import BusinessService
from services.conversation_service import IDLE, ConversationService
from tests.conftest import whatsapp_post
from tests.helpers import FakeAI, FakeOpenAI
from services.ai_service import AIService

SENDER = "whatsapp:+27830000099"


def _service(ai=None):
    return ConversationService(ai_service=ai or FakeAI(), state_store={})


def _configure(business_id, **fields):
    BusinessService.update_business(business_id, fields)
    return BusinessService.get_business(business_id)


def _priced(business_id, name, price):
    for service in BusinessService.get_services(business_id):
        if service.name == name:
            BusinessService.update_service(business_id, service.id, {"price": price})
            return
    BusinessService.add_service(business_id, {"name": name, "price": price})


def test_classifier_supported_intents(make_business):
    business_id = make_business(
        name="Apex Automation",
        services=["PLC Programming"],
        faqs=[("Do you travel to site?", "Yes, within Gauteng.")],
    )
    _configure(
        business_id,
        opening_hours="Mon-Fri 08:00-17:00",
        address="12 Industry Road",
        city="Johannesburg",
        phone="+27000000000",
        email="hello@example.com",
    )
    facts = load_tenant_facts(business_id)
    cases = {
        "hello": Intent.GREETING,
        "what are your opening hours?": Intent.OPENING_HOURS,
        "where are you located?": Intent.LOCATION,
        "what's your phone number?": Intent.CONTACT,
        "what services do you offer?": Intent.SERVICES,
        "how much is PLC Programming?": Intent.PRICING,
        "I want to book an appointment": Intent.BOOKING,
        "Do you travel to site?": Intent.GENERAL_QUESTION,
        "can I speak to a human please": Intent.HUMAN_REQUEST,
        "asdf qwer zxcv": Intent.UNKNOWN,
    }
    for message, intent in cases.items():
        result = classify(message, facts)
        assert result.intent == intent, f"{message!r} -> {result.intent} (want {intent})"
        if intent is not Intent.UNKNOWN:
            assert result.confidence >= 0.75


def test_price_mention_does_not_override_location_question(make_business):
    business_id = make_business(name="A", services=["PLC Programming"])
    facts = load_tenant_facts(business_id)
    result = classify("I paid a high price last time, where are you located?", facts)
    assert result.intent == Intent.LOCATION
    assert result.confidence >= 0.75


def test_unknown_has_insufficient_confidence(make_business):
    facts = load_tenant_facts(make_business(name="A"))
    result = classify("hmm not sure about that thing", facts)
    assert result.intent == Intent.UNKNOWN
    assert result.confidence < 0.75


def test_greeting_does_not_call_ai(make_business):
    business_id = make_business(name="Hello Co")
    ai = FakeAI()
    reply = _service(ai).handle(business_id, SENDER, "hi")
    assert "Hello Co" in reply
    assert ai.respond_calls == []


def test_opening_hours_from_tenant_data(make_business):
    business_id = make_business(name="Hours Co")
    _configure(business_id, opening_hours="Mon-Fri 08:00-17:00")
    ai = FakeAI()
    reply = _service(ai).handle(business_id, SENDER, "what are your opening hours?")
    assert "Mon-Fri 08:00-17:00" in reply
    assert "Hours Co" in reply
    assert ai.respond_calls == []


def test_missing_opening_hours_is_safe(make_business):
    business_id = make_business(name="No Hours Co")
    reply = _service().handle(business_id, SENDER, "when are you open?")
    assert "don't have" in reply.lower()
    assert "opening hours" in reply.lower()
    assert "08:00" not in reply


def test_location_and_missing_location(make_business):
    located = make_business(name="Located Co")
    _configure(located, address="1 Main Road", city="Cape Town", country="South Africa")
    missing = make_business(name="Unknown Co")
    located_reply = _service().handle(located, SENDER, "where are you?")
    missing_reply = _service().handle(missing, SENDER, "where are you?")
    assert "1 Main Road" in located_reply and "Cape Town" in located_reply
    assert "don't have" in missing_reply.lower()
    assert "1 Main Road" not in missing_reply


def test_contact_details(make_business):
    business_id = make_business(name="Contact Co")
    _configure(business_id, phone="+27000000000", email="desk@example.com", website="https://example.com")
    reply = _service().handle(business_id, SENDER, "how can I contact you?")
    assert "+27000000000" in reply
    assert "desk@example.com" in reply
    assert "https://example.com" in reply


def test_services_and_pricing(make_business):
    business_id = make_business(name="Price Co", services=["PLC Programming", "Site Survey"])
    _priced(business_id, "PLC Programming", "750")
    ai = FakeAI()
    cs = _service(ai)
    services_reply = cs.handle(business_id, SENDER, "what services do you offer?")
    assert "PLC Programming" in services_reply
    assert "Site Survey" in services_reply
    price_reply = cs.handle(business_id, SENDER, "how much is PLC Programming?")
    assert "750.00" in price_reply
    assert "PLC Programming" in price_reply
    general_prices = cs.handle(business_id, SENDER, "what are your prices?")
    assert "750.00" in general_prices
    assert "don't have prices on file for Site Survey" in general_prices
    assert ai.respond_calls == []


def test_never_invents_a_missing_price(make_business):
    business_id = make_business(name="No Price Co", services=["Consulting"])
    reply = _service().handle(business_id, SENDER, "how much is Consulting?")
    assert "don't have" in reply.lower()
    assert "Consulting" in reply
    assert "750" not in reply
    assert "0.00" not in reply


def test_faq_match_and_human_request(make_business):
    business_id = make_business(
        name="Faq Co",
        faqs=[("Do you travel to site?", "Yes, within Gauteng.")],
    )
    ai = FakeAI()
    cs = _service(ai)
    faq_reply = cs.handle(business_id, SENDER, "Do you travel to site?")
    assert "Gauteng" in faq_reply
    human_reply = cs.handle(business_id, SENDER, "please speak to a human")
    assert "team member" in human_reply.lower()
    assert ai.respond_calls == []


def test_cross_tenant_hours_services_and_faqs(make_business):
    a = make_business(
        name="Tenant A",
        services=["PLC Programming"],
        faqs=[("Do you travel to site?", "Yes, within Gauteng.")],
        whatsapp_number="whatsapp:+27111111111",
    )
    b = make_business(
        name="Tenant B",
        services=["Photography"],
        faqs=[("Do you travel to site?", "No, studio only.")],
        whatsapp_number="whatsapp:+27222222222",
    )
    _configure(a, opening_hours="Mon-Fri 08:00-17:00", city="Johannesburg")
    _configure(b, opening_hours="Sat 09:00-13:00", city="Durban")
    _priced(a, "PLC Programming", "750")
    _priced(b, "Photography", "1200")
    cs = _service()

    hours_a = cs.handle(a, SENDER, "what are your opening hours?")
    hours_b = cs.handle(b, SENDER, "what are your opening hours?")
    assert "Mon-Fri 08:00-17:00" in hours_a and "Sat 09:00-13:00" not in hours_a
    assert "Sat 09:00-13:00" in hours_b and "Mon-Fri 08:00-17:00" not in hours_b

    services_a = cs.handle(a, SENDER, "what services do you offer?")
    services_b = cs.handle(b, SENDER, "what services do you offer?")
    assert "PLC Programming" in services_a and "Photography" not in services_a
    assert "Photography" in services_b and "PLC Programming" not in services_b

    price_a = cs.handle(a, SENDER, "what are your prices?")
    price_b = cs.handle(b, SENDER, "what are your prices?")
    assert "750.00" in price_a and "1200.00" not in price_a
    assert "1200.00" in price_b and "750.00" not in price_b

    faq_a = cs.handle(a, SENDER, "Do you travel to site?")
    faq_b = cs.handle(b, SENDER, "Do you travel to site?")
    assert "Gauteng" in faq_a and "studio" not in faq_a.lower()
    assert "studio" in faq_b.lower() and "Gauteng" not in faq_b


def test_pipeline_never_uses_default_tenant():
    import apex_receptionist.intelligence.facts as facts_mod
    import apex_receptionist.intelligence.pipeline as pipeline_mod
    import apex_receptionist.services.conversation_service as conv_mod

    for module in (facts_mod, pipeline_mod, conv_mod):
        assert "get_default_business" not in inspect.getsource(module)


def test_facts_refuse_to_mix_businesses(make_business):
    a = make_business(name="A", services=["PLC Programming"])
    b = make_business(name="B", services=["Photography"])
    facts_a = load_tenant_facts(a)
    facts_b = facts_from_business(BusinessService.get_business(b))
    assert facts_a.business_id == a
    assert facts_b.business_id == b
    assert {item.name for item in facts_a.services} == {"PLC Programming"}
    assert {item.name for item in facts_b.services} == {"Photography"}


def test_booking_fsm_still_starts_from_idle(make_business):
    business_id = make_business(name="Book Co", services=["PLC Programming"])
    ai = FakeAI()
    cs = _service(ai)
    reply = cs.handle(business_id, SENDER, "I want to book an appointment")
    assert "name" in reply.lower()
    assert cs.get_state(business_id, SENDER).step != IDLE
    assert ai.respond_calls == []


def test_greeting_then_booking_still_works(make_business):
    business_id = make_business(name="Flow Co", services=["PLC Programming"])
    cs = _service()
    greet = cs.handle(business_id, SENDER, "hello")
    assert "Flow Co" in greet
    assert cs.get_state(business_id, SENDER).step == IDLE
    book = cs.handle(business_id, SENDER, "book")
    assert "name" in book.lower()


def test_ambiguous_message_uses_ai_seam(make_business):
    business_id = make_business(name="AI Co")
    ai = FakeAI(message="A fallback answer.")
    reply = _service(ai).handle(business_id, SENDER, "tell me a joke about conveyors")
    assert reply == "A fallback answer."
    assert len(ai.respond_calls) == 1
    assert ai.respond_calls[0][0] == business_id


def test_ai_disabled_does_not_call_model(make_business, monkeypatch):
    monkeypatch.setenv("APEX_AI_ENABLED", "false")
    business_id = make_business(name="Off Co")
    ai = FakeAI(message="should not be used")
    reply = _service(ai).handle(business_id, SENDER, "tell me a joke about conveyors")
    assert ai.respond_calls == []
    assert "team member" in reply.lower()
    assert "should not be used" not in reply


def test_ai_failure_on_unknown_intent_is_safe(make_business):
    business_id = make_business(name="Down Co")
    ai = AIService(client=FakeOpenAI(exc=RuntimeError("provider down")))
    reply = ConversationService(ai_service=ai, state_store={}).handle(
        business_id, SENDER, "tell me a joke about conveyors"
    )
    assert "team member" in reply.lower()
    assert "provider down" not in reply.lower()


def test_ai_unavailable_without_key(make_business):
    business_id = make_business(name="NoKey Co")
    reply = ConversationService(ai_service=AIService(), state_store={}).handle(
        business_id, SENDER, "tell me a joke about conveyors"
    )
    assert "team member" in reply.lower()


def test_webhook_greeting_stays_tenant_scoped(make_business, app_client):
    make_business(name="Hook Co", whatsapp_number="whatsapp:+27111111111")
    resp = whatsapp_post(app_client, "hello", SENDER, "whatsapp:+27111111111")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Hook Co" in body
    assert "<Message>" in body


def test_uncertain_classification_does_not_start_booking(make_business):
    business_id = make_business(name="Careful Co", services=["PLC Programming"])
    cs = _service()
    cs.handle(business_id, SENDER, "maybe later thanks")
    assert cs.get_state(business_id, SENDER).step == IDLE


def test_pipeline_logs_do_not_include_message_or_phone(make_business, caplog):
    business_id = make_business(name="Log Co")
    _configure(business_id, opening_hours="Mon-Fri 08:00-17:00")
    with caplog.at_level(logging.INFO, logger="apex_receptionist.intelligence.pipeline"):
        ResponsePipeline().decide(
            BusinessService.get_business(business_id),
            "what are your opening hours?",
        )
    texts = [record.getMessage() for record in caplog.records]
    combined = " ".join(texts)
    assert SENDER not in combined
    assert "what are your opening hours?" not in combined
    extras = [record.__dict__ for record in caplog.records if record.__dict__.get("event") == "response_pipeline"]
    assert extras
    extra = extras[0]
    assert extra["business_id"] == business_id
    assert extra["intent"] == "OPENING_HOURS"
    assert extra["ai_required"] is False
    assert extra.get("phone") is None


def test_incomplete_tenant_contact_is_safe(make_business):
    business_id = make_business(name="Bare Co")
    reply = _service().handle(business_id, SENDER, "what's your email address?")
    assert "don't have" in reply.lower()
    assert "Bare Co" in reply
