"""Login abuse protection: rate limiting and temporary lockout."""

from __future__ import annotations

import pytest

from tests.conftest import login


@pytest.fixture
def rate_limited_app(app_client):
    import app as app_module

    app_module.app.config["LOGIN_MAX_ATTEMPTS"] = 3
    app_module.app.config["LOGIN_WINDOW_SECONDS"] = 300
    app_module.app.config["LOGIN_LOCKOUT_SECONDS"] = 300
    clock = {"now": 1000.0}
    app_module.login_rate_limiter._time = lambda: clock["now"]
    app_module.login_rate_limiter.reset()
    try:
        yield app_client, app_module, clock
    finally:
        import time as _time

        app_module.login_rate_limiter._time = _time.monotonic
        app_module.login_rate_limiter.reset()


def test_normal_login_succeeds(make_business, make_admin, rate_limited_app):
    client, _, _ = rate_limited_app
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)
    assert login(client, email, password).status_code == 302


def test_repeated_failures_trigger_temporary_block(make_business, make_admin, rate_limited_app):
    client, _, _ = rate_limited_app
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)

    for _ in range(3):
        assert login(client, email, "wrong").status_code == 401

    # Now blocked — even the CORRECT password is refused with 429.
    blocked = login(client, email, password)
    assert blocked.status_code == 429


def test_login_allowed_again_after_lockout_period(make_business, make_admin, rate_limited_app):
    client, app_module, clock = rate_limited_app
    business_id = make_business(name="Business A")
    email, password = make_admin(business_id)

    for _ in range(3):
        login(client, email, "wrong")
    assert login(client, email, password).status_code == 429

    # Advance the clock beyond the lockout window.
    clock["now"] += 301
    assert login(client, email, password).status_code == 302


def test_block_does_not_reveal_account_existence(make_business, make_admin, rate_limited_app):
    client, _, _ = rate_limited_app
    business_id = make_business(name="Business A")
    make_admin(business_id, email="real@example.com")

    # Failures against a non-existent account still produce the generic 401.
    for _ in range(3):
        resp = login(client, "ghost@example.com", "wrong")
        assert resp.status_code == 401
        assert b"Invalid email or password" in resp.data
