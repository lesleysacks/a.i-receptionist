"""JSON administration API for configurable business content."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from flask import Blueprint, jsonify, request

from models.business import Business
from models.faq import FAQ
from models.service import Service
from services.business_service import BusinessService, NotFoundError, ValidationError

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{6,30}$")


def _default_business() -> Business:
    return BusinessService.get_default_business()


@admin_bp.errorhandler(ValidationError)
def validation_error(error: ValidationError):
    return jsonify({"error": str(error)}), 400


@admin_bp.errorhandler(NotFoundError)
def not_found_error(error: NotFoundError):
    return jsonify({"error": str(error)}), 404


@admin_bp.get("/business")
def get_business():
    return jsonify(_serialize(_default_business()))


@admin_bp.put("/business")
def update_business():
    data = _json_object()
    _validate_business(data)
    business = _default_business()
    return jsonify(_serialize(BusinessService.update_business(business.id, data)))


@admin_bp.get("/services")
def get_services():
    return jsonify([_serialize(item) for item in BusinessService.get_services(_default_business().id)])


@admin_bp.post("/services")
def add_service():
    service = BusinessService.add_service(_default_business().id, _json_object())
    return jsonify(_serialize(service)), 201


@admin_bp.put("/services/<int:service_id>")
def update_service(service_id: int):
    return jsonify(_serialize(BusinessService.update_service(_default_business().id, service_id, _json_object())))


@admin_bp.delete("/services/<int:service_id>")
def delete_service(service_id: int):
    BusinessService.delete_service(_default_business().id, service_id)
    return "", 204


@admin_bp.get("/faq")
def get_faq():
    return jsonify([_serialize(item) for item in BusinessService.get_faq(_default_business().id)])


@admin_bp.post("/faq")
def add_faq():
    faq = BusinessService.add_faq(_default_business().id, _json_object())
    return jsonify(_serialize(faq)), 201


@admin_bp.put("/faq/<int:faq_id>")
def update_faq(faq_id: int):
    return jsonify(_serialize(BusinessService.update_faq(_default_business().id, faq_id, _json_object())))


@admin_bp.delete("/faq/<int:faq_id>")
def delete_faq(faq_id: int):
    BusinessService.delete_faq(_default_business().id, faq_id)
    return "", 204


def _json_object() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("A JSON object is required.")
    return data


def _validate_business(data: dict[str, Any]) -> None:
    if "email" in data and data["email"] and not EMAIL_PATTERN.fullmatch(str(data["email"])):
        raise ValidationError("Email must be valid.")
    for field in ("phone", "owner_phone"):
        if field in data and data[field] and not PHONE_PATTERN.fullmatch(str(data[field])):
            raise ValidationError(f"{field.replace('_', ' ').capitalize()} must be valid.")
    if "opening_hours" in data and data["opening_hours"] is not None and not str(data["opening_hours"]).strip():
        raise ValidationError("Opening hours cannot be blank; omit it when unknown.")
    if "booking_duration" in data:
        try:
            if int(data["booking_duration"]) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValidationError("Booking duration must be a positive number of minutes.") from exc


def _serialize(value: Business | Service | FAQ) -> dict[str, Any]:
    """Convert supported ORM objects to stable JSON response shapes."""
    result: dict[str, Any] = {}
    for column in value.__table__.columns:
        item = getattr(value, column.name)
        if isinstance(item, Decimal):
            item = float(item)
        elif isinstance(item, (datetime, date)):
            item = item.isoformat()
        result[column.name] = item
    return result
