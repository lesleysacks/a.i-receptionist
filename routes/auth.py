"""Session-based authentication for the admin dashboard and API."""

from __future__ import annotations

import functools
import logging

from flask import Blueprint, jsonify, redirect, render_template_string, request, session, url_for

from services.auth_service import AuthService

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

_LOGIN_TEMPLATE = """
<!doctype html>
<title>Admin Login</title>
<h1>Admin Login</h1>
{% if error %}<p style="color:#b00020">{{ error }}</p>{% endif %}
<form method="post" action="{{ url_for('auth.login') }}">
  <p><label>Email <input type="email" name="email" autocomplete="username" required></label></p>
  <p><label>Password <input type="password" name="password" autocomplete="current-password" required></label></p>
  <p><button type="submit">Log in</button></p>
</form>
"""


def current_admin():
    """Return the logged-in AdminUser, or None."""
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    return AuthService.get_admin(admin_id)


def login_required(view):
    """Redirect browser requests to the login page when not authenticated."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        admin = current_admin()
        if admin is None:
            return redirect(url_for("auth.login"))
        return view(*args, admin=admin, **kwargs)

    return wrapped


@auth_bp.get("/login")
def login_form():
    if current_admin() is not None:
        return redirect(url_for("view_leads"))
    return render_template_string(_LOGIN_TEMPLATE, error=None)


@auth_bp.post("/login")
def login():
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    admin = AuthService.authenticate(email, password)
    if admin is None:
        logger.warning("Failed admin login attempt from %s", request.remote_addr or "unknown")
        return render_template_string(_LOGIN_TEMPLATE, error="Invalid email or password."), 401
    session.clear()
    session["admin_id"] = admin.id
    logger.info("Admin %s logged in (business_id=%s)", admin.id, admin.business_id)
    return redirect(url_for("view_leads"))


@auth_bp.post("/logout")
@auth_bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
