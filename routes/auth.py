"""Session-based authentication for the admin dashboard and API."""

from __future__ import annotations

import functools
import logging

from flask import Blueprint, redirect, render_template, request, session, url_for

from services.auth_service import AuthService
from services.rate_limiter import build_login_rate_limiter

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# Redis-backed when REDIS_URL is reachable (shared across workers), else local.
login_rate_limiter = build_login_rate_limiter()


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
            return redirect(url_for("auth.login_form"))
        return view(*args, admin=admin, **kwargs)

    return wrapped


@auth_bp.get("/login")
def login_form():
    if current_admin() is not None:
        return redirect(url_for("dashboard.index"))
    return render_template("login.html", error=None)


@auth_bp.post("/login")
def login():
    client_key = request.remote_addr or "unknown"
    if login_rate_limiter.is_blocked(client_key):
        logger.warning("Login temporarily blocked for client %s", client_key)
        return render_template("login.html", error="Too many attempts. Please try again later."), 429

    email = request.form.get("email", "")
    password = request.form.get("password", "")
    admin = AuthService.authenticate(email, password)
    if admin is None:
        login_rate_limiter.register_failure(client_key)
        logger.warning("Failed admin login attempt from %s", client_key)
        # Generic message: never reveal whether the account exists.
        return render_template("login.html", error="Invalid email or password."), 401

    login_rate_limiter.reset(client_key)
    session.clear()
    session["admin_id"] = admin.id
    logger.info("Admin %s logged in (business_id=%s)", admin.id, admin.business_id)
    return redirect(url_for("dashboard.index"))


@auth_bp.post("/logout")
@auth_bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_form"))
