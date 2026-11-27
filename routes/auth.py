"""Shared-secret protection for the owner-facing admin API and dashboard."""

from __future__ import annotations

import hmac
import os
from functools import wraps

from flask import Response, request


def _supplied_secret() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    if request.authorization and request.authorization.password:
        return request.authorization.password
    return None


def check_admin() -> Response | None:
    """Return an error response unless the request carries ADMIN_PASSWORD."""
    expected = os.getenv("ADMIN_PASSWORD", "")
    if not expected:
        return Response("Admin access is disabled: set ADMIN_PASSWORD in .env.", 503)
    supplied = _supplied_secret()
    if supplied is None or not hmac.compare_digest(supplied.encode(), expected.encode()):
        return Response("Authentication required.", 401, {"WWW-Authenticate": 'Basic realm="AI Receptionist Admin"'})
    return None


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        error = check_admin()
        return error if error is not None else view(*args, **kwargs)
    return wrapper
