"""C1: production DJANGO_ALLOWED_HOSTS validation and import-time failure."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from apex.settings import (
    InvalidDjangoAllowedHosts,
    allowed_hosts_for_env,
    parse_allowed_hosts,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_production_with_valid_hosts_returns_explicit_list():
    assert allowed_hosts_for_env("production", "apex.example") == ["apex.example"]
    assert allowed_hosts_for_env("production", "apex.example, www.apex.example") == [
        "apex.example",
        "www.apex.example",
    ]
    assert allowed_hosts_for_env("production", ".apex.example") == [".apex.example"]


def test_production_with_missing_hosts_raises_actionable_error():
    with pytest.raises(InvalidDjangoAllowedHosts, match="DJANGO_ALLOWED_HOSTS") as missing:
        allowed_hosts_for_env("production", None)
    assert "APP_ENV=production" in str(missing.value)
    assert "apex.example.com" in str(missing.value)

    with pytest.raises(InvalidDjangoAllowedHosts, match="DJANGO_ALLOWED_HOSTS"):
        allowed_hosts_for_env("production", "")


def test_production_with_wildcard_hosts_is_rejected():
    for raw in ("*", " * ", "*,apex.example", "apex.example,*", "*.apex.example"):
        with pytest.raises(InvalidDjangoAllowedHosts, match="rejected"):
            allowed_hosts_for_env("production", raw)


def test_production_with_malformed_or_empty_host_entries_is_rejected():
    assert parse_allowed_hosts(",,,") == []
    assert parse_allowed_hosts("apex.example, , ") == ["apex.example"]

    with pytest.raises(InvalidDjangoAllowedHosts):
        allowed_hosts_for_env("production", " , , ")

    with pytest.raises(InvalidDjangoAllowedHosts, match="rejected"):
        allowed_hosts_for_env("production", "https://apex.example")

    with pytest.raises(InvalidDjangoAllowedHosts, match="rejected"):
        allowed_hosts_for_env("production", "apex.example/admin")

    with pytest.raises(InvalidDjangoAllowedHosts, match="rejected"):
        allowed_hosts_for_env("production", "apex example.com")


def test_development_configuration_defaults_to_localhost():
    assert allowed_hosts_for_env("development", None) == ["localhost", "127.0.0.1"]
    assert allowed_hosts_for_env("development", "") == ["localhost", "127.0.0.1"]
    assert allowed_hosts_for_env("development", "dev.local") == ["dev.local"]
    assert allowed_hosts_for_env("development", "*") == ["*"]


def test_testing_configuration_includes_django_testserver():
    hosts = allowed_hosts_for_env("testing", None)
    assert "testserver" in hosts
    assert "localhost" in hosts
    assert "127.0.0.1" in hosts


def _subprocess_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["DJANGO_SETTINGS_MODULE"] = "apex.settings"
    env["SECRET_KEY"] = "m0-import-secret"
    env["DATABASE_URL"] = "sqlite:///:memory:"
    env["TWILIO_ACCOUNT_SID"] = "AC" + "x" * 32
    env["TWILIO_AUTH_TOKEN"] = "m0_placeholder_token"
    env.pop("DJANGO_ALLOWED_HOSTS", None)
    env.update(overrides)
    return env


def _run_python(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_settings_import_succeeds_in_production_with_valid_hosts():
    result = _run_python(
        "import apex.settings as s; print(','.join(s.ALLOWED_HOSTS))",
        _subprocess_env(APP_ENV="production", DJANGO_ALLOWED_HOSTS="apex.example"),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "apex.example"


def test_settings_import_fails_in_production_when_hosts_missing():
    result = _run_python(
        "import apex.settings",
        _subprocess_env(APP_ENV="production", DJANGO_ALLOWED_HOSTS=""),
    )
    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr
    assert "InvalidDjangoAllowedHosts" in result.stderr or "explicit hostnames" in result.stderr


def test_settings_import_fails_in_production_when_hosts_are_wildcard():
    result = _run_python(
        "import apex.settings",
        _subprocess_env(APP_ENV="production", DJANGO_ALLOWED_HOSTS="*"),
    )
    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_settings_import_succeeds_in_development_without_hosts():
    result = _run_python(
        "import apex.settings as s; print(','.join(s.ALLOWED_HOSTS))",
        _subprocess_env(APP_ENV="development"),
    )
    assert result.returncode == 0, result.stderr
    assert "localhost" in result.stdout


def test_wsgi_import_fails_closed_under_invalid_production_hosts():
    result = _run_python(
        "import wsgi",
        _subprocess_env(APP_ENV="production", DJANGO_ALLOWED_HOSTS="*"),
    )
    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_wsgi_import_succeeds_under_valid_production_hosts():
    result = _run_python(
        "import wsgi; print(wsgi.flask_owns_path('/whatsapp'), wsgi.flask_owns_path('/accounts/'))",
        _subprocess_env(APP_ENV="production", DJANGO_ALLOWED_HOSTS="apex.example"),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True False"
