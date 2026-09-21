"""CSRF protection for browser forms; webhook and API stay exempt."""

from __future__ import annotations

import re

import pytest

from tests.conftest import whatsapp_post


@pytest.fixture
def csrf_client():
    """A test client with CSRF protection actively enabled."""
    import app as app_module

    app_module.app.config["WTF_CSRF_ENABLED"] = True
    try:
        yield app_module.app.test_client()
    finally:
        app_module.app.config["WTF_CSRF_ENABLED"] = False


def _csrf_token(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else None


def test_browser_form_with_valid_csrf_succeeds(make_business, make_admin, csrf_client):
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)

    page = csrf_client.get("/login").get_data(as_text=True)
    token = _csrf_token(page)
    assert token

    resp = csrf_client.post("/login", data={"email": email, "password": password, "csrf_token": token})
    assert resp.status_code == 302  # authenticated + redirected


def test_missing_csrf_token_is_rejected(make_business, make_admin, csrf_client):
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)
    resp = csrf_client.post("/login", data={"email": email, "password": password})
    assert resp.status_code == 400


def test_invalid_csrf_token_is_rejected(make_business, make_admin, csrf_client):
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)
    resp = csrf_client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": "not-a-valid-token"},
    )
    assert resp.status_code == 400


def test_webhook_still_works_with_csrf_enabled(make_business, csrf_client):
    make_business(name="Business A", services=["PLC Programming"], whatsapp_number="whatsapp:+27111111111")
    resp = whatsapp_post(csrf_client, "I want to book", "whatsapp:+27831234567", "whatsapp:+27111111111")
    assert resp.status_code == 200
    assert "<Message>" in resp.get_data(as_text=True)
