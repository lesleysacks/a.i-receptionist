"""Admin authentication tests: login, logout, and protected /leads."""

from __future__ import annotations

from tests.conftest import login


def test_unauthenticated_leads_redirects_to_login(make_business, app_client):
    make_business(name="Business A")
    resp = app_client.get("/leads")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_valid_login_grants_access(make_business, make_admin, app_client):
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)

    resp = login(app_client, email, password)
    assert resp.status_code == 302  # redirect to /leads

    leads = app_client.get("/leads")
    assert leads.status_code == 200
    assert "Leads Dashboard" in leads.get_data(as_text=True)


def test_invalid_login_is_rejected(make_business, make_admin, app_client):
    business_id = make_business(name="Business A")
    email, _ = make_admin(business_id)

    resp = login(app_client, email, "wrong-password")
    assert resp.status_code == 401
    # Still not authenticated.
    assert app_client.get("/leads").status_code == 302


def test_logout_revokes_access(make_business, make_admin, app_client):
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)
    login(app_client, email, password)
    assert app_client.get("/leads").status_code == 200

    app_client.get("/logout")
    after = app_client.get("/leads")
    assert after.status_code == 302
    assert "/login" in after.headers["Location"]


def test_password_is_not_stored_in_plaintext(make_business, make_admin):
    from sqlalchemy import select

    from database import get_session
    from models.admin_user import AdminUser

    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)
    with get_session() as session:
        admin = session.scalar(select(AdminUser).where(AdminUser.email == email))
    assert admin.password_hash != password
    assert password not in admin.password_hash