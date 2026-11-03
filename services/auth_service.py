"""Administrator authentication backed by Django User + Membership.

Flask session still holds the user id for the receptionist UI. Passwords are
hashed by Django. The legacy AdminUser table is no longer written.
"""

from __future__ import annotations

from apex.setup_django import setup_django

setup_django()

from apps.tenants.services import Principal, create_tenant_admin, principal_for_user
from services.business_service import BusinessService, NotFoundError, ValidationError


class AuthService:
    """Create and authenticate tenant-scoped admin accounts via Django."""

    @staticmethod
    def create_admin(business_id: int, email: str, password: str):
        setup_django()
        email = (email or "").strip().lower()
        if not email:
            raise ValidationError("Admin email is required.")
        if not password or len(password) < 8:
            raise ValidationError("Admin password must be at least 8 characters.")
        from apps.accounts.models import User

        if User.objects.filter(email=email).exists():
            existing = User.objects.get(email=email)
            # Allow the same test helper email on a reset database, but not two
            # live accounts with one email across tenants.
            if existing.memberships.exclude(tenant__receptionist_business_id=business_id).exists():
                raise ValidationError("An admin with this email already exists.")
        try:
            business = BusinessService.get_business(business_id)
        except NotFoundError as exc:
            raise ValidationError("Business was not found.") from exc
        user, _tenant, _membership = create_tenant_admin(
            business_id=business_id,
            business_name=business.name,
            email=email,
            password=password,
        )
        return user

    @staticmethod
    def authenticate(email: str, password: str) -> Principal | None:
        setup_django()
        email = (email or "").strip().lower()
        if not email or not password:
            return None
        from django.contrib.auth import authenticate

        user = authenticate(username=email, password=password)
        if user is None or not user.is_active:
            return None
        return principal_for_user(user)

    @staticmethod
    def get_admin(admin_id: int) -> Principal | None:
        setup_django()
        from apps.accounts.models import User

        try:
            user = User.objects.get(pk=admin_id, is_active=True)
        except User.DoesNotExist:
            return None
        return principal_for_user(user)
