"""Compatibility shim. New authentication uses Django User + Membership."""

from apex_receptionist.models.admin_user import AdminUser

__all__ = ["AdminUser"]
