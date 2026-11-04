"""WSGI prefix rules for the dual Flask/Django process.

This module must not import Flask or Django. Tests can exercise routing
without booting either application or calling external APIs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

# Exact Flask prefixes from the production dispatcher in ``wsgi.py``.
# Nested paths match ``prefix`` or ``prefix + "/"``; similar names do not.
FLASK_PREFIXES: tuple[str, ...] = (
    "/whatsapp",
    "/leads",
    "/admin",
    "/dashboard",
    "/login",
    "/logout",
    "/health",
    "/ready",
)

FLASK_EXACT_PATHS: frozenset[str] = frozenset({"/"})

StartResponse = Callable[..., Any]
WsgiApp = Callable[[dict, StartResponse], Iterable[bytes]]


def flask_owns_path(path: str | None) -> bool:
    """Return True when the dual-stack dispatcher must send *path* to Flask."""
    path = path or ""
    if path in FLASK_EXACT_PATHS:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in FLASK_PREFIXES)


def dispatch_wsgi(
    environ: dict,
    start_response: StartResponse,
    flask_app: WsgiApp,
    django_app: WsgiApp,
) -> Iterable[bytes]:
    """Forward one WSGI call to Flask or Django without mutating *environ*."""
    if flask_owns_path(environ.get("PATH_INFO") or ""):
        return flask_app(environ, start_response)
    return django_app(environ, start_response)
