"""Liveness endpoint. Does not touch the database, Redis, or tenant state."""

from __future__ import annotations

import json

from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

# Compact JSON plus newline matches the previous Flask ``jsonify`` body
# (``{"status":"ok"}\\n``, Content-Length 16).
_HEALTH_BODY = json.dumps({"status": "ok"}, separators=(",", ":")) + "\n"
_HEALTH_BODY_BYTES = _HEALTH_BODY.encode("ascii")
_HEALTH_CONTENT_TYPE = "application/json"
_HEALTH_CONTENT_LENGTH = str(len(_HEALTH_BODY_BYTES))


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def health(request: HttpRequest) -> HttpResponse:
    """Process liveness. CSRF is exempt so disallowed methods return 405, not 403.

    HEAD keeps Flask's empty body with Content-Length of the GET payload.
    csrf_exempt is the outer decorator so Django's CsrfViewMiddleware sees it
    on the resolved callback; require_http_methods still rejects POST/PUT/etc.
    """
    response = HttpResponse(_HEALTH_BODY_BYTES, content_type=_HEALTH_CONTENT_TYPE)
    if request.method == "HEAD":
        # Empty the body after length is known; Gunicorn will not send a HEAD
        # body but must advertise the GET Content-Length.
        response.content = b""
        response["Content-Length"] = _HEALTH_CONTENT_LENGTH
    return response
