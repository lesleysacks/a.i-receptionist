# Apex M1.1 — migrate `GET /health` to Django

M1.1 moves **only** the liveness endpoint from Flask to Django. `/ready` and every other Flask route stay on Flask. No schema changes. No production deploy.

## Previous Flask implementation

- Route: `GET /health` on `ops_bp` in `routes/ops.py` (`ops.health`)
- Body: Flask `jsonify({"status": "ok"})` → bytes `{"status":"ok"}\n`
- Status: `200`
- Content-Type: `application/json`
- Content-Length: `16`
- Auth / tenant / CSRF / DB / Redis: none
- `HEAD /health`: `200`, empty body, `application/json`
- `POST /health`: `405`
- `GET /health/` and `GET /health/something`: `404`
- WSGI: `FLASK_PREFIXES` included `"/health"` (`apex/http_dispatch.py`)

## New Django implementation

- View: `apps.ops.views.health` (`@require_http_methods(["GET", "HEAD"])`)
- URL: `apps/ops/urls.py` → `path("health", ...)` included from `apex/urls.py`
- Body: the same compact JSON plus newline (`json.dumps(..., separators=(",", ":")) + "\n"`)
- No database, Redis, tenant, or environment values in the response
- Flask `ops.health` is **removed** so Flask no longer serves `/health` (avoids dual ownership). `routes.ops.ready` is unchanged.

## Dispatcher ownership change

`"/health"` was removed from `FLASK_PREFIXES`. Exact `/` and `/ready`, `/whatsapp`, `/leads`, `/admin`, `/dashboard`, `/login`, `/logout` remain Flask. `/accounts` and `/platform` remain Django. `/health`, `/health/`, and `/health/something` now go to Django; only exact `/health` returns the liveness JSON.

Rollback: restore `"/health"` on `FLASK_PREFIXES` and the Flask `ops.health` view; drop or leave unused the Django url.

## Preserved response contract

| Request | Result |
| --- | --- |
| `GET /health` | `200`, `Content-Type: application/json`, body `{"status":"ok"}\n` |
| `HEAD /health` | `200`, `Content-Type: application/json`, empty body |
| `GET /health?foo=bar` | Same JSON as GET |
| `POST` / `PUT` / `PATCH` / `DELETE` | `405`, not `{"status":"ok"}` |
| `GET /health/` | `404` |
| `GET /health/something` | `404` |

## Regression tests

- `tests/test_ops.py` — Django `Client` parity, no Django SQL, no Flask engine use, no auth, methods, slash, nested path; Flask client `404` on `/health`; `/ready` still Flask.
- `tests/test_wsgi_dispatch.py` — `/health` Django-only; `/ready` `/whatsapp` `/leads` `/admin` `/dashboard` Flask; live `wsgi.app` returns the JSON contract; method/query/headers/body forwarding.

## Remaining Flask routes

`/`, `/whatsapp`, `/leads`, `/login`, `/logout`, `/dashboard/*`, `/admin/*`, `/ready`.

## Known limitations

- Django `ALLOWED_HOSTS` now applies to `/health` (Flask did not). Probes must send an allowed `Host` (compose default `localhost,127.0.0.1`). Do not set `*`.
- Flask `OPTIONS /health` was `200`; Django returns `405`. Probes use GET/HEAD. CORS was not added.
- Flask JSON access logs (`app._log_request`) no longer include `/health`.
- `GET /ready` is still Flask.

## Rollback procedure

1. Put `"/health"` back in `FLASK_PREFIXES`.
2. Restore `@ops_bp.get("/health")` in `routes/ops.py`.
3. Optionally remove `apps.ops` urls from `apex/urls.py`.
4. No database commands.
