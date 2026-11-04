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


READY_OK_NO_REDIS = b'{"checks":{"database":"ok"},"status":"ready"}\n'
READY_OK_NO_REDIS_LENGTH = "46"
READY_FAIL_DB = b'{"checks":{"database":"unavailable"},"status":"not_ready"}\n'
READY_OK_WITH_REDIS = b'{"checks":{"database":"ok","redis":"ok"},"status":"ready"}\n'
READY_FAIL_REDIS = b'{"checks":{"database":"ok","redis":"unavailable"},"status":"not_ready"}\n'


def test_ready_reports_database_ok(app_client):
    resp = app_client.get("/ready")
    assert resp.status_code == 200
    assert resp.content_type == "application/json"
    assert resp.get_data() == READY_OK_NO_REDIS
    assert resp.headers["Content-Length"] == READY_OK_NO_REDIS_LENGTH
    body = resp.get_json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok"}
    assert "redis" not in body["checks"]


def test_ready_fails_when_database_unavailable(app_client, monkeypatch):
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("db down postgresql://secret:password@db/receptionist")

    monkeypatch.setattr("routes.ops.engine", _BrokenEngine())
    resp = app_client.get("/ready")
    assert resp.status_code == 503
    assert resp.content_type == "application/json"
    assert resp.get_data() == READY_FAIL_DB
    body = resp.get_json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unavailable"
    text = resp.get_data(as_text=True)
    assert "db down" not in text
    assert "password" not in text
    assert "postgresql://" not in text


def test_ready_omits_redis_when_url_absent(app_client, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    resp = app_client.get("/ready")
    assert resp.status_code == 200
    assert resp.get_json()["checks"] == {"database": "ok"}


def test_ready_reports_redis_ok_when_configured_and_reachable(app_client, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr("routes.ops.redis_is_reachable", lambda: True)
    resp = app_client.get("/ready")
    assert resp.status_code == 200
    assert resp.get_data() == READY_OK_WITH_REDIS
    assert resp.get_json()["checks"]["redis"] == "ok"


def test_ready_fails_when_redis_configured_but_unavailable(app_client, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr("routes.ops.redis_is_reachable", lambda: False)
    resp = app_client.get("/ready")
    assert resp.status_code == 503
    assert resp.get_data() == READY_FAIL_REDIS
    body = resp.get_json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "unavailable"
    assert "redis://" not in resp.get_data(as_text=True)


def test_ready_head_is_empty_with_get_content_length(app_client):
    resp = app_client.head("/ready")
    assert resp.status_code == 200
    assert resp.content_type == "application/json"
    assert resp.get_data() == b""
    assert resp.headers["Content-Length"] == READY_OK_NO_REDIS_LENGTH


def test_ready_query_string_is_ignored(app_client):
    resp = app_client.get("/ready?foo=bar")
    assert resp.status_code == 200
    assert resp.get_data() == READY_OK_NO_REDIS


def test_ready_trailing_slash_is_404(app_client):
    resp = app_client.get("/ready/")
    assert resp.status_code == 404
    assert resp.get_json(silent=True) != {"status": "ready", "checks": {"database": "ok"}}


def test_ready_options_is_200(app_client):
    resp = app_client.options("/ready")
    assert resp.status_code == 200
    assert resp.get_data() == b""


def test_ready_unsupported_methods_are_405(app_client):
    for method in ("post", "put", "patch", "delete"):
        resp = getattr(app_client, method)("/ready")
        assert resp.status_code == 405, f"{method} -> {resp.status_code}"
        assert resp.status_code != 403
        assert resp.get_json(silent=True) != {"status": "ready", "checks": {"database": "ok"}}


def test_ready_get_and_post_with_csrf_enabled():
    import app as app_module

    app_module.app.config["WTF_CSRF_ENABLED"] = True
    try:
        client = app_module.app.test_client()
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.get_data() == READY_OK_NO_REDIS
        resp = client.post("/ready")
        assert resp.status_code == 405
        assert resp.status_code != 400
    finally:
        app_module.app.config["WTF_CSRF_ENABLED"] = False


def test_ready_does_not_create_a_new_engine(app_client, monkeypatch):
    import database as database_module

    created = []
    real = database_module.create_engine

    def wrapping(*args, **kwargs):
        created.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(database_module, "create_engine", wrapping)
    resp = app_client.get("/ready")
    assert resp.status_code == 200
    assert created == []
