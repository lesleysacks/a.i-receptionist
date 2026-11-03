"""Environment-aware application configuration.

Selects a configuration profile from ``APP_ENV`` (development | testing |
production) and pulls secrets/tunables from the environment. No secrets or
credentials are hard-coded here.
"""

from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger(__name__)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class BaseConfig:
    APP_ENV = "production"
    DEBUG = False
    TESTING = False

    # Sessions / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = True

    # CSRF (Flask-WTF)
    WTF_CSRF_ENABLED = True

    # Login abuse protection
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW_SECONDS = 300
    LOGIN_LOCKOUT_SECONDS = 300


class DevelopmentConfig(BaseConfig):
    APP_ENV = "development"
    DEBUG = _bool("FLASK_DEBUG", False)
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)


class TestingConfig(BaseConfig):
    APP_ENV = "testing"
    TESTING = True
    SESSION_COOKIE_SECURE = False
    # Disabled globally so existing tests need no token; CSRF-specific tests
    # re-enable it explicitly to assert protection works.
    WTF_CSRF_ENABLED = False


class ProductionConfig(BaseConfig):
    APP_ENV = "production"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)


_PROFILES = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def select_config() -> type[BaseConfig]:
    return _PROFILES.get(os.getenv("APP_ENV", "development").strip().lower(), DevelopmentConfig)


def resolve_secret_key(profile: type[BaseConfig]) -> str:
    """Return the session secret, requiring it in production."""
    key = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
    if key:
        return key
    if profile.APP_ENV == "production":
        raise RuntimeError("SECRET_KEY must be set in production.")
    logger.warning("SECRET_KEY is not set; using an ephemeral key. Admin sessions will not survive a restart.")
    return secrets.token_hex(32)


def apply_config(app) -> None:
    """Apply the selected profile plus dynamic secrets to a Flask app."""
    profile = select_config()
    app.config.from_object(profile)
    app.config["APP_ENV"] = profile.APP_ENV
    app.secret_key = resolve_secret_key(profile)
    # Runtime overrides from the environment (tunable per deployment).
    app.config["SESSION_COOKIE_SECURE"] = _bool("SESSION_COOKIE_SECURE", app.config["SESSION_COOKIE_SECURE"])
    app.config["LOGIN_MAX_ATTEMPTS"] = _int("LOGIN_MAX_ATTEMPTS", app.config["LOGIN_MAX_ATTEMPTS"])
    app.config["LOGIN_WINDOW_SECONDS"] = _int("LOGIN_WINDOW_SECONDS", app.config["LOGIN_WINDOW_SECONDS"])
    app.config["LOGIN_LOCKOUT_SECONDS"] = _int("LOGIN_LOCKOUT_SECONDS", app.config["LOGIN_LOCKOUT_SECONDS"])
