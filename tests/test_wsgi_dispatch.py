"""C2: WSGI prefix dispatcher sends each path to exactly one framework."""

from __future__ import annotations

from io import BytesIO

from apex.http_dispatch import FLASK_PREFIXES, dispatch_wsgi, flask_owns_path


class RecordingApp:
    """Minimal WSGI app that records the environ it received."""

    def __init__(self, name: str):
        self.name = name
        self.calls: list[dict] = []

    def __call__(self, environ, start_response):
        self.calls.append(dict(environ))
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [self.name.encode("ascii")]


def _environ(
    path: str,
    *,
    method: str = "GET",
    query: str = "",
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> dict:
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "SCRIPT_NAME": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "5000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(body),
        "wsgi.errors": BytesIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "CONTENT_LENGTH": str(len(body)),
    }
    for header, value in (headers or {}).items():
        key = header.upper().replace("-", "_")
        if key not in {"CONTENT_TYPE", "CONTENT_LENGTH"}:
            key = "HTTP_" + key
        environ[key] = value
    return environ


def _dispatch(path: str, **kwargs) -> tuple[RecordingApp, RecordingApp, list[bytes]]:
    flask_app = RecordingApp("flask")
    django_app = RecordingApp("django")
    collected: list[tuple] = []

    def start_response(status, headers, exc_info=None):
        collected.append((status, headers))
        return None

    body = list(dispatch_wsgi(_environ(path, **kwargs), start_response, flask_app, django_app))
    return flask_app, django_app, body


def test_dispatcher_prefixes_match_wsgi_module():
    import wsgi

    assert tuple(wsgi.FLASK_PREFIXES) == FLASK_PREFIXES
    assert wsgi.flask_owns_path is flask_owns_path


def test_whatsapp_and_nested_webhook_paths_go_to_flask_only():
    for path in ("/whatsapp", "/whatsapp/", "/whatsapp/retry"):
        flask_app, django_app, body = _dispatch(path, method="POST")
        assert body == [b"flask"]
        assert len(flask_app.calls) == 1
        assert django_app.calls == []
        assert flask_app.calls[0]["PATH_INFO"] == path
        assert flask_app.calls[0]["REQUEST_METHOD"] == "POST"


def test_leads_dashboard_admin_and_ops_paths_go_to_flask_only():
    flask_paths = (
        "/",
        "/leads",
        "/leads/",
        "/dashboard",
        "/dashboard/services",
        "/dashboard/faqs/new",
        "/admin",
        "/admin/businesses",
        "/login",
        "/login/",
        "/logout",
        "/ready",
        "/ready/",
    )
    for path in flask_paths:
        flask_app, django_app, body = _dispatch(path)
        assert django_app.calls == [], path
        assert flask_app.calls[0]["PATH_INFO"] == path
        assert body == [b"flask"]


def test_accounts_and_platform_paths_go_to_django_only():
    django_paths = (
        "/accounts",
        "/accounts/",
        "/accounts/login/",
        "/accounts/logout/",
        "/platform",
        "/platform/",
        "/platform/tenants/",
        "/platform/django-admin/",
        "/platform/django-admin/login/",
        "/static/admin/css/base.css",
        "/health",
        "/health/",
        "/health/something",
    )
    for path in django_paths:
        flask_app, django_app, body = _dispatch(path)
        assert flask_app.calls == [], path
        assert django_app.calls[0]["PATH_INFO"] == path
        assert body == [b"django"]


def test_unknown_routes_go_to_django():
    flask_app, django_app, body = _dispatch("/no-such-route")
    assert flask_app.calls == []
    assert len(django_app.calls) == 1
    assert body == [b"django"]


def test_similar_but_non_matching_prefixes_go_to_django():
    lookalikes = (
        "/whatsapplication",
        "/whatsapp-backup",
        "/leads-export",
        "/administrator",
        "/dashboarding",
        "/login-form",
        "/logout-everywhere",
        "/healthcheck",
        "/readyz",
        "/Whatsapp",
        "/Accounts",
    )
    for path in lookalikes:
        flask_app, django_app, _body = _dispatch(path)
        assert flask_app.calls == [], path
        assert django_app.calls[0]["PATH_INFO"] == path
        assert flask_owns_path(path) is False


def test_trailing_slash_does_not_change_framework_owner():
    pairs = (
        ("/whatsapp", "/whatsapp/"),
        ("/leads", "/leads/"),
        ("/dashboard", "/dashboard/"),
        ("/admin", "/admin/"),
        ("/ready", "/ready/"),
        ("/health", "/health/"),
        ("/accounts", "/accounts/"),
        ("/platform", "/platform/"),
    )
    for without, with_slash in pairs:
        assert flask_owns_path(without) == flask_owns_path(with_slash)


def test_query_string_does_not_change_routing_and_is_preserved():
    flask_app, django_app, _body = _dispatch(
        "/whatsapp",
        method="POST",
        query="MessageSid=SM123&To=whatsapp%3A%2B27111111111",
    )
    assert django_app.calls == []
    assert flask_app.calls[0]["QUERY_STRING"] == "MessageSid=SM123&To=whatsapp%3A%2B27111111111"
    assert flask_app.calls[0]["PATH_INFO"] == "/whatsapp"

    flask_app, django_app, _body = _dispatch("/accounts/login/", query="next=/whatsapp")
    assert flask_app.calls == []
    assert django_app.calls[0]["QUERY_STRING"] == "next=/whatsapp"
    assert django_app.calls[0]["PATH_INFO"] == "/accounts/login/"


def test_http_method_is_preserved_for_both_frameworks():
    flask_app, django_app, _body = _dispatch("/whatsapp", method="POST")
    assert flask_app.calls[0]["REQUEST_METHOD"] == "POST"
    assert django_app.calls == []

    flask_app, django_app, _body = _dispatch("/accounts/logout/", method="POST")
    assert django_app.calls[0]["REQUEST_METHOD"] == "POST"
    assert flask_app.calls == []


def test_request_body_is_preserved_for_flask_webhook():
    payload = b"From=whatsapp%3A%2B27830000000&To=whatsapp%3A%2B27111111111&Body=hello"
    flask_app, django_app, _body = _dispatch(
        "/whatsapp",
        method="POST",
        body=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert django_app.calls == []
    received = flask_app.calls[0]
    assert received["wsgi.input"].read() == payload
    assert received["CONTENT_TYPE"] == "application/x-www-form-urlencoded"
    assert received["CONTENT_LENGTH"] == str(len(payload))


def test_twilio_signature_headers_are_preserved_on_whatsapp_dispatch():
    flask_app, django_app, _body = _dispatch(
        "/whatsapp",
        method="POST",
        body=b"Body=hi",
        headers={
            "X-Twilio-Signature": "signature-from-twilio",
            "X-Twilio-Account-Sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "Host": "hooks.example",
        },
    )
    assert django_app.calls == []
    received = flask_app.calls[0]
    assert received["HTTP_X_TWILIO_SIGNATURE"] == "signature-from-twilio"
    assert received["HTTP_X_TWILIO_ACCOUNT_SID"] == "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    assert received["HTTP_HOST"] == "hooks.example"


def test_empty_path_info_does_not_match_flask_root():
    """WSGI PATH_INFO '' is not '/'; the current dispatcher sends it to Django."""
    assert flask_owns_path("") is False
    flask_app, django_app, _body = _dispatch("")
    assert flask_app.calls == []
    assert len(django_app.calls) == 1


def test_wsgi_app_callable_uses_the_same_prefix_rules(monkeypatch):
    import wsgi

    flask_app = RecordingApp("flask")
    django_app = RecordingApp("django")
    monkeypatch.setattr(wsgi, "flask_app", flask_app)
    monkeypatch.setattr(wsgi, "django_app", django_app)

    def start_response(status, headers, exc_info=None):
        return None

    list(wsgi.app(_environ("/whatsapp", method="POST"), start_response))
    list(wsgi.app(_environ("/accounts/login/"), start_response))
    list(wsgi.app(_environ("/health"), start_response))
    list(wsgi.app(_environ("/ready"), start_response))

    assert [call["PATH_INFO"] for call in flask_app.calls] == ["/whatsapp", "/ready"]
    assert [call["PATH_INFO"] for call in django_app.calls] == ["/accounts/login/", "/health"]
    assert django_app.calls[0]["REQUEST_METHOD"] == "GET"
    assert flask_app.calls[0]["REQUEST_METHOD"] == "POST"
    assert flask_app.calls[1]["REQUEST_METHOD"] == "GET"
    assert django_app.calls[1]["REQUEST_METHOD"] == "GET"


def test_health_is_django_and_other_receptionist_paths_stay_flask():
    django_only = ("/health", "/health/", "/health/something", "/accounts", "/platform")
    flask_only = ("/ready", "/whatsapp", "/leads", "/admin", "/dashboard", "/login", "/logout", "/")
    for path in django_only:
        flask_app, django_app, body = _dispatch(path)
        assert flask_app.calls == [], path
        assert body == [b"django"]
        assert flask_owns_path(path) is False
    for path in flask_only:
        flask_app, django_app, body = _dispatch(path)
        assert django_app.calls == [], path
        assert body == [b"flask"]
        assert flask_owns_path(path) is True


def test_health_dispatch_preserves_method_query_headers_and_body():
    flask_app, django_app, _body = _dispatch(
        "/health",
        method="GET",
        query="foo=bar",
        body=b"",
        headers={"X-Request-Id": "probe-1", "Host": "localhost"},
    )
    assert flask_app.calls == []
    received = django_app.calls[0]
    assert received["REQUEST_METHOD"] == "GET"
    assert received["QUERY_STRING"] == "foo=bar"
    assert received["PATH_INFO"] == "/health"
    assert received["HTTP_X_REQUEST_ID"] == "probe-1"
    assert received["HTTP_HOST"] == "localhost"
    assert received["wsgi.input"].read() == b""


def test_wsgi_live_health_returns_ok_json():
    import json
    import wsgi

    recorded: dict = {}

    def start_response(status, headers, exc_info=None):
        recorded["status"] = status
        recorded["headers"] = {key: value for key, value in headers}

    body = b"".join(
        wsgi.app(_environ("/health", headers={"Host": "testserver"}), start_response)
    )
    assert recorded["status"].startswith("200")
    assert json.loads(body) == {"status": "ok"}
    assert recorded["headers"]["Content-Type"] == "application/json"
    assert recorded["headers"]["Content-Length"] == "16"
    assert body == b'{"status":"ok"}\n'


def test_wsgi_live_health_head_has_empty_body_and_content_length_16():
    import wsgi

    recorded: dict = {}

    def start_response(status, headers, exc_info=None):
        recorded["status"] = status
        recorded["headers"] = {key: value for key, value in headers}

    body = b"".join(
        wsgi.app(
            _environ("/health", method="HEAD", headers={"Host": "testserver"}),
            start_response,
        )
    )
    assert recorded["status"].startswith("200")
    assert body == b""
    assert recorded["headers"]["Content-Type"] == "application/json"
    assert recorded["headers"]["Content-Length"] == "16"


def test_wsgi_live_health_unsafe_methods_are_405_not_403():
    import json
    import wsgi

    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        recorded: dict = {}

        def start_response(status, headers, exc_info=None, recorded=recorded):
            recorded["status"] = status
            recorded["headers"] = {key: value for key, value in headers}

        body = b"".join(
            wsgi.app(
                _environ("/health", method=method, headers={"Host": "testserver"}),
                start_response,
            )
        )
        assert recorded["status"].startswith("405"), method
        assert not recorded["status"].startswith("403"), method
        try:
            payload = json.loads(body.decode() or "{}")
        except json.JSONDecodeError:
            payload = None
        assert payload != {"status": "ok"}, method


def test_ready_dispatch_preserves_method_query_headers_and_body():
    flask_app, django_app, _body = _dispatch(
        "/ready",
        method="GET",
        query="foo=bar",
        body=b"",
        headers={"X-Request-Id": "probe-ready", "Host": "not-allowed.example"},
    )
    assert django_app.calls == []
    received = flask_app.calls[0]
    assert received["REQUEST_METHOD"] == "GET"
    assert received["QUERY_STRING"] == "foo=bar"
    assert received["PATH_INFO"] == "/ready"
    assert received["HTTP_X_REQUEST_ID"] == "probe-ready"
    assert received["HTTP_HOST"] == "not-allowed.example"
    assert received["wsgi.input"].read() == b""


def test_wsgi_live_ready_returns_ready_json():
    import json
    import wsgi

    recorded: dict = {}

    def start_response(status, headers, exc_info=None):
        recorded["status"] = status
        recorded["headers"] = {key: value for key, value in headers}

    body = b"".join(
        wsgi.app(_environ("/ready", headers={"Host": "not-allowed.example"}), start_response)
    )
    assert recorded["status"].startswith("200")
    assert json.loads(body) == {"status": "ready", "checks": {"database": "ok"}}
    assert recorded["headers"]["Content-Type"] == "application/json"
    assert recorded["headers"]["Content-Length"] == "46"
    assert body == b'{"checks":{"database":"ok"},"status":"ready"}\n'


def test_wsgi_live_ready_head_has_empty_body_and_get_content_length():
    import wsgi

    recorded: dict = {}

    def start_response(status, headers, exc_info=None):
        recorded["status"] = status
        recorded["headers"] = {key: value for key, value in headers}

    body = b"".join(
        wsgi.app(
            _environ("/ready", method="HEAD", headers={"Host": "testserver"}),
            start_response,
        )
    )
    assert recorded["status"].startswith("200")
    assert body == b""
    assert recorded["headers"]["Content-Type"] == "application/json"
    assert recorded["headers"]["Content-Length"] == "46"


def test_wsgi_live_ready_options_is_200_and_post_is_405():
    import wsgi

    for method, prefix in (("OPTIONS", "200"), ("POST", "405")):
        recorded: dict = {}

        def start_response(status, headers, exc_info=None, recorded=recorded):
            recorded["status"] = status
            recorded["headers"] = {key: value for key, value in headers}

        body = b"".join(
            wsgi.app(
                _environ("/ready", method=method, headers={"Host": "testserver"}),
                start_response,
            )
        )
        assert recorded["status"].startswith(prefix), method
        if method == "POST":
            assert not recorded["status"].startswith("403")
            assert b'"status":"ready"' not in body


def test_wsgi_live_ownership_ready_health_whatsapp_leads_accounts(monkeypatch):
    """Production dispatcher still splits ops and receptionist paths as in M1.1."""
    import wsgi

    flask_app = RecordingApp("flask")
    django_app = RecordingApp("django")
    monkeypatch.setattr(wsgi, "flask_app", flask_app)
    monkeypatch.setattr(wsgi, "django_app", django_app)

    def start_response(status, headers, exc_info=None):
        return None

    for path, method in (
        ("/ready", "GET"),
        ("/health", "GET"),
        ("/whatsapp", "POST"),
        ("/leads", "GET"),
        ("/accounts", "GET"),
    ):
        list(wsgi.app(_environ(path, method=method), start_response))

    assert [call["PATH_INFO"] for call in flask_app.calls] == ["/ready", "/whatsapp", "/leads"]
    assert [call["PATH_INFO"] for call in django_app.calls] == ["/health", "/accounts"]
    assert [call["REQUEST_METHOD"] for call in flask_app.calls] == ["GET", "POST", "GET"]
    assert [call["REQUEST_METHOD"] for call in django_app.calls] == ["GET", "GET"]
