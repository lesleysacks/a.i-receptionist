"""Forms for the email-based custom user model."""

from __future__ import annotations

from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from apps.accounts.models import User


class ApexUserCreationForm(UserCreationForm):
    """Create a user with email as the identifier (no username field)."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)


class ApexUserChangeForm(UserChangeForm):
    """Edit a user without Django's default username field."""

    class Meta(UserChangeForm.Meta):
        model = User
        fields = (
            "email",
            "password",
            "is_active",
            "is_staff",
            "is_platform_admin",
            "is_superuser",
            "groups",
            "user_permissions",
        )
