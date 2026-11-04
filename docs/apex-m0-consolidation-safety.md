# Apex M0 — consolidation safety (C1 and C2)

M0 implements the two high-priority findings from
`docs/apex-flask-django-consolidation-audit.md`. It does **not** port Flask
routes, change receptionist behaviour, or deploy to production.

## C1 — Production host configuration

### Root cause

Django `ALLOWED_HOSTS` is assigned at **import time** in `apex/settings.py`:

```text
ALLOWED_HOSTS = allowed_hosts_for_env(APP_ENV, os.getenv("DJANGO_ALLOWED_HOSTS"))
```

When `APP_ENV=production`, `allowed_hosts_for_env` refuses an empty list and
the wildcard `*`. Docker Compose previously set `APP_ENV=production` without
`DJANGO_ALLOWED_HOSTS`.

That import always happens on the documented boot paths:

1. `docker-entrypoint.sh` runs `python manage.py migrate`
2. Gunicorn loads `wsgi:app`
3. `wsgi.py` imports `app.py`
4. `app.py` calls `setup_django()` (`apex/setup_django.py`) **before** Flask blueprints that import Django models
5. `django.setup()` imports `apex.settings`

M0 also moved `load_dotenv()` / `setup_django()` above the blueprint imports in
`app.py`. Previously they ran after `from routes.admin import admin_bp`, so a
fresh `import wsgi` raised `AppRegistryNotReady` even when hosts were valid.
Tests hid this because `tests/conftest.py` calls `setup_django()` first.

The failure is therefore a **process boot `InvalidDjangoAllowedHosts`**
(`RuntimeError` subclass), not a per-request `DisallowedHost`. Flask routes
never consult Django `ALLOWED_HOSTS`; they still cannot start because Flask
initialises Django during import.

### Configuration validation

`allowed_hosts_for_env` / `parse_allowed_hosts` in `apex/settings.py`:

| Environment | Missing / empty value | Wildcard `*` (alone or mixed) | URLs / paths / internal spaces |
| --- | --- | --- | --- |
| `production` | Raises `InvalidDjangoAllowedHosts` with an actionable message | Rejected | Rejected |
| `development` | Defaults to `localhost`, `127.0.0.1` | Allowed (unchanged local behaviour) | Passed through |
| `testing` | Adds `testserver`, `localhost`, `127.0.0.1` | Passed through | Passed through |

Production still never silently accepts `*`. Leading-dot Django suffix hosts
(`.example.com`) remain allowed because they name a domain, not “any host”.

The error tells operators to set
`DJANGO_ALLOWED_HOSTS=apex.example.com,www.apex.example.com`.

Validation stays a pure function plus the existing module-level assignment.
No extra I/O was added at import.

### Compose vs real production

`docker-compose.yml` now sets
`DJANGO_ALLOWED_HOSTS=${DJANGO_ALLOWED_HOSTS:-localhost,127.0.0.1}` on `app`
and `worker` so local `docker compose up` can import Django. That default is
**compose-only**.

The production image (`Dockerfile`) still does **not** default hosts. An
orchestrator that sets `APP_ENV=production` without `DJANGO_ALLOWED_HOSTS`
still fails closed at boot.

## C2 — WSGI dispatcher regression tests

### Dispatch rules (unchanged ownership)

`apex/http_dispatch.py` holds the prefix rules. `wsgi.app` forwards to Flask
or Django without rewriting `PATH_INFO`, `QUERY_STRING`, `REQUEST_METHOD`,
`wsgi.input`, or headers.

Flask owns:

- exact `/`
- `/whatsapp`, `/leads`, `/admin`, `/dashboard`, `/login`, `/logout`,
  `/health`, `/ready`
- those prefixes plus a nested path (`/dashboard/services`, `/whatsapp/`)

Django owns everything else, including `/accounts/`, `/platform/`,
`/static/`, and unknown paths.

A similar name does **not** match: `/whatsapplication`, `/healthcheck`,
`/administrator` go to Django. Matching is case-sensitive (`/Whatsapp` is
Django). Query strings are not used for routing.

### Tests added

- `tests/test_allowed_hosts.py` — valid / missing / wildcard / malformed
  production hosts; development and testing defaults; subprocess import of
  `apex.settings` and `wsgi` under valid and invalid production config.
- `tests/test_wsgi_dispatch.py` — every current prefix, nested routes,
  trailing slashes, query strings, method and body preservation, Twilio
  `X-Twilio-Signature` header forwarding, lookalike prefixes, unknown
  routes, and the real `wsgi.app` callable with recording backends.

Route ownership was not changed to make tests pass.

## Remaining risks

- Empty WSGI `PATH_INFO` (`""`) is not `/`. The dispatcher sends it to
  Django. Gunicorn normally sets `/` for the site root; this is documented,
  not changed.
- Flask and Django sessions remain separate (audit C3–C6). Out of M0 scope.
- Compose `SECRET_KEY=change-me-in-production` and
  `SESSION_COOKIE_SECURE=false` remain local-compose assumptions.
- Real production still requires the operator to set public
  `DJANGO_ALLOWED_HOSTS` (no `*`).
- No `collectstatic` in the image (audit C7).

## Deployment configuration requirements

1. `APP_ENV=production`
2. `SECRET_KEY` (required)
3. `DJANGO_ALLOWED_HOSTS` — comma-separated public hostnames, no `*`
4. `DATABASE_URL` (PostgreSQL), Twilio variables, recommended `WEBHOOK_BASE_URL`
5. Serve `gunicorn -c gunicorn.conf.py wsgi:app`

Local compose may rely on the localhost host default. Do not copy that
default into a public deployment.
