from django.urls import path

from apps.accounts import views

urlpatterns = [
    path("login/", views.login_view, name="accounts-login"),
    path("logout/", views.logout_view, name="accounts-logout"),
    path("", views.home_view, name="accounts-home"),
]
