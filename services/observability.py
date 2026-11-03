"""Optional error tracking (Sentry).

The integration is entirely optional: without ``SENTRY_DSN`` the app runs
normally and nothing is sent. PII is not sent (``send_default_pii=False``).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_sentry() -> bool:
    """Initialise Sentry when SENTRY_DSN is set. Returns True if enabled."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0")),
            send_default_pii=False,
            environment=os.getenv("APP_ENV", "development"),
        )
        logger.info("Sentry error tracking enabled.")
        return True
    except Exception:
        logger.exception("Failed to initialise Sentry; continuing without it.")
        return False
