"""Business configuration and catalogue persistence services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from database import get_session
from models.business import Business
from models.faq import FAQ
from models.service import Service


class ValidationError(ValueError):
    """Raised when a request cannot produce valid tenant configuration."""


class NotFoundError(LookupError):
    """Raised when a requested tenant-owned entity does not exist."""


class BusinessService:
    """The only database-facing API for business configuration."""

    BUSINESS_FIELDS = {
        "name", "industry", "description", "website", "email", "phone", "address", "city", "country",
        "owner_name", "owner_phone", "timezone", "language", "currency", "booking_enabled", "booking_duration",
        "website_chat_enabled", "whatsapp_enabled", "voice_enabled", "email_enabled", "opening_hours", "logo_url",
    }

    @staticmethod
    def get_business(business_id: int) -> Business:
        """Fetch one tenant or raise a service-level not-found error."""
        with get_session() as session:
            business = session.get(Business, business_id)
            if business is None:
                raise NotFoundError("Business was not found.")
            return business

    @staticmethod
    def get_default_business() -> Business:
        """Return the first tenant, creating an unbranded initial record if needed."""
        with get_session() as session:
            business = session.scalar(select(Business).order_by(Business.id).limit(1))
            if business is None:
                business = Business(name="Your Business")
                session.add(business)
                session.flush()
            return business

    @classmethod
    def update_business(cls, business_id: int, data: dict[str, Any]) -> Business:
        """Update explicitly allowed tenant fields."""
        unknown = set(data) - cls.BUSINESS_FIELDS
        if unknown:
            raise ValidationError(f"Unsupported business fields: {', '.join(sorted(unknown))}.")
        if "name" in data and not str(data["name"]).strip():
            raise ValidationError("Business name is required.")
        with get_session() as session:
            business = session.get(Business, business_id)
            if business is None:
                raise NotFoundError("Business was not found.")
            for field, value in data.items():
                setattr(business, field, value.strip() if isinstance(value, str) else value)
            session.flush()
            return business

    @staticmethod
    def get_services(business_id: int, active_only: bool = False) -> list[Service]:
        """List a tenant's services."""
        with get_session() as session:
            statement = select(Service).where(Service.business_id == business_id).order_by(Service.name)
            if active_only:
                statement = statement.where(Service.active.is_(True))
            return list(session.scalars(statement))

    @staticmethod
    def add_service(business_id: int, data: dict[str, Any]) -> Service:
        """Create a unique service for a business."""
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValidationError("Service name is required.")
        service = Service(
            business_id=business_id,
            name=name,
            description=_optional_text(data.get("description")),
            price=_price(data.get("price")),
            duration_minutes=_duration(data.get("duration_minutes")),
            active=bool(data.get("active", True)),
        )
        try:
            with get_session() as session:
                session.add(service)
                session.flush()
                return service
        except IntegrityError as exc:
            raise ValidationError("A service with this name already exists.") from exc

    @staticmethod
    def update_service(business_id: int, service_id: int, data: dict[str, Any]) -> Service:
        """Update one tenant-owned service."""
        with get_session() as session:
            service = session.scalar(select(Service).where(Service.id == service_id, Service.business_id == business_id))
            if service is None:
                raise NotFoundError("Service was not found.")
            if "name" in data:
                name = str(data["name"]).strip()
                if not name:
                    raise ValidationError("Service name is required.")
                service.name = name
            for field in ("description", "active"):
                if field in data:
                    setattr(service, field, _optional_text(data[field]) if field == "description" else bool(data[field]))
            if data.get("price", _MISSING) is not _MISSING:
                service.price = _price(data["price"])
            if data.get("duration_minutes", _MISSING) is not _MISSING:
                service.duration_minutes = _duration(data["duration_minutes"])
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValidationError("A service with this name already exists.") from exc
            return service

    @staticmethod
    def delete_service(business_id: int, service_id: int) -> None:
        """Delete one service owned by the selected tenant."""
        with get_session() as session:
            service = session.scalar(select(Service).where(Service.id == service_id, Service.business_id == business_id))
            if service is None:
                raise NotFoundError("Service was not found.")
            session.delete(service)

    @staticmethod
    def get_faq(business_id: int) -> list[FAQ]:
        """List FAQ entries ordered by priority then question."""
        with get_session() as session:
            return list(session.scalars(select(FAQ).where(FAQ.business_id == business_id).order_by(FAQ.priority.desc(), FAQ.question)))

    @staticmethod
    def add_faq(business_id: int, data: dict[str, Any]) -> FAQ:
        """Create a FAQ entry with a unique question for the tenant."""
        question, answer = str(data.get("question", "")).strip(), str(data.get("answer", "")).strip()
        if not question or not answer:
            raise ValidationError("FAQ question and answer are required.")
        try:
            with get_session() as session:
                faq = FAQ(business_id=business_id, question=question, answer=answer, category=_optional_text(data.get("category")), priority=_priority(data.get("priority")))
                session.add(faq)
                session.flush()
                return faq
        except IntegrityError as exc:
            raise ValidationError("An FAQ with this question already exists.") from exc

    @staticmethod
    def update_faq(business_id: int, faq_id: int, data: dict[str, Any]) -> FAQ:
        """Update one FAQ entry owned by the selected tenant."""
        with get_session() as session:
            faq = session.scalar(select(FAQ).where(FAQ.id == faq_id, FAQ.business_id == business_id))
            if faq is None:
                raise NotFoundError("FAQ was not found.")
            for field in ("question", "answer", "category"):
                if field in data:
                    value = _optional_text(data[field])
                    if field in {"question", "answer"} and not value:
                        raise ValidationError(f"FAQ {field} is required.")
                    setattr(faq, field, value)
            if "priority" in data:
                faq.priority = _priority(data["priority"])
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValidationError("An FAQ with this question already exists.") from exc
            return faq

    @staticmethod
    def delete_faq(business_id: int, faq_id: int) -> None:
        """Delete a tenant-owned FAQ entry."""
        with get_session() as session:
            faq = session.scalar(select(FAQ).where(FAQ.id == faq_id, FAQ.business_id == business_id))
            if faq is None:
                raise NotFoundError("FAQ was not found.")
            session.delete(faq)

    @staticmethod
    def search_services(business_id: int, query: str) -> list[Service]:
        """Search service names and descriptions without crossing tenant boundaries."""
        term = f"%{query.strip()}%"
        with get_session() as session:
            return list(session.scalars(select(Service).where(Service.business_id == business_id, or_(Service.name.ilike(term), Service.description.ilike(term))).order_by(Service.name)))

    @staticmethod
    def search_faq(business_id: int, query: str) -> list[FAQ]:
        """Search FAQ questions and answers for one tenant."""
        term = f"%{query.strip()}%"
        with get_session() as session:
            return list(session.scalars(select(FAQ).where(FAQ.business_id == business_id, or_(FAQ.question.ilike(term), FAQ.answer.ilike(term))).order_by(FAQ.priority.desc())))


def _optional_text(value: Any) -> str | None:
    return str(value).strip() or None if value is not None else None


_MISSING = object()


def _price(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValidationError("Price must be a valid number.") from exc
    if result < 0:
        raise ValidationError("Price cannot be negative.")
    return result


def _duration(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Duration must be a positive number of minutes.") from exc
    if result <= 0:
        raise ValidationError("Duration must be a positive number of minutes.")
    return result


def _priority(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Priority must be an integer.") from exc
