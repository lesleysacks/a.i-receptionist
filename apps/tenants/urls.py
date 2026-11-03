from django.urls import path

from apps.tenants import views

urlpatterns = [
    path("tenants/", views.tenant_list, name="platform-tenants"),
]
