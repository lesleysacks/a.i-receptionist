"""Phase 2.2: redacted pipeline outcomes, tenant isolation, non-blocking persistence."""

from __future__ import annotations

import inspect

from apps.intelligence.models import IntelligenceOutcome
from apps.intelligence.services import (
    assert_no_sensitive_fields,
    outcomes_for_user,
    record_pipeline_outcome,
)
from apps.tenants.models import Membership, Tenant
from apex_receptionist.intelligence.pipeline import ResponsePipeline
from apex_receptionist.intelligence.types import PipelineDecision
from services.business_service import BusinessService
from services.conversation_service import ConversationService
from tests.helpers import FakeAI

SENDER = "whatsapp:+27830000999"


def _service(ai=None, persist=None):
    pipeline = ResponsePipeline(persist_outcome=persist) if persist is not None else ResponsePipeline()
    return ConversationService(ai_service=ai or FakeAI(), state_store={}, response_pipeline=pipeline)


def test_greeting_persists_redacted_outcome_for_resolved_tenant(make_business):
    business_id = make_business(name="Outcome Co")
    ai = FakeAI()
    reply = _service(ai).handle(business_id, SENDER, "hello")
    assert "Outcome Co" in reply
    assert ai.respond_calls == []

    rows = list(IntelligenceOutcome.objects.all())
    assert len(rows) == 1
    row = rows[0]
    tenant = Tenant.objects.get(receptionist_business_id=business_id)
    assert row.tenant_id == tenant.id
    assert row.receptionist_business_id == business_id
    assert row.intent == "GREETING"
    assert row.classification_method == "keyword"
    assert row.decision == PipelineDecision.DETERMINISTIC.value
    assert row.response_type == "greeting"
    assert row.ai_required is False
    assert row.outcome == "success"
    assert row.duration_ms is not None
    assert row.confidence is not None


def test_outcome_has_no_message_or_phone_fields():
    assert_no_sensitive_fields()
    names = {field.name for field in IntelligenceOutcome._meta.get_fields()}
    for forbidden in ("message", "body", "phone", "sender", "transcript", "prompt", "metadata"):
        assert forbidden not in names
    params = inspect.signature(record_pipeline_outcome).parameters
    for forbidden in ("message", "body", "phone", "sender", "transcript"):
        assert forbidden not in params


def test_cross_tenant_operators_cannot_read_other_outcomes(make_business, make_admin):
    a = make_business(name="Tenant A")
    b = make_business(name="Tenant B")
    _service().handle(a, SENDER, "hello")
    _service().handle(b, SENDER, "hello")
    assert IntelligenceOutcome.objects.count() == 2

    email_a, password_a = make_admin(a, email="a-ops@example.com")
    email_b, _ = make_admin(b, email="b-ops@example.com")
    from apps.accounts.models import User

    user_a = User.objects.get(email=email_a)
    user_b = User.objects.get(email=email_b)
    seen_a = list(outcomes_for_user(user_a))
    seen_b = list(outcomes_for_user(user_b))
    assert len(seen_a) == 1
    assert len(seen_b) == 1
    assert seen_a[0].receptionist_business_id == a
    assert seen_b[0].receptionist_business_id == b
    assert user_a.check_password(password_a)


def test_revoked_membership_cannot_read_outcomes(make_business, make_admin):
    business_id = make_business(name="Revoked Co")
    _service().handle(business_id, SENDER, "hello")
    email, password = make_admin(business_id, email="revoked@example.com")
    from apps.accounts.models import User

    user = User.objects.get(email=email)
    Membership.objects.filter(user=user).update(status=Membership.Status.REVOKED)
    assert list(outcomes_for_user(user)) == []


def test_platform_admin_can_read_all_outcomes(make_business):
    a = make_business(name="A")
    b = make_business(name="B")
    _service().handle(a, SENDER, "hello")
    _service().handle(b, SENDER, "hello")
    from apps.accounts.models import User

    staff = User.objects.create_user(
        email="staff@intersacks.example",
        password="staff-pass-123",
        is_platform_admin=True,
    )
    ids = {row.receptionist_business_id for row in outcomes_for_user(staff)}
    assert ids == {a, b}


def test_unauthenticated_user_sees_no_outcomes(make_business):
    _service().handle(make_business(name="Hidden Co"), SENDER, "hello")
    assert list(outcomes_for_user(None)) == []


def test_persistence_failure_does_not_break_reply(make_business):
    business_id = make_business(name="Resilient Co")

    def boom(business_id, result):
        raise RuntimeError("database unavailable")

    ai = FakeAI()
    reply = _service(ai, persist=boom).handle(business_id, SENDER, "hello")
    assert "Resilient Co" in reply
    assert ai.respond_calls == []
    assert IntelligenceOutcome.objects.count() == 0


def test_pipeline_customer_reply_is_unchanged(make_business):
    business_id = make_business(name="Same Co")
    BusinessService.update_business(business_id, {"opening_hours": "Mon-Fri 08:00-17:00"})
    without_store = ConversationService(
        ai_service=FakeAI(),
        state_store={},
        response_pipeline=ResponsePipeline(persist_outcome=lambda *_: None),
    ).handle(business_id, SENDER, "what are your opening hours?")
    with_store = ConversationService(ai_service=FakeAI(), state_store={}).handle(
        business_id, SENDER, "what are your opening hours?"
    )
    assert without_store == with_store
    assert "Mon-Fri 08:00-17:00" in with_store
    assert IntelligenceOutcome.objects.filter(intent="OPENING_HOURS").count() == 1


def test_record_uses_server_business_id_not_customer_payload(make_business):
    business_id = make_business(name="Trusted Co")
    other = make_business(name="Other Co")
    record_pipeline_outcome(
        business_id=business_id,
        intent="GREETING",
        classification_method="keyword",
        confidence=0.95,
        decision="deterministic",
        response_type="greeting",
        ai_required=False,
        outcome="success",
        duration_ms=1.0,
    )
    row = IntelligenceOutcome.objects.get()
    assert row.receptionist_business_id == business_id
    assert row.tenant.receptionist_business_id == business_id
    assert row.receptionist_business_id != other
