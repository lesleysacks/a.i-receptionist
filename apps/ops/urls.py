from django.urls import path

from apps.ops import views

urlpatterns = [
    path("health", views.health, name="ops-health"),
]
