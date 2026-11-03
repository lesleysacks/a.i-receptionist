"""Django session login/logout for the Apex management plane."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audit.services import record_audit
from apps.tenants.models import Membership


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts-home")
    error = None
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=email, password=password)
        if user is None or not user.is_active:
            record_audit(actor=None, action="auth.login_failed", metadata={"email_domain": email.split("@")[-1] if "@" in email else None})
            error = "Invalid email or password."
        else:
            login(request, user)
            record_audit(actor=user, action="auth.login_success")
            return redirect("accounts-home")
    return render(request, "accounts/login.html", {"error": error})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    if request.user.is_authenticated:
        record_audit(actor=request.user, action="auth.logout")
    logout(request)
    return redirect("accounts-login")


@login_required
def home_view(request):
    memberships = (
        Membership.objects.filter(user=request.user, status=Membership.Status.ACTIVE)
        .select_related("tenant")
        .order_by("tenant__name")
    )
    return render(
        request,
        "accounts/home.html",
        {
            "memberships": memberships,
            "is_platform_admin": bool(getattr(request.user, "is_platform_admin", False)),
        },
    )
