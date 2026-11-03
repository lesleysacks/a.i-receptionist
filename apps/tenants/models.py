"""Tenant and membership models for Apex multi-tenancy."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Tenant(models.Model):
    """A client organisation. Receptionist data is linked via business id."""

    class Status(models.TextChoices):
        PROVISIONING = "provisioning", "Provisioning"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    class ServiceMode(models.TextChoices):
        MANAGED = "managed", "Managed service"
        SELF_SERVICE = "self_service", "Self-service"

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    service_mode = models.CharField(
        max_length=32,
        choices=ServiceMode.choices,
        default=ServiceMode.MANAGED,
    )
    receptionist_business_id = models.IntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text="SQLAlchemy businesses.id owned by this tenant.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class Membership(models.Model):
    """A user's role on one tenant. Platform admins may also have a User flag."""

    class Role(models.TextChoices):
        PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform admin"
        TENANT_ADMIN = "TENANT_ADMIN", "Tenant admin"
        TENANT_MEMBER = "TENANT_MEMBER", "Tenant member"

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=32, choices=Role.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "tenant")
        ordering = ("tenant_id", "user_id")

    def __str__(self) -> str:
        return f"{self.user_id}:{self.tenant_id}:{self.role}"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE and self.tenant.is_active

    @property
    def can_write(self) -> bool:
        return self.is_active and self.role in {self.Role.TENANT_ADMIN, self.Role.PLATFORM_ADMIN}
