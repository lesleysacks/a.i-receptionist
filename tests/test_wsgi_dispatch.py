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
        "/health",
        "/health/",
        "/ready",
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

    assert [call["PATH_INFO"] for call in flask_app.calls] == ["/whatsapp"]
    assert [call["PATH_INFO"] for call in django_app.calls] == ["/accounts/login/"]
    assert django_app.calls[0]["REQUEST_METHOD"] == "GET"
    assert flask_app.calls[0]["REQUEST_METHOD"] == "POST"
