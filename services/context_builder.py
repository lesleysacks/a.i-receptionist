"""Build a complete, structured business context for the AI layer."""

from __future__ import annotations

from services.business_service import BusinessService


class ContextBuilder:
    """Reads tenant configuration and exposes no persistence details to AI code."""

    def __init__(self, business_service: type[BusinessService] = BusinessService) -> None:
        self.business_service = business_service

    def build(self, business_id: int) -> dict[str, object]:
        """Return only owner-configured information relevant to customer replies."""
        business = self.business_service.get_business(business_id)
        services = self.business_service.get_services(business_id, active_only=True)
        faqs = self.business_service.get_faq(business_id)
        return {
            "business_name": business.name,
            "industry": business.industry,
            "description": business.description,
            "language": business.language,
            "timezone": business.timezone,
            "opening_hours": business.opening_hours,
            "services": [
                {"name": service.name, "description": service.description, "price": float(service.price) if service.price is not None else None, "duration_minutes": service.duration_minutes}
                for service in services
            ],
            "pricing": [{"service": service.name, "price": float(service.price) if service.price is not None else None, "currency": business.currency} for service in services],
            "faqs": [{"question": faq.question, "answer": faq.answer, "category": faq.category} for faq in faqs],
            "booking_rules": {"enabled": business.booking_enabled, "duration_minutes": business.booking_duration},
            "business_policies": {"booking_enabled": business.booking_enabled, "website_chat_enabled": business.website_chat_enabled, "whatsapp_enabled": business.whatsapp_enabled, "voice_enabled": business.voice_enabled, "email_enabled": business.email_enabled},
            "contact_details": {"phone": business.phone, "email": business.email, "website": business.website, "address": business.address, "city": business.city, "country": business.country},
        }
