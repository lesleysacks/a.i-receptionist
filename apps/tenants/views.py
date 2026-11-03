"""Minimal platform-admin tenant listing."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render

from apps.tenants.models import Tenant
from apps.tenants.services import user_is_platform_admin


@login_required
def tenant_list(request):
    if not user_is_platform_admin(request.user):
        return HttpResponseForbidden("Platform administrator permission is required.")
    tenants = Tenant.objects.all().order_by("name")
    return render(request, "tenants/list.html", {"tenants": tenants})
