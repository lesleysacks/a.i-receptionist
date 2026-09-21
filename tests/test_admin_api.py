"""Admin API authentication and tenant-boundary tests."""

from __future__ import annotations

from sqlalchemy import select

from database import get_session
from models.service import Service
from tests.conftest import login


def _service_id(business_id, name):
    with get_session() as session:
        return session.scalar(
            select(Service.id).where(Service.business_id == business_id, Service.name == name)
        )


def test_unauthorized_request_is_rejected(make_business, app_client):
    make_business(name="Business A")
    resp = app_client.get("/admin/business")
    assert resp.status_code == 401


def test_invalid_api_key_is_rejected(make_business, app_client, monkeypatch):
    biz = make_business(name="Business A")
    monkeypatch.setenv("ADMIN_API_KEY", "correct-key")
    resp = app_client.get("/admin/business", headers={"X-Admin-Key": "wrong-key", "X-Business-Id": str(biz)})
    assert resp.status_code == 401


def test_valid_api_key_with_business_id(make_business, app_client, monkeypatch):
    biz = make_business(name="Business A")
    monkeypatch.setenv("ADMIN_API_KEY", "correct-key")
    resp = app_client.get("/admin/business", headers={"X-Admin-Key": "correct-key", "X-Business-Id": str(biz)})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Business A"


def test_session_admin_can_read_own_business(make_business, make_admin, app_client):
    biz = make_business(name="Business A")
    email, password = make_admin(biz)
    login(app_client, email, password)
    resp = app_client.get("/admin/business")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Business A"


def test_admin_cannot_modify_another_business(make_business, make_admin, app_client):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    biz_b = make_business(name="Business B", services=["Photography"])
    b_service_id = _service_id(biz_b, "Photography")

    email_a, pw_a = make_admin(biz_a, email="a@example.com")
    login(app_client, email_a, pw_a)

    # Business A admin tries to edit Business B's service -> scoped away (404).
    resp = app_client.put(f"/admin/services/{b_service_id}", json={"name": "Hijacked"})
    assert resp.status_code == 404

    # Business B's service is unchanged.
    with get_session() as session:
        svc = session.get(Service, b_service_id)
        assert svc.name == "Photography"


def test_admin_can_modify_own_business(make_business, make_admin, app_client):
    biz_a = make_business(name="Business A", services=["PLC Programming"])
    a_service_id = _service_id(biz_a, "PLC Programming")
    email_a, pw_a = make_admin(biz_a, email="a@example.com")
    login(app_client, email_a, pw_a)

    resp = app_client.put(f"/admin/services/{a_service_id}", json={"name": "PLC Programming Pro"})
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "PLC Programming Pro"