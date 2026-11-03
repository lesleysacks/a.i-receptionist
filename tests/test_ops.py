"""Health (liveness) and readiness endpoint tests."""

from __future__ import annotations


def test_health_is_ok_and_independent_of_database(app_client, monkeypatch):
    # Even if the DB is broken, liveness must still report ok.
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("routes.ops.engine", _BrokenEngine())
    resp = app_client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


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
