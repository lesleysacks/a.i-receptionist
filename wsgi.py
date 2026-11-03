"""Production WSGI entry point.

Gunicorn:  gunicorn -c gunicorn.conf.py wsgi:app

Flask serves the receptionist webhook, dashboard, and ops endpoints.
Django serves /accounts/ and /platform/.
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apex.settings")

from app import app as flask_app  # noqa: E402
from apex.wsgi import application as django_app  # noqa: E402

FLASK_PREFIXES = (
    "/whatsapp",
    "/leads",
    "/admin",
    "/dashboard",
    "/login",
    "/logout",
    "/health",
    "/ready",
)


def app(environ, start_response):
    path = environ.get("PATH_INFO") or ""
    if path == "/" or any(path == prefix or path.startswith(prefix + "/") for prefix in FLASK_PREFIXES):
        return flask_app(environ, start_response)
    return django_app(environ, start_response)


__all__ = ["app", "flask_app"]
