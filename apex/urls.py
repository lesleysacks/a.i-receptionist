"""Root URL configuration for the Apex Django platform."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("platform/django-admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("platform/", include("apps.tenants.urls")),
]
