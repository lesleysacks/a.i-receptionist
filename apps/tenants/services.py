"""Tenant provisioning and access-control helpers.

Trusted tenant identity is always derived from the authenticated principal
(membership or explicit platform-admin targeting), never from an unchecked
request body field.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.tenants.models import Membership, Tenant


class AccessDenied(PermissionError):
    """Raised when a principal must not see or change the requested tenant."""


@dataclass(frozen=True)
class Principal:
    """Flask-compatible view of the signed-in user for receptionist HTTP."""

    id: int
    email: str
    business_id: int | None
    tenant_id: int | None
    role: str
    is_platform_admin: bool
    membership_id: int | None = None

    @property
    def can_write(self) -> bool:
        return self.is_platform_admin or self.role in {
            Membership.Role.TENANT_ADMIN,
            Membership.Role.PLATFORM_ADMIN,
        }

    @property
    def can_read(self) -> bool:
        return self.is_platform_admin or self.role in {
            Membership.Role.TENANT_ADMIN,
            Membership.Role.TENANT_MEMBER,
            Membership.Role.PLATFORM_ADMIN,
        }


def user_is_platform_admin(user: User | None) -> bool:
    if user is None or not getattr(user, "is_active", False):
        return False
    if getattr(user, "is_platform_admin", False):
        return True
    return Membership.objects.filter(
        user=user,
        role=Membership.Role.PLATFORM_ADMIN,
        status=Membership.Status.ACTIVE,
    ).exists()


def ensure_tenant_for_business(business_id: int, name: str, service_mode: str = Tenant.ServiceMode.MANAGED) -> Tenant:
    """Create or return the Django tenant that owns a receptionist business."""
    existing = Tenant.objects.filter(receptionist_business_id=business_id).first()
    if existing:
        return existing
    base = slugify(name) or "tenant"
    slug = f"{base}-{business_id}"
    suffix = 2
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base}-{business_id}-{suffix}"
        suffix += 1
    return Tenant.objects.create(
        name=name,
        slug=slug,
        status=Tenant.Status.ACTIVE,
        service_mode=service_mode,
        receptionist_business_id=business_id,
    )


def grant_membership(
    *,
    user: User,
    tenant: Tenant,
    role: str,
    actor: User | None = None,
) -> Membership:
    membership, created = Membership.objects.update_or_create(
        user=user,
        tenant=tenant,
        defaults={"role": role, "status": Membership.Status.ACTIVE},
    )
    if role == Membership.Role.PLATFORM_ADMIN:
        user.is_platform_admin = True
        user.is_staff = True
        user.save(update_fields=["is_platform_admin", "is_staff"])
    record_audit(
        actor=actor or user,
        tenant=tenant,
        action="membership.granted" if created else "membership.updated",
        target_type="membership",
        target_id=str(membership.id),
        metadata={"role": role, "user_id": user.id},
    )
    return membership


def principal_for_user(user: User, *, business_id: int | None = None, tenant_id: int | None = None) -> Principal | None:
    """Build a Principal from memberships. Platform admins still need a target for tenant data."""
    if user is None or not user.is_active:
        return None
    platform = user_is_platform_admin(user)
    memberships = Membership.objects.filter(user=user, status=Membership.Status.ACTIVE).select_related("tenant")

    chosen = None
    if tenant_id is not None:
        chosen = memberships.filter(tenant_id=tenant_id).first()
    elif business_id is not None:
        chosen = memberships.filter(tenant__receptionist_business_id=business_id).first()
    elif memberships.count() == 1:
        chosen = memberships.first()
    else:
        chosen = memberships.filter(role=Membership.Role.TENANT_ADMIN).first() or memberships.first()

    if chosen and chosen.is_active:
        return Principal(
            id=user.id,
            email=user.email,
            business_id=chosen.tenant.receptionist_business_id,
            tenant_id=chosen.tenant_id,
            role=chosen.role,
            is_platform_admin=platform,
            membership_id=chosen.id,
        )
    if platform:
        return Principal(
            id=user.id,
            email=user.email,
            business_id=None,
            tenant_id=None,
            role=Membership.Role.PLATFORM_ADMIN,
            is_platform_admin=True,
            membership_id=None,
        )
    return None


def resolve_business_id_for_user(
    user: User,
    *,
    requested_business_id: int | None = None,
    allow_platform_unscoped: bool = False,
) -> int:
    """Return the business id this user may act on, or raise AccessDenied.

    Client requests must not pass an arbitrary tenant id to escalate. A
    tenant member may only use their membership's business. A platform admin
    must name the target business explicitly unless allow_platform_unscoped.
    """
    if user is None or not user.is_active:
        raise AccessDenied("Authentication required.")
    platform = user_is_platform_admin(user)

    if platform:
        if requested_business_id is None:
            if allow_platform_unscoped:
                raise AccessDenied("Platform administrators must select a tenant explicitly.")
            raise AccessDenied("X-Business-Id is required for platform administrators.")
        tenant = Tenant.objects.filter(receptionist_business_id=requested_business_id).first()
        if tenant is None:
            raise AccessDenied("Tenant was not found.")
        record_audit(
            actor=user,
            tenant=tenant,
            action="tenant.privileged_access",
            target_type="business",
            target_id=str(requested_business_id),
        )
        return requested_business_id

    memberships = Membership.objects.filter(user=user, status=Membership.Status.ACTIVE).select_related("tenant")
    if requested_business_id is not None:
        membership = memberships.filter(tenant__receptionist_business_id=requested_business_id).first()
        if membership is None or not membership.is_active:
            raise AccessDenied("You do not have access to that tenant.")
        return requested_business_id

    active = [m for m in memberships if m.is_active and m.tenant.receptionist_business_id is not None]
    if len(active) == 1:
        return active[0].tenant.receptionist_business_id
    raise AccessDenied("No tenant is in scope for this account.")


@transaction.atomic
def create_tenant_admin(*, business_id: int, business_name: str, email: str, password: str) -> tuple[User, Tenant, Membership]:
    """Provision Django user + tenant membership for a receptionist business."""
    email = (email or "").strip().lower()
    tenant = ensure_tenant_for_business(business_id, business_name)
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(email=email, password=password)
    else:
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
    membership = grant_membership(user=user, tenant=tenant, role=Membership.Role.TENANT_ADMIN, actor=user)
    return user, tenant, membership
