"""Twilio webhook signature helpers.

Twilio signs the public webhook URL. Behind a reverse proxy Flask's
``request.url`` often does not match that URL, so production deployments
should set ``WEBHOOK_BASE_URL`` to the canonical public origin.
"""

from __future__ import annotations

import os

from twilio.request_validator import RequestValidator


def signed_webhook_url(request, path: str = "/whatsapp") -> str:
    """Return the URL Twilio used when computing X-Twilio-Signature.

    Prefer an explicitly configured public base URL. Fall back to the request
    URL so local tests and unsigned-proxy-free development keep working.
    """
    base = (os.getenv("WEBHOOK_BASE_URL") or "").strip().rstrip("/")
    if base:
        query = request.query_string.decode("utf-8") if getattr(request, "query_string", b"") else ""
        suffix = f"{path}?{query}" if query else path
        return f"{base}{suffix}"
    return request.url


def is_valid_twilio_signature(request, auth_token: str, path: str = "/whatsapp") -> bool:
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature or not auth_token:
        return False
    params = {k: v for k, v in request.form.items()}
    validator = RequestValidator(auth_token)
    return validator.validate(signed_webhook_url(request, path=path), params, signature)
