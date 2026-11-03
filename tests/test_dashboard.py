"""Admin management UI: tenant-scoped service/FAQ/WhatsApp CRUD."""

from __future__ import annotations

from sqlalchemy import select

from database import get_session
from models.service import Service
from services.business_service import BusinessService
from tests.conftest import login


def _login_admin(app_client, make_business, make_admin, name="Business A", email="a@example.com"):
    business_id = make_business(name=name, whatsapp_number=None)
    email, password = make_admin(business_id, email=email)
    login(app_client, email, password)
    return business_id


def _service_id(business_id, name):
    with get_session() as session:
        return session.scalar(select(Service.id).where(Service.business_id == business_id, Service.name == name))


def test_service_create_edit_delete(app_client, make_business, make_admin):
    business_id = _login_admin(app_client, make_business, make_admin)

    # Create
    app_client.post("/dashboard/services/new", data={"name": "PLC Programming", "price": "750", "duration_minutes": "60", "active": "on"})
    names = [s.name for s in BusinessService.get_services(business_id)]
    assert "PLC Programming" in names

    # Edit
    sid = _service_id(business_id, "PLC Programming")
    app_client.post(f"/dashboard/services/{sid}/edit", data={"name": "PLC Pro", "price": "800", "duration_minutes": "90", "active": "on"})
    assert _service_id(business_id, "PLC Pro") is not None

    # Delete
    sid = _service_id(business_id, "PLC Pro")
    app_client.post(f"/dashboard/services/{sid}/delete")
    assert BusinessService.get_services(business_id) == []


def test_faq_create_and_delete(app_client, make_business, make_admin):
    business_id = _login_admin(app_client, make_business, make_admin)
    app_client.post("/dashboard/faqs/new", data={"question": "Hours?", "answer": "9-5", "priority": "1"})
    faqs = BusinessService.get_faq(business_id)
    assert [f.question for f in faqs] == ["Hours?"]

    app_client.post(f"/dashboard/faqs/{faqs[0].id}/delete")
    assert BusinessService.get_faq(business_id) == []


def test_whatsapp_number_update_is_normalized(app_client, make_business, make_admin):
    business_id = _login_admin(app_client, make_business, make_admin)
    app_client.post("/dashboard/business", data={"name": "Business A", "whatsapp_number": "whatsapp:+27 111-111111", "booking_enabled": "on"})
    business = BusinessService.get_business(business_id)
    assert business.whatsapp_number == "+27111111111"


def test_admin_cannot_edit_another_business_service_via_ui(app_client, make_business, make_admin):
    biz_a = _login_admin(app_client, make_business, make_admin, name="Business A", email="a@example.com")
    biz_b = make_business(name="Business B", services=["Photography"])
    b_service_id = _service_id(biz_b, "Photography")

    # A (logged in) tries to edit B's service via the UI — scoped away, B unchanged.
    resp = app_client.post(f"/dashboard/services/{b_service_id}/edit", data={"name": "Hijacked"})
    assert resp.status_code in (302, 303)
    with get_session() as session:
        assert session.get(Service, b_service_id).name == "Photography"


def test_admin_cannot_delete_another_business_service_via_ui(app_client, make_business, make_admin):
    _login_admin(app_client, make_business, make_admin, name="Business A", email="a@example.com")
    biz_b = make_business(name="Business B", services=["Photography"])
    b_service_id = _service_id(biz_b, "Photography")

    app_client.post(f"/dashboard/services/{b_service_id}/delete")
    with get_session() as session:
        assert session.get(Service, b_service_id) is not None
