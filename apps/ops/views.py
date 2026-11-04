"""Liveness endpoint. Does not touch the database, Redis, or tenant state."""

from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_http_methods

# Compact JSON plus newline matches the previous Flask ``jsonify`` body
# (``{"status":"ok"}\\n``, Content-Length 16).
_HEALTH_BODY = json.dumps({"status": "ok"}, separators=(",", ":")) + "\n"
_HEALTH_CONTENT_TYPE = "application/json"


@require_http_methods(["GET", "HEAD"])
def health(request: HttpRequest) -> HttpResponse:
    """Process liveness. GET returns JSON; HEAD is empty with the same type."""
    if request.method == "HEAD":
        return HttpResponse(status=200, content_type=_HEALTH_CONTENT_TYPE)
    return HttpResponse(_HEALTH_BODY, content_type=_HEALTH_CONTENT_TYPE)
