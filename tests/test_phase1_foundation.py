"""Phase 1 platform tests: Django auth, tenancy, audit, webhook hardening."""

from __future__ import annotations

import inspect
import os

import app as app_module
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import AccessDenied, grant_membership, resolve_business_id_for_user
from tests.conftest import login


def test_webhook_does_not_use_default_business():
    source = inspect.getsource(app_module.whatsapp)
    assert "get_default_business" not in source


def test_django_user_and_membership_are_created(make_business, make_admin):
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id, email="owner@example.com")
    user = User.objects.get(email=email)
    assert user.check_password(password)
    membership = Membership.objects.get(user=user)
    assert membership.role == Membership.Role.TENANT_ADMIN
    assert membership.tenant.receptionist_business_id == business_id
    assert Tenant.objects.filter(receptionist_business_id=business_id).exists()


def test_cross_tenant_business_id_is_rejected(make_business, make_admin):
    a = make_business(name="A")
    b = make_business(name="B")
    make_admin(a, email="a@example.com")
    user = User.objects.get(email="a@example.com")
    try:
        resolve_business_id_for_user(user, requested_business_id=b)
        raised = False
    except AccessDenied:
        raised = True
    assert raised


def test_platform_admin_requires_explicit_tenant(make_business):
    business_id = make_business(name="Managed Co")
    user = User.objects.create_user(email="staff@intersacks.example", password="staff-pass-123", is_platform_admin=True)
    try:
        resolve_business_id_for_user(user)
        raised = False
    except AccessDenied:
        raised = True
    assert raised
    assert resolve_business_id_for_user(user, requested_business_id=business_id) == business_id
    assert AuditEvent.objects.filter(action="tenant.privileged_access").exists()


def test_tenant_member_cannot_mutate_admin_api(make_business, make_admin, app_client):
    business_id = make_business(name="Business A", services=["PLC Programming"])
    email, password = make_admin(business_id, email="admin@example.com")
    admin = User.objects.get(email=email)
    member = User.objects.create_user(email="member@example.com", password="member-pass-123")
    tenant = Tenant.objects.get(receptionist_business_id=business_id)
    Membership.objects.filter(user=admin).update(role=Membership.Role.TENANT_MEMBER)
    grant_membership(user=member, tenant=tenant, role=Membership.Role.TENANT_MEMBER)
    login(app_client, "member@example.com", "member-pass-123")
    resp = app_client.post("/admin/services", json={"name": "Hijack"})
    assert resp.status_code == 403
    get_resp = app_client.get("/admin/services")
    assert get_resp.status_code == 200


def test_platform_admin_cannot_use_flask_dashboard_without_tenant(app_client):
    User.objects.create_user(email="staff@intersacks.example", password="staff-pass-123", is_platform_admin=True)
    resp = login(app_client, "staff@intersacks.example", "staff-pass-123")
    assert resp.status_code == 403
    assert app_client.get("/leads").status_code == 302


def test_audit_event_redacts_password_keys(make_business, make_admin):
    from apps.audit.services import record_audit

    business_id = make_business(name="A")
    make_admin(business_id)
    user = User.objects.get(email="admin@example.com")
    record_audit(
        actor=user,
        action="test.redaction",
        metadata={"password": "secret", "role": "TENANT_ADMIN", "token": "abc"},
    )
    event = AuditEvent.objects.filter(action="test.redaction").first()
    assert event is not None
    assert "password" not in event.metadata
    assert "token" not in event.metadata
    assert event.metadata.get("role") == "TENANT_ADMIN"


def test_django_login_requires_csrf():
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    user = User.objects.create_user(email="csrf@example.com", password="csrf-pass-123")
    resp = client.post("/accounts/login/", {"email": user.email, "password": "csrf-pass-123"})
    assert resp.status_code == 403


def test_django_login_success_creates_audit():
    from django.test import Client

    client = Client()
    User.objects.create_user(email="ok@example.com", password="ok-pass-1234")
    resp = client.post("/accounts/login/", {"email": "ok@example.com", "password": "ok-pass-1234"})
    assert resp.status_code in {200, 302}
    assert resp.status_code == 302
    assert AuditEvent.objects.filter(action="auth.login_success").exists()


def test_webhook_canonical_base_url(make_business, app_client, monkeypatch):
    make_business(name="A", whatsapp_number="whatsapp:+27111111111")
    monkeypatch.setenv("WEBHOOK_BASE_URL", "https://apex.example")
    from twilio.request_validator import RequestValidator

    params = {
        "Body": "hello",
        "From": "whatsapp:+27830000000",
        "To": "whatsapp:+27111111111",
    }
    signature = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"]).compute_signature(
        "https://apex.example/whatsapp", params
    )
    resp = app_client.post("/whatsapp", data=params, headers={"X-Twilio-Signature": signature})
    assert resp.status_code == 200


def test_duplicate_message_sid_is_ignored(make_business, app_client):
    make_business(name="A", whatsapp_number="whatsapp:+27111111111", services=["PLC Programming"])
    from twilio.request_validator import RequestValidator

    params = {
        "Body": "I want to book",
        "From": "whatsapp:+27830000001",
        "To": "whatsapp:+27111111111",
        "MessageSid": "SM-duplicate-1",
    }
    url = "http://localhost/whatsapp"
    signature = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"]).compute_signature(url, params)
    once = app_client.post("/whatsapp", data=params, headers={"X-Twilio-Signature": signature}, base_url="http://localhost")
    twice = app_client.post("/whatsapp", data=params, headers={"X-Twilio-Signature": signature}, base_url="http://localhost")
    assert once.status_code == 200
    assert twice.status_code == 200
    assert b"Message" in once.data
    assert b"Message" not in twice.data


def test_tenant_member_cannot_list_platform_tenants(make_business, make_admin):
    from django.test import Client

    business_id = make_business(name="Member Co")
    email, password = make_admin(business_id, email="member-ui@example.com")
    client = Client()
    assert client.login(username=email, password=password)
    resp = client.get("/platform/tenants/")
    assert resp.status_code == 403


def test_platform_admin_can_list_tenants(make_business):
    from django.test import Client

    make_business(name="Listed Co")
    user = User.objects.create_user(
        email="staff-ui@intersacks.example",
        password="staff-pass-123",
        is_platform_admin=True,
    )
    client = Client()
    client.force_login(user)
    resp = client.get("/platform/tenants/")
    assert resp.status_code == 200
    assert b"Listed Co" in resp.content


def test_django_logout_is_post_only_and_revokes_session():
    from django.test import Client

    client = Client()
    User.objects.create_user(email="out@example.com", password="out-pass-1234")
    client.post("/accounts/login/", {"email": "out@example.com", "password": "out-pass-1234"})
    assert client.get("/accounts/").status_code == 200
    assert client.get("/accounts/logout/").status_code == 405
    resp = client.post("/accounts/logout/")
    assert resp.status_code == 302
    follow = client.get("/accounts/")
    assert follow.status_code == 302
    assert "/accounts/login/" in follow.url
    assert AuditEvent.objects.filter(action="auth.logout").exists()


def test_oversized_payload_is_rejected():
    import app as app_module
    from flask import request
    from werkzeug.exceptions import RequestEntityTooLarge

    flask_app = app_module.app
    limit = flask_app.config["MAX_CONTENT_LENGTH"]
    assert limit == 64 * 1024
    payload = b"x" * (limit + 1)
    try:
        with flask_app.test_request_context(
            "/whatsapp",
            method="POST",
            data=payload,
            content_type="application/x-www-form-urlencoded",
        ):
            request.get_data()
        raised = False
    except RequestEntityTooLarge as exc:
        raised = True
        assert exc.code == 413
    assert raised


def test_production_allowed_hosts_require_explicit_names():
    from apex.settings import allowed_hosts_for_env

    assert "testserver" in allowed_hosts_for_env("testing", None)
    try:
        allowed_hosts_for_env("production", None)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    try:
        allowed_hosts_for_env("production", "*")
        wildcard = False
    except RuntimeError:
        wildcard = True
    assert wildcard
    assert allowed_hosts_for_env("production", "apex.example") == ["apex.example"]


def test_custom_user_admin_forms_use_email_not_username():
    from apps.accounts.forms import ApexUserChangeForm, ApexUserCreationForm

    user = User.objects.create_user(email="form@example.com", password="form-pass-123")
    change = ApexUserChangeForm(instance=user)
    create = ApexUserCreationForm()
    assert "email" in change.fields
    assert "username" not in change.fields
    assert "email" in create.fields
    assert "username" not in create.fields
