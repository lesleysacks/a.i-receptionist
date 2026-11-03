"""Compatibility shim."""

from apex_receptionist.services.business_service import BusinessService, NotFoundError, ValidationError

__all__ = ["BusinessService", "NotFoundError", "ValidationError"]
