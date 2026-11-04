"""Django settings for the Apex management platform.

Secrets and database coordinates come only from the environment. The
receptionist engine keeps using SQLAlchemy/Alembic for its own tables; Django
owns accounts, tenants, memberships, and audit events in the same database.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
DEBUG = APP_ENV == "development" and os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}

SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("DJANGO_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY") or ""
if not SECRET_KEY:
    if APP_ENV == "production":
        raise RuntimeError("SECRET_KEY must be set in production.")
    SECRET_KEY = "django-insecure-dev-only-not-for-production"


def allowed_hosts_for_env(app_env: str, raw: str | None) -> list[str]:
    """Parse DJANGO_ALLOWED_HOSTS. Production must name explicit hosts."""
    env = (app_env or "development").strip().lower()
    hosts = [host.strip() for host in (raw or "").split(",") if host.strip()]
    if env == "production":
        if not hosts or hosts == ["*"]:
            raise RuntimeError("DJANGO_ALLOWED_HOSTS must list explicit hosts in production.")
        return hosts
    if not hosts:
        hosts = ["localhost", "127.0.0.1"]
    if env == "testing":
        return sorted(set(hosts) | {"testserver", "localhost", "127.0.0.1"})
    return hosts


ALLOWED_HOSTS = allowed_hosts_for_env(APP_ENV, os.getenv("DJANGO_ALLOWED_HOSTS"))


def _database_from_url(url: str) -> dict:
    url = (url or "sqlite:///receptionist.db").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("sqlite:///"):
        name = url[len("sqlite:///"):]
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": name or str(BASE_DIR / "receptionist.db"),
        }
    parsed = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": (parsed.path or "/apex").lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
    }


DATABASES = {"default": _database_from_url(os.getenv("DATABASE_URL", "sqlite:///receptionist.db"))}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.tenants",
    "apps.audit",
    "apps.intelligence",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "apex.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "apps" / "accounts" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "apex.wsgi.application"

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-za"
TIME_ZONE = "Africa/Johannesburg"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = APP_ENV == "production" and os.getenv("SESSION_COOKIE_SECURE", "true").lower() in {"1", "true", "yes", "on"}
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("MAX_CONTENT_LENGTH", str(64 * 1024)))
DATA_UPLOAD_MAX_NUMBER_FIELDS = 100

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/accounts/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
