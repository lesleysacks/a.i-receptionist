"""Production WSGI entry point.

Gunicorn:  gunicorn -c gunicorn.conf.py wsgi:app

Flask serves the receptionist webhook, dashboard, JSON /admin, and /ready.
Django serves /health, /accounts/, and /platform/.
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apex.settings")

from apex.http_dispatch import (  # noqa: E402
    FLASK_PREFIXES,
    dispatch_wsgi,
    flask_owns_path,
)
from app import app as flask_app  # noqa: E402
from apex.wsgi import application as django_app  # noqa: E402


def app(environ, start_response):
    """Dispatch one WSGI request to Flask or Django by PATH_INFO prefix."""
    return dispatch_wsgi(
        environ,
        start_response,
        flask_app=flask_app,
        django_app=django_app,
    )


__all__ = ["app", "django_app", "flask_app", "FLASK_PREFIXES", "flask_owns_path"]
