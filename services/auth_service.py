"""Administrator authentication: hashed passwords and credential checks."""

from __future__ import annotations

from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_session
from models.admin_user import AdminUser
from services.business_service import NotFoundError, ValidationError


class AuthService:
    """Create and authenticate business-scoped admin accounts.

    Passwords are only ever stored as salted hashes (via werkzeug); the plaintext
    is never persisted or logged.
    """

    @staticmethod
    def create_admin(business_id: int, email: str, password: str) -> AdminUser:
        email = (email or "").strip().lower()
        if not email:
            raise ValidationError("Admin email is required.")
        if not password or len(password) < 8:
            raise ValidationError("Admin password must be at least 8 characters.")
        with get_session() as session:
            existing = session.scalar(select(AdminUser).where(AdminUser.email == email))
            if existing is not None:
                raise ValidationError("An admin with this email already exists.")
            admin = AdminUser(
                business_id=business_id,
                email=email,
                password_hash=generate_password_hash(password),
            )
            session.add(admin)
            session.flush()
            return admin

    @staticmethod
    def authenticate(email: str, password: str) -> AdminUser | None:
        """Return the admin when credentials are valid, otherwise None."""
        email = (email or "").strip().lower()
        if not email or not password:
            return None
        with get_session() as session:
            admin = session.scalar(select(AdminUser).where(AdminUser.email == email))
            if admin is None:
                return None
            if not check_password_hash(admin.password_hash, password):
                return None
            return admin

    @staticmethod
    def get_admin(admin_id: int) -> AdminUser | None:
        with get_session() as session:
            return session.get(AdminUser, admin_id)
