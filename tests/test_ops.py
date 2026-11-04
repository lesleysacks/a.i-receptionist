"""Health (Django liveness) and readiness (Flask) endpoint tests."""

from __future__ import annotations

import json

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.ops.views import _HEALTH_BODY_BYTES, _HEALTH_CONTENT_LENGTH


def _django():
    return Client()


def _django_csrf():
    """Client that applies CsrfViewMiddleware the same way Gunicorn does."""
    return Client(enforce_csrf_checks=True)


def test_health_is_ok_and_independent_of_database(monkeypatch):
    # Even if the SQLAlchemy engine used by Flask /ready is broken, liveness
    # must still report ok. Django /health must not query Django's database.
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("routes.ops.engine", _BrokenEngine())
    with CaptureQueriesContext(connection) as queries:
        resp = _django_csrf().get("/health")
    assert queries.captured_queries == []
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert "db down" not in resp.content.decode()


def test_health_preserves_flask_json_contract():
    resp = _django_csrf().get("/health")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"
    assert resp.content == b'{"status":"ok"}\n'
    assert resp.content == _HEALTH_BODY_BYTES
    assert resp["Content-Length"] == _HEALTH_CONTENT_LENGTH == "16"
    assert resp.json() == {"status": "ok"}
    assert "database" not in resp.json()
    assert "redis" not in resp.json()


def test_health_does_not_require_authentication():
    resp = _django().get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_flask_app_no_longer_owns_health(app_client):
    """Production uses wsgi.app; Flask itself must not still serve /health."""
    resp = app_client.get("/health")
    assert resp.status_code == 404
    assert resp.get_json(silent=True) != {"status": "ok"}


def test_health_query_string_is_ignored():
    resp = _django().get("/health?foo=bar")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_head_is_empty_with_get_content_length():
    resp = _django_csrf().head("/health")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"
    assert resp.content == b""
    assert resp["Content-Length"] == "16"


def test_health_unsupported_methods_are_405_not_403_with_csrf_enforced():
    client = _django_csrf()
    for method in ("post", "put", "patch", "delete", "options"):
        resp = getattr(client, method)("/health")
        assert resp.status_code == 405, f"{method} -> {resp.status_code}"
        assert resp.status_code != 403
        try:
            payload = json.loads(resp.content.decode() or "{}")
        except json.JSONDecodeError:
            payload = None
        assert payload != {"status": "ok"}


def test_health_trailing_slash_is_not_the_liveness_endpoint():
    resp = _django().get("/health/")
    assert resp.status_code == 404
    assert resp.content != b'{"status":"ok"}\n'


def test_health_nested_path_is_not_the_liveness_endpoint():
    resp = _django().get("/health/something")
    assert resp.status_code == 404
    assert resp.content != b'{"status":"ok"}\n'


def test_ready_reports_database_ok(app_client):
    resp = app_client.get("/ready")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


def test_ready_fails_when_database_unavailable(app_client, monkeypatch):
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("routes.ops.engine", _BrokenEngine())
    resp = app_client.get("/ready")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unavailable"
    # No secrets or internal details leak into the response.
    assert "db down" not in resp.get_data(as_text=True)
