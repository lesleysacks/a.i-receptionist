"""Create an InterSacks platform administrator (no public self-service)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.tenants.models import Membership, Tenant
from apps.tenants.services import grant_membership


class Command(BaseCommand):
    help = "Create a platform administrator. Does not expose public registration."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        if len(password) < 8:
            raise CommandError("Password must be at least 8 characters.")
        user, created = User.objects.get_or_create(email=email, defaults={"is_platform_admin": True, "is_staff": True})
        if not created and not user.is_platform_admin:
            user.is_platform_admin = True
            user.is_staff = True
        user.set_password(password)
        user.is_active = True
        user.save()
        tenant, _ = Tenant.objects.get_or_create(
            slug="intersacks-platform",
            defaults={"name": "InterSacks Digital", "service_mode": Tenant.ServiceMode.MANAGED},
        )
        grant_membership(user=user, tenant=tenant, role=Membership.Role.PLATFORM_ADMIN, actor=user)
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} platform admin {email}"))
