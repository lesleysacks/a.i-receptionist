# Apex M1 — first Django route selection audit

**Product:** Apex by InterSacks Digital  
**Audit type:** Read-only first-route selection for Flask → Django HTTP consolidation  
**Audit date:** 4 November 2026 (Africa/Johannesburg)  
**Inspected ref:** `feature/apex-m0-consolidation-safety` at `b8f2fa0415725ff17051035920ad79fd7eb6cb0a`

This audit did not modify application code, tests, settings, dependencies, migrations, or route ownership except for creating this report. No paid APIs were called. No secrets are reproduced.

---

## 1. Executive summary

The dual stack is unchanged after M0: `wsgi.app` (`wsgi.py`) still sends `FLASK_PREFIXES` plus exact `/` to Flask (`app.app`) and everything else to Django (`apex.wsgi.application`). Prefix rules live in `apex/http_dispatch.py` (`flask_owns_path`, `dispatch_wsgi`).

**Preferred first migration:** `GET /health` (`routes.ops.health`).

It is the only Flask route that is simultaneously unauthenticated, tenant-free, CSRF-irrelevant, free of customer/business writes, independent of the database, covered by an existing HTTP test, and removable from the dispatcher as a single prefix. The consolidation plan already named ops as M1; this audit narrows that to **health first**, not health and ready together.

**Do not migrate `/whatsapp`, login/logout, dashboard/admin mutations, or `/leads` first.** `GET /ready` is the correct second ops route, not the first: it touches SQLAlchemy `engine` and optional Redis and can flap load-balancer probes.

**Do not start implementation until this audit is accepted.**

---

## 2. Verified baseline

| Item | Verified value |
| --- | --- |
| Remote | `https://github.com/lesleysacks/a.i-receptionist` |
| Branch | `feature/apex-m0-consolidation-safety` |
| HEAD | `b8f2fa0415725ff17051035920ad79fd7eb6cb0a` |
| Parent | Audit `621560f` on Phase 2.2 `01fb9ce` |
| Working tree at inspection | Clean |
| Newer commits on this branch | None |
| Docs already present | `docs/apex-flask-django-consolidation-audit.md`, `docs/apex-m0-consolidation-safety.md` |
| `docs/apex-m1-route-selection-audit.md` | Absent before this report |

**Checks run during this audit (non-destructive)**

- `python -m pytest --disable-warnings`: process exit 0 (consistent with **161 passed, 2 skipped**).
- `APP_ENV=testing python manage.py check`: no issues.
- Flask `url_map` dump via test client (no source edits): confirms registered rules, methods, trailing-slash 404s, and JSON bodies recorded in section 3.

Skipped tests (unchanged): `tests/test_openai_integration.py`; `tests/test_rate_limit_redis.py`.

---

## 3. Complete Flask route inventory

Verified from `app.url_map.iter_rules()`, `app.py`, `routes/ops.py`, `routes/auth.py`, `routes/dashboard.py`, `routes/admin.py`. Flask `strict_slashes` is **True**. Default Flask `/static/<path:filename>` exists on the Flask app but is **not** reachable through `wsgi.app` because `/static` is not a Flask prefix (`tests/test_wsgi_dispatch.py` sends `/static/admin/css/base.css` to Django).

CSRF: `CSRFProtect(app)` in `app.py`. Exempt: `ops_bp`, `admin_bp`, `app.whatsapp`. Browser POST forms use Flask-WTF tokens.

Auth helpers: `routes.auth.login_required`, `write_required`, `current_admin` (Flask cookie `session`; keys `user_id` / `admin_id`; `AuthService.get_admin` → `apps.tenants.services.principal_for_user`).

### 3.1 `GET /` — `app.home`

| Field | Evidence |
| --- | --- |
| Methods | GET, HEAD, OPTIONS (`@app.route("/")`) |
| Auth / CSRF / tenant | None |
| Validation | None |
| Response | `200` `text/html; charset=utf-8` body `WhatsApp Receptionist Bot Running` (not JSON) |
| DB / services / side effects | None besides `app._log_request` |
| Tests | **None** for HTTP body/status |
| Dispatcher | Exact path in `FLASK_EXACT_PATHS` |

POST `/` → Flask `405`.

### 3.2 `POST /whatsapp` — `app.whatsapp`

| Field | Evidence |
| --- | --- |
| Methods | POST, OPTIONS (`@csrf.exempt`) |
| Auth | Twilio `X-Twilio-Signature` via `app.is_valid_twilio_request` → `apex_receptionist.adapters.twilio_webhook.is_valid_twilio_signature` |
| Tenant | `BusinessService.get_by_whatsapp_number(To)` only; no default tenant |
| Validation | Signature; non-empty `Body`/`From`; `MAX_CONTENT_LENGTH` |
| DB | SQLAlchemy `ProcessedWebhook`; `ConversationService.handle` (FSM, bookings, intelligence persist) |
| Side effects | Booking create, owner notify enqueue, `IntelligenceOutcome` insert |
| Response | TwiML; unsigned `403`; empty body `400`; duplicate MessageSid empty TwiML `200` |
| Tests | `tests/test_webhook.py`, `test_routing.py`, `test_phase1_foundation.py`, `test_intelligence_foundation.py`, `test_csrf.py` (`test_webhook_still_works_with_csrf_enabled`) |

**Excluded as first candidate** (customer-facing, FSM, writes).

### 3.3 `GET /leads` — `app.view_leads`

| Field | Evidence |
| --- | --- |
| Methods | GET, HEAD, OPTIONS |
| Auth | `login_required`: Flask session; `can_read`; `business_id` required or `403` |
| Tenant | `admin.business_id` only |
| DB | `BusinessService.get_business`, `BookingService.list_bookings` |
| Response | HTML `templates/leads.html` with customer **name and phone** |
| Tests | `tests/test_auth.py`, `test_tenant_leads.py`, `test_booking_flow.py` |

Unauthenticated → `302` `/login`. **Not first:** PII, Flask session, SQLAlchemy bookings.

### 3.4 Auth — `routes.auth`

| Route | Function | Methods | Auth | CSRF | Notes | Tests |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /login` | `login_form` | GET, HEAD, OPTIONS | Public; redirect if scoped session | Token in `templates/login.html` | Redirect `dashboard.index` | `test_auth.py`, `test_csrf.py` |
| `POST /login` | `login` | POST, OPTIONS | Public; `build_login_rate_limiter` | Flask-WTF required | `AuthService.authenticate`; unscoped platform admin `403`; sets Flask session; `record_audit` | `test_csrf.py`, `test_login_rate_limit.py`, `test_phase1_foundation.py` |
| `GET` and `POST /logout` | `logout` | GET, HEAD, POST, OPTIONS | Optional | **GET not CSRF-protected** | `session.clear()`; audit | `test_auth.py` uses GET |

**Excluded as first candidate.** Dual-login architecture; C3 GET logout.

### 3.5 Dashboard — `routes.dashboard` (`url_prefix="/dashboard"`)

All require `login_required`. Mutations also `write_required` (POST without `can_write` → `403`). Tenant is always `admin.business_id` via `BusinessService`. CSRF on POST via Flask-WTF (forms). Tests: `tests/test_dashboard.py` (mutations + IDOR).

| URL | Function | Methods | Writes? |
| --- | --- | --- | --- |
| `/dashboard/` | `index` | GET, HEAD, OPTIONS | No (counts only) |
| `/dashboard/services` | `services` | GET, HEAD, OPTIONS | No |
| `/dashboard/services/new` | `service_new` | GET, POST | POST `add_service` |
| `/dashboard/services/<id>/edit` | `service_edit` | GET, POST | POST `update_service` |
| `/dashboard/services/<id>/delete` | `service_delete` | POST | `delete_service` |
| `/dashboard/faqs` | `faqs` | GET, HEAD, OPTIONS | No |
| `/dashboard/faqs/new` | `faq_new` | GET, POST | POST `add_faq` |
| `/dashboard/faqs/<id>/edit` | `faq_edit` | GET, POST | POST `update_faq` |
| `/dashboard/faqs/<id>/delete` | `faq_delete` | POST | `delete_faq` |
| `/dashboard/business` | `business` | GET, POST | POST `update_business` |

GET pages still need Flask session + Jinja `url_for`. **Not first.** Mutations **excluded**.

### 3.6 JSON admin — `routes.admin` (`url_prefix="/admin"`)

Blueprint CSRF-exempt (`app.py` `csrf.exempt(admin_bp)`). `admin_bp.before_request` `_authenticate_and_scope`: Flask session **or** `hmac.compare_digest` of `X-Admin-Key` vs `ADMIN_API_KEY`. Tenant from membership or required `X-Business-Id` for platform admin / API key; **never from JSON body**. Read-only membership blocked on non-GET/HEAD.

| URL | Function | Methods | Writes? |
| --- | --- | --- | --- |
| `/admin/business` | `get_business` | GET, HEAD, OPTIONS | No |
| `/admin/business` | `update_business` | PUT | Yes |
| `/admin/services` | `get_services` | GET, HEAD, OPTIONS | No |
| `/admin/services` | `add_service` | POST | Yes `201` |
| `/admin/services/<id>` | `update_service` | PUT | Yes |
| `/admin/services/<id>` | `delete_service` | DELETE | Yes `204` |
| `/admin/faq` | `get_faq` | GET, HEAD, OPTIONS | No |
| `/admin/faq` | `add_faq` | POST | Yes `201` |
| `/admin/faq/<id>` | `update_faq` | PUT | Yes |
| `/admin/faq/<id>` | `delete_faq` | DELETE | Yes `204` |

Tests: `tests/test_admin_api.py`, `test_phase1_foundation.py`. **GET admin is still a poor first route** (dual auth, CSRF-exempt JSON, tenant scoping, `ADMIN_API_KEY`). Mutations **excluded**.

### 3.7 Ops — `routes.ops`

| URL | Function | Methods | Auth | CSRF | Tenant | DB | Response | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/health` | `health` | GET, HEAD, OPTIONS | None | Exempt | None | **None** (comment: does not touch DB) | `200` `application/json` `{"status":"ok"}\n` | `test_health_is_ok_and_independent_of_database` |
| `/ready` | `ready` | GET, HEAD, OPTIONS | None | Exempt | None | `engine.connect()` `SELECT 1`; Redis only if `services.jobs.redis_url()` | `200` `{"status":"ready","checks":{...}}` or `503` `not_ready`; exception text not returned | `test_ready_reports_database_ok`, `test_ready_fails_when_database_unavailable` |

Probed behaviour (Flask test client, this audit):

- `POST /health` and `POST /ready` → `405` HTML.
- `GET /health/` and `GET /ready/` → **`404`** (no slash redirect).
- `HEAD /health` → `200`, empty body, `Content-Type: application/json`.
- `/ready` without Redis includes only `checks.database`.

### 3.8 Flask-only extras (not production-dispatcher routes)

- `GET /static/<path:filename>` — Flask default; **Django receives `/static/`** under `wsgi.app`.
- `app._unexpected_error` — generic `500` without exception text.
- `app._log_request` — JSON access log for every Flask request.

---

## 4. Django route inventory

From `apex/urls.py`, `apps/accounts/urls.py`, `apps/tenants/urls.py`, `django.contrib.admin`.

| URL | View | Methods | Auth | CSRF | Tenant | Response | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/accounts/login/` | `apps.accounts.views.login_view` | GET, POST (`require_http_methods`) | Public | `CsrfViewMiddleware` | n/a | HTML / redirect `accounts-home` | `test_django_login_requires_csrf` |
| `/accounts/logout/` | `logout_view` | **POST only** | Optional | CSRF | n/a | Redirect login | `test_django_logout_is_post_only_and_revokes_session` |
| `/accounts/` | `home_view` | GET | `@login_required` Django `sessionid` | n/a GET | User's `Membership` | HTML | login success only |
| `/platform/tenants/` | `apps.tenants.views.tenant_list` | GET | login + `user_is_platform_admin` | n/a GET | All `Tenant` rows | HTML or `403` | Phase 1 tenant tests |
| `/platform/django-admin/`… | Django admin | Admin | `is_staff` | Admin CSRF | `IntelligenceOutcomeAdmin.get_queryset` → `outcomes_for_user`; User/Tenant/Membership/AuditEvent admins | HTML | queryset tests; **no live admin HTTP** |
| `/static/` | staticfiles | GET | Public | n/a | n/a | Files if collected | None |

No Django `/health`, `/ready`, `/whatsapp`, `/leads`, `/login` (Flask path), `/dashboard`, or JSON `/admin`. **No duplicate paths** with Flask for those prefixes because the dispatcher never offers them to Django today.

**Session difference:** Django `sessionid` vs Flask `session`. Logging into `/accounts/login/` does not authorize `/leads`.

**CSRF difference:** Django login/logout use Django tokens; Flask login uses `csrf_token()`; Flask JSON `/admin` is exempt.

**Host checking:** Django `ALLOWED_HOSTS` applies only after a path is dispatched to Django. Flask `/health` currently **ignores** Django hosts.

---

## 5. Security and tenant-isolation comparison

| Concern | Flask ops `/health` | Flask `/ready` | Flask `/leads` / dashboard GET | Flask JSON GET `/admin/*` | Django `/accounts/` |
| --- | --- | --- | --- | --- | --- |
| Auth | None | None | Flask session + membership | Session or `ADMIN_API_KEY` | Django session |
| Tenant | None | None | `admin.business_id` | `_authenticate_and_scope` | Membership list / platform admin |
| CSRF | GET; blueprint exempt | Same | GET | Exempt blueprint | Django CSRF on POST |
| PII | None | None | Yes (leads) | Business config | Emails in membership HTML |
| Writes | No | Read-only `SELECT 1` | No on GET | No on GET | No on GET home |
| After migration Host check | **Would start** | Would start | Would start | Would start | Already |

No Flask route trusts a customer-supplied tenant id as the sole source (`routes.admin` and `resolve_business_id_for_user` verified). Platform `X-Business-Id` is privileged.

---

## 6. Candidate scoring table

Score **1–5** where **5 is best** for a first migration. Excluded rows are scored only to show why they are last.

| Candidate | Impact | Security | Tenant | Dependencies | Tests | Parity | Rollback | Total | First-route? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`GET /health`** | **5** — probe-only; customers never call it | **5** — no auth/secrets | **5** — no tenant | **5** — `jsonify({"status":"ok"})` only | **4** — independence test exists; methods/slash/HEAD missing | **5** — tiny JSON | **5** — restore `/health` prefix | **34** | **Yes** |
| `GET /ready` | 3 — false 503/200 flaps probes | 5 | 5 | 3 — `database.engine`, optional Redis | 4 — 200 and 503 covered; Redis path untested | 4 — JSON shape + no leak | 5 | 29 | Second, not first |
| `GET /` | 4 — unused liveness string | 5 | 5 | 5 | 2 — no HTTP test | 4 — plaintext vs Django `HttpResponse` | 4 — `FLASK_EXACT_PATHS` special case | 29 | No: weaker tests, less value |
| `GET /dashboard/` or `/services` or `/faqs` | 2 — operator UI | 2 — Flask session | 2 | 2 — Jinja + `BusinessService` | 3 — mutations tested more than GET | 2 — templates/`url_for` | 3 | 16 | No |
| `GET /leads` | 2 — PII HTML | 2 | 2 | 2 — bookings | 4 | 2 | 3 | 17 | No |
| `GET /admin/business` (etc.) | 2 | 1 — dual auth, CSRF-exempt, API key | 2 | 2 | 4 | 2 | 3 | 16 | No |
| `GET/POST /login`, `/logout` | 1 — session split | 1 — CSRF/rate-limit mismatch with Django | 3 | 2 | 4 | 1 — two login UIs | 2 | 14 | Excluded |
| Dashboard/admin writes | 1 | 1 | 1 | 2 | 4 | 2 | 2 | 13 | Excluded |
| `POST /whatsapp` | 1 — all tenants’ chat | 1 — Twilio + CSRF exempt | 1 | 1 — FSM, AI, jobs | 5 | 2 | 2 | 13 | Excluded |

Coverage is **not** the reason to pick `/whatsapp` first: impact and isolation dominate.

`GET /` is not preferred merely because it is simple: it has **no tests**, uses the dispatcher exact-path set rather than a prefix, and does not exercise JSON + `FLASK_PREFIXES` removal (the pattern later routes need).

---

## 7. Preferred first route

**`GET /health`** — `routes.ops.health` (`ops_bp`, endpoint `ops.health`).

### Why it is the safest candidate

1. Read-only, no tenant, no session, no PII, no CSRF token, no business/customer writes.
2. Documented and tested independence from the database (`test_health_is_ok_and_independent_of_database` monkeypatches `routes.ops.engine` and still expects `{"status":"ok"}`).
3. One dispatcher prefix (`/health`) can move without touching `/ready`, `/whatsapp`, or `/`.
4. Matches the accepted consolidation plan’s ops phase, but **splits** it so `/ready` does not share the first blast radius.
5. Rollback is prefix restoration; no schema.

### Current request lifecycle

1. Gunicorn `wsgi:app` → `dispatch_wsgi` → `flask_owns_path("/health")` True (`FLASK_PREFIXES`).
2. Flask `before_request` timer; `ops.health` returns `jsonify({"status":"ok"})`, 200.
3. `after_request` logs method/path/status/latency (`services.logging_setup`).
4. Django middleware, `ALLOWED_HOSTS`, and CSRF are **not** applied.

### Proposed Django implementation location (not implemented)

- New app `apps/ops/` (views + urls), included from `apex/urls.py` as `path("health", ...)`.
- Use `django.http.JsonResponse({"status": "ok"})` and `django.views.decorators.http.require_GET` (GET+HEAD).
- Do **not** register a trailing-slash variant; Flask `GET /health/` is 404.
- Remove `"/health"` from `FLASK_PREFIXES` in `apex/http_dispatch.py` so Django actually receives the request. Leaving the Flask view in place as dead code is acceptable for rollback; deleting it is optional and not required for the first slice.
- Keep `"/ready"` on Flask.

Do not put this under `/platform/` or `/accounts/`; probes and `AGENTS.md` document `GET /health` at the site root.

### Services to reuse

None. Do not call `routes.ops.ready`, SQLAlchemy, or Redis. Copying `/ready` logic into `/health` would **break** the tested “DB down still 200” contract.

### Dependencies and risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Django `ALLOWED_HOSTS` starts applying (Flask does not) | Medium (availability, not authz) | Probes must send a host in `DJANGO_ALLOWED_HOSTS` (compose default `localhost,127.0.0.1`). Do not add `*` |
| `APPEND_SLASH` redirect on `/health/` | Low | Register `path("health")` without slash; assert `/health/` stays 404 like Flask |
| JSON spacing / trailing newline | Low | Assert parsed JSON `{"status":"ok"}` and `Content-Type` contains `application/json`, not raw Flask bytes |
| Flask request log disappears for this path | Informational | Acceptable; Django can log later |
| Forgetting to drop the WSGI prefix | High for “migration that does nothing” | Dispatcher tests: `/health` → Django recording app; `/ready` still Flask |
| OPTIONS parity | Low | Flask allows OPTIONS; Django function views often 405. Probes use GET/HEAD. Document; do not expand CORS |

### Expected response parity

| Request | Flask today | Django target |
| --- | --- | --- |
| `GET /health` | 200, JSON `{"status":"ok"}` | Same object |
| `HEAD /health` | 200, empty body | 200, empty body |
| `POST /health` | 405 | 405 |
| `GET /health/` | 404 | 404 |
| `GET /healthcheck` | Django (already) | Unchanged |
| `GET /ready` | Flask JSON | **Still Flask** |

### Security requirements

- Remain unauthenticated (do not add login).
- Do not return exception text, stack traces, env, or host lists.
- Do not weaken `allowed_hosts_for_env`.
- GET/HEAD only.

---

## 8. Proposed migration design

Implementation is **out of scope** for this audit. When approved, the slice should be:

1. Capture Flask parity tests **before** switching the prefix (status, JSON, HEAD, POST 405, slash 404, DB-down still 200).
2. Add Django view + url; point tests at Django `Client` **and** `wsgi.app` with recording backends / a live dispatcher test.
3. Remove `"/health"` from `FLASK_PREFIXES` only.
4. Confirm `/ready`, `/whatsapp`, `/login` still Flask; `/accounts/` still Django.
5. No migrations, no auth changes, no template port.

Suggested files (future): `apps/ops/views.py`, `apps/ops/urls.py`, `apex/urls.py`, `apex/http_dispatch.py`, `tests/test_ops.py`, `tests/test_wsgi_dispatch.py`. Possibly leave `routes/ops.py` `health` unused until M1 `/ready`.

---

## 9. Regression test plan

### Before switching ownership (add while Flask still owns `/health`)

Reuse `tests/test_ops.py::test_health_is_ok_and_independent_of_database`.

**Missing today — add as Flask characterisations, then keep after the port:**

| Case | Need |
| --- | --- |
| Method parity | GET 200, HEAD 200, POST 405, PUT 405 |
| Headers | `Content-Type` includes `application/json` |
| Body | `resp.json() == {"status": "ok"}` (not raw whitespace) |
| Trailing slash | `GET /health/` 404 |
| Query string | `GET /health?foo=bar` still 200 same body (Flask ignores QS) |
| Dispatcher | `/health` Flask (before); `/healthcheck` Django; `/ready` Flask |
| Auth | No cookie, still 200 |
| CSRF | GET with CSRF enabled still 200 (ops exempt / GET) |

### After switching ownership

| Case | Need |
| --- | --- |
| Dispatcher | `/health` **Django**; `/health/` Django 404; `/ready` **Flask**; `/whatsapp` Flask; `/accounts/login/` Django |
| Host | Valid `ALLOWED_HOSTS` 200; invalid host Django 400 (new behaviour — document, do not “fix” with `*`) |
| DB down | Monkeypatch SQLAlchemy engine; `/health` still 200; `/ready` still 503 via Flask |
| Unknown routes | Unchanged Django 404 |
| No regression | Full `python -m pytest`; existing Phase 1 / 2.1 / 2.2 tests |

Tenant isolation, booking FSM, Twilio signature, lead HTML, and admin JSON tests must stay green and **unmodified in intent**.

---

## 10. Rollback plan

1. Restore `"/health"` in `FLASK_PREFIXES` (`apex/http_dispatch.py`). Traffic returns to `routes.ops.health` immediately.
2. Revert the Django url/view commit if desired. Dead Django view is harmless if the prefix points at Flask.
3. **No database rollback.** `/health` has no tables.
4. Restore previous image tag in any environment.

Do not `alembic downgrade` or `migrate ... zero`.

---

## 11. Risks and unresolved questions

1. **Probe `Host` header** after the move (compose vs Kubernetes). Must be in `DJANGO_ALLOWED_HOSTS`. Not verifiable without a deployment; there is no production.
2. **Is `/health` the Kubernetes/compose probe today?** `AGENTS.md` and `docs/apex-local-development.md` document `curl localhost:5000/health`. Dockerfile exposes 5000; no k8s manifests in-repo.
3. **OPTIONS** clients: none found. If a probe uses OPTIONS, add it in implementation, not by guessing.
4. **`GET /ready` Redis check** has no unit test when `REDIS_URL` is set (`test_rate_limit_redis.py` is skipped locally). Do not migrate `/ready` until that path is characterised.
5. Empty WSGI `PATH_INFO` still goes to Django (M0); unrelated to `/health`.
6. Dual sessions, GET Flask logout, Django login rate limit remain (audit C3–C4). Out of this slice.

---

## 12. Explicit statement: no application code or route ownership was changed

This audit created only `docs/apex-m1-route-selection-audit.md`.

It did not modify Python modules, tests, settings, dependencies, migrations, Docker files, `FLASK_PREFIXES`, or environment variables. It did not migrate `/health` or any other route. It did not merge, deploy, or call Twilio/OpenAI.

---

*End of audit. Stop here until `GET /health` is explicitly approved as the first implementation slice.*
