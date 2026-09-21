"""Authenticated, tenant-scoped admin management UI (server-rendered)."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from routes.auth import login_required
from services.business_service import BusinessService, NotFoundError, ValidationError

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _business(admin):
    return BusinessService.get_business(admin.business_id)


@dashboard_bp.get("/")
@login_required
def index(admin):
    business = _business(admin)
    return render_template(
        "dashboard.html",
        admin=admin,
        business=business,
        service_count=len(BusinessService.get_services(admin.business_id)),
        faq_count=len(BusinessService.get_faq(admin.business_id)),
    )


# -- Services -----------------------------------------------------------------
@dashboard_bp.get("/services")
@login_required
def services(admin):
    return render_template(
        "services.html",
        admin=admin,
        business=_business(admin),
        services=BusinessService.get_services(admin.business_id),
    )


@dashboard_bp.route("/services/new", methods=["GET", "POST"])
@login_required
def service_new(admin):
    business = _business(admin)
    if request.method == "POST":
        try:
            BusinessService.add_service(admin.business_id, _service_form())
            flash("Service created.", "ok")
            return redirect(url_for("dashboard.services"))
        except ValidationError as exc:
            return render_template("service_form.html", admin=admin, business=business, service=None, form=request.form, error=str(exc))
    return render_template("service_form.html", admin=admin, business=business, service=None, form=None, error=None)


@dashboard_bp.route("/services/<int:service_id>/edit", methods=["GET", "POST"])
@login_required
def service_edit(admin, service_id):
    business = _business(admin)
    services_list = {s.id: s for s in BusinessService.get_services(admin.business_id)}
    service = services_list.get(service_id)
    if service is None:
        flash("Service not found.", "error")
        return redirect(url_for("dashboard.services"))
    if request.method == "POST":
        try:
            BusinessService.update_service(admin.business_id, service_id, _service_form())
            flash("Service updated.", "ok")
            return redirect(url_for("dashboard.services"))
        except ValidationError as exc:
            return render_template("service_form.html", admin=admin, business=business, service=service, form=request.form, error=str(exc))
    return render_template("service_form.html", admin=admin, business=business, service=service, form=None, error=None)


@dashboard_bp.post("/services/<int:service_id>/delete")
@login_required
def service_delete(admin, service_id):
    try:
        BusinessService.delete_service(admin.business_id, service_id)
        flash("Service deleted.", "ok")
    except NotFoundError:
        flash("Service not found.", "error")
    return redirect(url_for("dashboard.services"))


def _service_form() -> dict:
    return {
        "name": request.form.get("name", ""),
        "price": request.form.get("price", ""),
        "duration_minutes": request.form.get("duration_minutes", ""),
        "active": "active" in request.form,
    }


# -- FAQs ---------------------------------------------------------------------
@dashboard_bp.get("/faqs")
@login_required
def faqs(admin):
    return render_template(
        "faqs.html",
        admin=admin,
        business=_business(admin),
        faqs=BusinessService.get_faq(admin.business_id),
    )


@dashboard_bp.route("/faqs/new", methods=["GET", "POST"])
@login_required
def faq_new(admin):
    business = _business(admin)
    if request.method == "POST":
        try:
            BusinessService.add_faq(admin.business_id, _faq_form())
            flash("FAQ created.", "ok")
            return redirect(url_for("dashboard.faqs"))
        except ValidationError as exc:
            return render_template("faq_form.html", admin=admin, business=business, faq=None, form=request.form, error=str(exc))
    return render_template("faq_form.html", admin=admin, business=business, faq=None, form=None, error=None)


@dashboard_bp.route("/faqs/<int:faq_id>/edit", methods=["GET", "POST"])
@login_required
def faq_edit(admin, faq_id):
    business = _business(admin)
    faqs_list = {f.id: f for f in BusinessService.get_faq(admin.business_id)}
    faq = faqs_list.get(faq_id)
    if faq is None:
        flash("FAQ not found.", "error")
        return redirect(url_for("dashboard.faqs"))
    if request.method == "POST":
        try:
            BusinessService.update_faq(admin.business_id, faq_id, _faq_form())
            flash("FAQ updated.", "ok")
            return redirect(url_for("dashboard.faqs"))
        except ValidationError as exc:
            return render_template("faq_form.html", admin=admin, business=business, faq=faq, form=request.form, error=str(exc))
    return render_template("faq_form.html", admin=admin, business=business, faq=faq, form=None, error=None)


@dashboard_bp.post("/faqs/<int:faq_id>/delete")
@login_required
def faq_delete(admin, faq_id):
    try:
        BusinessService.delete_faq(admin.business_id, faq_id)
        flash("FAQ deleted.", "ok")
    except NotFoundError:
        flash("FAQ not found.", "error")
    return redirect(url_for("dashboard.faqs"))


def _faq_form() -> dict:
    return {
        "question": request.form.get("question", ""),
        "answer": request.form.get("answer", ""),
        "category": request.form.get("category", ""),
        "priority": request.form.get("priority", 0),
    }


# -- Business settings --------------------------------------------------------
@dashboard_bp.route("/business", methods=["GET", "POST"])
@login_required
def business(admin):
    if request.method == "POST":
        data = {
            "name": request.form.get("name", ""),
            "whatsapp_number": request.form.get("whatsapp_number", ""),
            "phone": request.form.get("phone", ""),
            "email": request.form.get("email", ""),
            "city": request.form.get("city", ""),
            "booking_enabled": "booking_enabled" in request.form,
        }
        try:
            BusinessService.update_business(admin.business_id, data)
            flash("Business settings saved.", "ok")
            return redirect(url_for("dashboard.business"))
        except ValidationError as exc:
            return render_template("business.html", admin=admin, business=_business(admin), error=str(exc))
    return render_template("business.html", admin=admin, business=_business(admin), error=None)
