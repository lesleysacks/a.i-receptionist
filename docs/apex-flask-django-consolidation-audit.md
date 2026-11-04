# Apex Flask/Django consolidation audit

**Product:** Apex by InterSacks Digital  
**Audit type:** Read-only HTTP architecture and migration assessment  
**Audit date:** 4 November 2026 (Africa/Johannesburg)  
**Inspected ref:** `feature/apex-phase-2-2-intelligence-outcomes` at `01fb9ce3b677cc56d97a93c71cf2053dc374c034`

**Classification**

| Label | Meaning |
| --- | --- |
| **Verified** | Observed in this tree |
| **Confirmed** | A control or defect located in code |
| **Design risk** | Safe today only because of surrounding controls; consolidation must not drop them |
| **Deployment assumption** | Depends on environment or operator procedure, not proven in production here |
| **Critical / High / Medium / Low / Informational** | Severity for security or migration failure |

This audit did not modify application code, tests, settings, dependencies, or migrations except for creating this report. No paid APIs were called. No secrets are reproduced.

---

## 1. Executive summary

Apex already has a **Django modular monolith for identity, tenancy, audit, and intelligence outcomes**, and a **Flask HTTP adapter** for WhatsApp, leads, the tenant dashboard, JSON `/admin`, and health checks. Production Gunicorn does **not** mount Flask inside Django. `wsgi:app` is a prefix dispatcher: selected paths go to the Flask WSGI app; everything else goes to Django.

The receptionist domain (`apex_receptionist`) is already framework-independent. Conversation FSM, Twilio signature checks, tenant routing by WhatsApp `To`, and `BusinessService` / `BookingService` do not need a rewrite. Consolidation is an **HTTP and session** problem, not a domain rewrite.

**Recommendation:** Option B — port Flask routes incrementally to Django views that call the existing services. Do not keep Flask mounted long-term (Option A). Do not replace routing in one cutover (Option C).

**Do not start implementation until this audit is accepted.** Highest-priority pre-work is a WSGI dispatcher regression test and fixing the documented Docker Compose production host configuration (Django `ALLOWED_HOSTS` is fail-closed and Compose does not set `DJANGO_ALLOWED_HOSTS`).

---

## 2. Verified repository and test baseline

| Item | Verified value |
| --- | --- |
| Remote | `https://github.com/lesleysacks/a.i-receptionist` |
| Branch | `feature/apex-phase-2-2-intelligence-outcomes` |
| HEAD | `01fb9ce3b677cc56d97a93c71cf2053dc374c034` |
| Parent | Phase 2.1 `06cd57ada878f54f6216b510d00de45ae35e766a` |
| `main` | `8d1c527` (Phase 1–2.2 **not** merged) |
| Working tree at inspection | Clean (this report is the only intended new file) |
| Newer commits on this branch | None |

**Checks run during this audit (non-destructive)**

- `python -m pytest` at this commit: process exit 0; two skips visible (`s`). Consistent with the verified **136 passed, 2 skipped** (live OpenAI; Redis limiter).
- `python manage.py check` with `APP_ENV=testing`: no issues.

Skipped tests (unchanged): `tests/test_openai_integration.py` (no `OPENAI_API_KEY`); `tests/test_rate_limit_redis.py` (no Redis in the local pytest process).

---

## 3. Current request-routing architecture

```
Gunicorn CMD: gunicorn -c gunicorn.conf.py wsgi:app     (Dockerfile)
python app.py                                           (Flask only; Django URLs not served)

wsgi.app(environ)
  PATH_INFO in {/, /whatsapp, /leads, /admin, /dashboard,
                /login, /logout, /health, /ready}  (+ prefix + "/")
        → Flask  (app.app)
  else  → Django (apex.wsgi.application)
```

**Verified dispatcher:** `wsgi.app` in `wsgi.py` (`FLASK_PREFIXES` plus exact `/`). This is a manual WSGI fork, not `django.urls` and not `werkzeug.middleware.dispatcher` wrapping inside Django.

**Process bootstrap (Flask import):** `app.py` calls `load_dotenv()`, `setup_django()` (`apex/setup_django.py`), `configure_logging()`, `init_sentry()`, `apply_config(app)` (`config.py`), `CSRFProtect(app)`, registers blueprints, requires `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`, then `init_database()`.

**Consequence:** even webhook-only traffic initialises Django settings. Production Docker Compose sets `APP_ENV=production` (`docker-compose.yml`) so `apex.settings.allowed_hosts_for_env` **requires** `DJANGO_ALLOWED_HOSTS` at import time.

**Two ORMs, one `DATABASE_URL`:** SQLAlchemy (`database.py`, Alembic) for receptionist tables; Django (`apex/settings.py` `DATABASES`) for `accounts`, `tenants`, `audit`, `intelligence`. No database rewrite is required for HTTP consolidation.

**ASGI:** `apex/asgi.py` exists and is unused by Gunicorn (`worker_class` default `gthread` in `gunicorn.conf.py`).

---

## 4. Route ownership inventory

Verified from `wsgi.py`, `app.py`, Flask blueprints, and `apex/urls.py`. Not inferred from docs alone.

### 4.1 Flask (`app.app`)

| Path | Handler | Auth | CSRF | Tenant source | ORM | Response | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `POST /whatsapp` | `app.whatsapp` | Twilio `X-Twilio-Signature` via `is_valid_twilio_request` → `apex_receptionist.adapters.twilio_webhook.is_valid_twilio_signature` | Exempt (`@csrf.exempt`) | `BusinessService.get_by_whatsapp_number(To)`; **no** default tenant | SQLAlchemy; Django used only to persist `IntelligenceOutcome` from the pipeline | TwiML `MessagingResponse` | `tests/test_webhook.py`, `test_routing.py`, `test_phase1_foundation.py` (`WEBHOOK_BASE_URL`, MessageSid), `test_intelligence_foundation.py` |
| `GET /leads` | `app.view_leads` | `routes.auth.login_required` | N/A (GET) | `admin.business_id` from Flask session / `AuthService.get_admin` | SQLAlchemy `BookingService.list_bookings` | HTML `templates/leads.html` | `tests/test_auth.py`, `test_tenant_leads.py`, `test_booking_flow.py` |
| `GET/POST /login` | `routes.auth.login_form` / `login` | Public; rate-limited `build_login_rate_limiter` | Flask-WTF on POST (`templates/login.html` `csrf_token`) | Membership via `AuthService.authenticate` → `principal_for_user`; unscoped platform admin **403** | Django `User` | HTML / redirect | `tests/test_auth.py`, `test_csrf.py`, `test_login_rate_limit.py`, `test_phase1_foundation.py` |
| `GET` and `POST /logout` | `routes.auth.logout` | Optional session | **GET is not CSRF-protected** | n/a | Django audit only | Redirect | `tests/test_auth.py` uses **GET** `/logout` |
| `/dashboard/*` | `routes.dashboard` (`dashboard_bp`) | `login_required`; mutations `write_required` | Flask-WTF (forms include `csrf_token`, e.g. `templates/service_form.html`) | `admin.business_id` only | SQLAlchemy `BusinessService` | HTML | `tests/test_dashboard.py` |
| `/admin/*` JSON | `routes.admin` (`admin_bp`, `_authenticate_and_scope`) | Flask session **or** `X-Admin-Key` == `ADMIN_API_KEY` (hmac) | **Blueprint CSRF-exempt** (`app.py`) | Session: membership; platform admin **must** send `X-Business-Id`; API key **must** send `X-Business-Id`. Never from JSON body | SQLAlchemy | JSON | `tests/test_admin_api.py`, `test_phase1_foundation.py` |
| `GET /health` | `routes.ops.health` | None | Exempt | n/a | None | JSON | `tests/test_ops.py` |
| `GET /ready` | `routes.ops.ready` | None | Exempt | n/a | SQLAlchemy `engine` (+ Redis if `REDIS_URL`) | JSON 200/503 | `tests/test_ops.py` |
| `GET /` | `app.home` | None | n/a | n/a | n/a | Plain text | None found |

Flask request size: `config.BaseConfig.MAX_CONTENT_LENGTH` default 64 KiB, applied in `apply_config`. Safe 500: `app._unexpected_error` (no exception text to client).

Idempotency: `app._already_processed` / `_mark_processed` on `ProcessedWebhook` (`provider`, `provider_message_id`).

### 4.2 Django (`apex.wsgi.application`)

| Path | Handler | Auth | CSRF | Tenant source | ORM | Response | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/accounts/login/` | `apps.accounts.views.login_view` | Public | `CsrfViewMiddleware`; test `test_django_login_requires_csrf` | n/a | Django `User` | HTML / redirect | `tests/test_phase1_foundation.py` |
| `POST /accounts/logout/` | `apps.accounts.views.logout_view` | Session optional | CSRF (POST-only `@require_http_methods(["POST"])`) | n/a | Django | Redirect | `test_django_logout_is_post_only_and_revokes_session` |
| `/accounts/` | `apps.accounts.views.home_view` | `@login_required` | n/a GET | Lists `Membership` for `request.user` | Django | HTML | login success test only |
| `/platform/tenants/` | `apps.tenants.views.tenant_list` | `@login_required` + `user_is_platform_admin` | n/a GET | All `Tenant` rows for platform admins | Django | HTML | `test_tenant_member_cannot_list_platform_tenants`, `test_platform_admin_can_list_tenants` |
| `/platform/django-admin/` | `django.contrib.admin` (`apex.urls`) | Django `is_staff` | Django admin CSRF | `IntelligenceOutcomeAdmin.get_queryset` → `outcomes_for_user` | Django | HTML | Model/queryset tests; **no** live admin HTTP test |
| `/static/` | Django staticfiles (if configured) | Public | n/a | n/a | n/a | Files | **None.** Docker entrypoint does not `collectstatic` |

Django limits: `DATA_UPLOAD_MAX_MEMORY_SIZE` default 64 KiB; `DATA_UPLOAD_MAX_NUMBER_FIELDS` 100. Hosts: `allowed_hosts_for_env` (`apex/settings.py`).

**No Flask static directory** is used; Flask templates embed CSS. Django admin CSS in production depends on `collectstatic` (not in `docker-entrypoint.sh`).

### 4.3 Dispatcher gaps (verified)

- Paths **not** in `FLASK_PREFIXES` (for example `/accounts/`, `/platform/`, `/static/`, unknown paths) always hit Django, including 404s.
- `python app.py` never uses `wsgi.py`. Django routes are unreachable on the Flask dev server. Local docs mention `wsgi:app` for Django login (`docs/apex-local-development.md`); README still shows `python app.py` as the primary run command.
- **No test** imports `wsgi.app` or asserts prefix routing.

---

## 5. Authentication/session architecture

**Identity store (verified):** Django `apps.accounts.models.User` (email `USERNAME_FIELD`, PBKDF2). Flask does not write `AdminUser` (`services.auth_service.AuthService`).

**Flask session (verified):**

- Cookie flags from `config.py`: `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE="Lax"`, `SESSION_COOKIE_SECURE` (on in production profile).
- Cookie **name not set** → Flask default `session`.
- Payload: `session["user_id"]` and `session["admin_id"]` (`routes.auth.login`).
- Principal: `AuthService.get_admin` → `apps.tenants.services.principal_for_user`.
- `login_required` requires `can_read` and a non-null `business_id` (platform admins without a tenant cannot use `/leads` or dashboard). Confirmed by `test_platform_admin_cannot_use_flask_dashboard_without_tenant`.

**Django session (verified):**

- Cookie name default `sessionid`; CSRF cookie `csrftoken` with `CSRF_COOKIE_HTTPONLY = True` (`apex/settings.py`).
- SameSite Lax; Secure when `APP_ENV=production` unless `SESSION_COOKIE_SECURE` overrides.
- `login()` / `logout()` in `apps.accounts.views`.

**Confirmed separation:** logging into Flask does not create a Django `request.user`. Logging into Django does not set Flask `session["user_id"]`. Operators need two cookies for the two UIs. Documented in `docs/apex-security.md` remaining risks.

**Logout:**

- Flask: GET and POST (`routes.auth.logout`). Nav uses GET (`templates/base.html` `url_for('auth.logout')`).
- Django: POST only.

**Rate limit:** Flask `/login` only (`services.rate_limiter`). Django `/accounts/login/` has **no** equivalent.

**Shared `SECRET_KEY` env:** Flask `resolve_secret_key` uses `SECRET_KEY` or `FLASK_SECRET_KEY`. Django also accepts `DJANGO_SECRET_KEY`. Same value does not unify sessions (different cookie names and serializers).

---

## 6. Security and tenant-isolation findings

### Confirmed controls (do not drop during consolidation)

| Control | Location |
| --- | --- |
| Twilio signature; optional `WEBHOOK_BASE_URL` | `apex_receptionist/adapters/twilio_webhook.py` `is_valid_twilio_signature`, `signed_webhook_url`; `app.is_valid_twilio_request` |
| No default-tenant webhook fallback | `app.whatsapp` + `BusinessService.get_by_whatsapp_number`; regression `test_webhook_does_not_use_default_business` |
| MessageSid idempotency | `app._already_processed`, `_mark_processed`, model `ProcessedWebhook` |
| Flask dashboard CSRF | `CSRFProtect` in `app.py`; tokens in login/dashboard forms |
| Django login CSRF; POST-only Django logout | `CsrfViewMiddleware`; `logout_view` |
| JSON admin tenant from principal or required `X-Business-Id`, never body | `routes.admin._authenticate_and_scope` |
| Cross-tenant JSON/UI blocked | `tests/test_admin_api.py`, `test_dashboard.py`, `test_tenant_leads.py`, `test_isolation.py` |
| Intelligence outcomes redacted + queryset isolation | `apps.intelligence.models.IntelligenceOutcome`; `outcomes_for_user` |
| PII masking on webhook logs | `app._mask`; structured extras allowlist `services.logging_setup._ALLOWED_EXTRA` |
| Generic Flask 500 | `app._unexpected_error` |
| Production Django hosts fail-closed | `apex.settings.allowed_hosts_for_env` |
| Password hashing | Django `User.set_password` |

### Findings

| ID | Severity | Type | Finding | Evidence |
| --- | --- | --- | --- | --- |
| C1 | **High** | Deployment / availability | Docker Compose `app` sets `APP_ENV=production` but does not set `DJANGO_ALLOWED_HOSTS`. Django settings raise `RuntimeError` on import. `app.py` always calls `setup_django()`, so the documented `docker compose up` image may fail to boot. | `docker-compose.yml` environment; `apex/settings.py` `allowed_hosts_for_env` |
| C2 | **High** | Design risk (migration) | Dual HTTP stacks and dual sessions. No dispatcher tests. Consolidation without a path-parity suite can silently send `/whatsapp` to Django 404 or drop Twilio CSRF exemption. | `wsgi.py`; no `tests/test_wsgi*.py` |
| C3 | **Medium** | Confirmed | Flask logout via GET. SameSite=Lax **does** send cookies on cross-site top-level GET, so a malicious link can clear the Flask session. Django logout already requires POST. | `routes.auth.logout`; `templates/base.html` logout `<a href>` |
| C4 | **Medium** | Confirmed | Django login is not rate-limited. Flask `/login` is. Password spraying against `/accounts/login/` is unconstrained at the app layer. | `apps.accounts.views.login_view` vs `routes.auth.login` |
| C5 | **Medium** | Design risk | `ADMIN_API_KEY` is a process-wide operator secret. CSRF is exempt on `admin_bp`. Cross-site JSON POST is largely mitigated by SameSite=Lax, but the key remains a single shared credential. | `routes.admin._authenticate_and_scope`; `app.py` `csrf.exempt(admin_bp)` |
| C6 | **Medium** | Design risk | `python app.py` serves Flask only. Operators following README “Running the application” never hit Django `/accounts/` or `/platform/`. | `app.py` `if __name__`; `wsgi.py` |
| C7 | **Low** | Confirmed | Django admin static files are not collected in `docker-entrypoint.sh`. `/platform/django-admin/` can render without CSS/JS in the production image. | `docker-entrypoint.sh`; `STATIC_ROOT` in settings; no `collectstatic` |
| C8 | **Low** | Informational | `flask-cors` is pinned in `requirements.txt` and never imported. | repo-wide grep: no `CORS` / `flask_cors` in `.py` |
| C9 | **Informational** | Design risk | Shared Twilio/OpenAI credentials; FAQ text in the model prompt; no POPIA export. Unchanged from Phase 1 security notes. | `docs/apex-security.md` |
| C10 | **Informational** | Deployment assumption | Compose default `SECRET_KEY=change-me-in-production` and `SESSION_COOKIE_SECURE=false`. Production safety depends on the operator overriding these. | `docker-compose.yml` |

No **Critical** unauthenticated PII dashboard remains on this branch (Phase 0 `/leads` and `/admin` issues are authenticated in recovered M5 + Phase 1). No endpoint was found that takes a **customer-supplied** tenant id as the sole trust source. `X-Business-Id` is only honoured for platform admins or the operator API key (`routes.admin._authenticate_and_scope`, `resolve_business_id_for_user`).

**Intelligence outcomes:** no public HTTP API. Access is Django admin + `outcomes_for_user`. Tenant members without `is_staff` cannot open `/platform/django-admin/`. That is intentional for Phase 2.2 (no dashboard). Consolidation must not add an unauthenticated outcomes route.

---

## 7. Flask/Django consolidation options comparison

### Option A — Mount Flask under Django (`WSGIMiddleware` / `DispatcherMiddleware` inside Django)

Keep current Flask views; Django becomes the only public WSGI app and forwards prefixes to Flask.

| Axis | Assessment |
| --- | --- |
| Compatibility | High for webhook/TwiML if prefixes stay exact |
| Security | Django `SecurityMiddleware` / `ALLOWED_HOSTS` can wrap Flask; **sessions stay split** unless extra work is done |
| Complexity | Low–medium (replace `wsgi.app`, prove Host/CSRF on forwarded paths) |
| Sessions | Unchanged dual cookies |
| Testability | Need Django test client **and** Flask client, plus middleware tests |
| Rollback | Revert `wsgi.py` |
| Maintainability | Two frameworks remain indefinitely |

Useful only as a **short** first slice if the team needs a single Gunicorn callable and Host checking immediately. It is not an end state.

### Option B — Port Flask routes to Django views; keep `apex_receptionist` (recommended)

Replace each Flask blueprint with Django views that call the same services. Delete Flask when the last route moves.

| Axis | Assessment |
| --- | --- |
| Compatibility | High if webhook is ported with CSRF exempt, raw TwiML, and the same signature helper |
| Security | One CSRF middleware, one session, one rate-limit policy; can close C3/C4 |
| Complexity | Medium; staged by route family |
| Sessions | **This is the only option that actually unifies login** |
| Testability | Existing service/FSM tests stay; HTTP tests switch `app.test_client()` → Django `Client` per route |
| Rollback | Per-phase: dispatcher still points leftover prefixes at Flask |
| Maintainability | Matches the Phase 0/1 target (Django management plane, extracted domain) |

Fits this repo: `ConversationService`, `BusinessService`, `is_valid_twilio_signature`, and `AuthService` are already callable without Flask request objects.

### Option C — One coordinated cutover

Rewrite `wsgi.py` and all Flask routes in one change, delete Flask.

| Axis | Assessment |
| --- | --- |
| Compatibility | Lowest. Webhook TwiML, CSRF exemptions, and session tests would move together |
| Security | Easy to drop an exemption or Host check |
| Complexity | High |
| Rollback | Entire release revert |
| Maintainability | Clean if it works; unjustified given Option B |

### Recommendation

**Option B**, with dispatcher tests **before** the first port, and with `wsgi.FLASK_PREFIXES` shrinking as each family lands. Do **not** treat Option A as the destination. Do **not** choose Option C.

No receptionist table rewrite. Dual ORM can remain until a later, separate persistence unification.

---

## 8. Recommended approach and rationale

1. Domain logic is already in `apex_receptionist` and Django apps. Flask is a thin adapter (`app.py`, `routes/`).
2. The operator pain is **two logins**, not two business engines. Mounting Flask (A) does not fix that.
3. Webhook behaviour is well tested at the Flask client layer and must keep signature + TwiML + idempotency. That argues for a dedicated webhook port step, not a big bang.
4. `wsgi.py` already isolates prefixes, so each Django replacement can drop one prefix and leave Flask serving the rest.
5. Security findings C3 and C4 are cheaper to fix while touching auth views than in a mount-Flask shim.

---

## 9. Phased migration plan

No phase writes destructive SQL. Rollback is git revert of that phase plus leaving Flask prefixes in `wsgi.py` until the Flask module is deleted.

### Phase M0 — Safety net (no user-visible change)

- **Scope:** Tests for `wsgi.app` dispatch; document `DJANGO_ALLOWED_HOSTS` on Compose/production. Optionally set Compose hosts for local `localhost` (config-only).
- **Files:** `tests/test_wsgi_dispatch.py`; maybe `docker-compose.yml` / docs.
- **Dependencies:** None.
- **Data:** None.
- **Tests:** `/whatsapp` → Flask; `/accounts/login/` → Django; `/platform/tenants/` → Django; unknown path → Django; trailing-prefix behaviour.
- **Accept:** Dispatcher tests green; Compose boot documented or fixed.
- **Rollback:** Delete the new tests.
- **Risk:** None to production behaviour if only tests/docs.

### Phase M1 — Ops routes to Django

- **Scope:** `GET /health`, `GET /ready` as Django views. Ready check should keep SQLAlchemy `engine` (same DB) and optional Redis.
- **Files:** `apps/` ops urls; `wsgi.py` remove `/health` `/ready`; `routes/ops.py` delete when unused; `tests/test_ops.py` via Django client.
- **Dependencies:** M0.
- **Data:** None.
- **Accept:** JSON shapes unchanged (`status`, `checks`); DB-down `/ready` still 503 without leaking exception text.
- **Risk:** Load-balancer probes. Mitigate by matching status codes and JSON keys exactly.

### Phase M2 — WhatsApp webhook to Django

- **Scope:** `POST /whatsapp` Django view: CSRF exempt, `is_valid_twilio_signature`, `BusinessService.get_by_whatsapp_number`, `ConversationService.handle`, TwiML string, MessageSid table.
- **Files:** new view module (e.g. `apps/webhooks/` or under `apex_receptionist` adapter + thin Django view); `app.whatsapp` removed from Flask; `wsgi.py` drop `/whatsapp`.
- **Dependencies:** M0; existing `ConversationService`.
- **Data:** None (same `processed_webhooks`).
- **Tests:** Port `test_webhook.py`, `test_routing.py`, signature/idempotency/size tests to Django `Client` **without** deleting assertions. Keep FSM tests (already non-HTTP).
- **Accept:** Unsigned 403; unknown `To` TwiML unchanged; booking via webhook still persists SQLAlchemy `Booking`; intelligence outcomes still insert.
- **Risk:** Proxy URL vs `WEBHOOK_BASE_URL`. Mitigate by reusing `signed_webhook_url`, not `request.build_absolute_uri` blindly. CSRF middleware must stay exempt.

### Phase M3 — Unified session + browser UI

- **Scope:** Replace Flask `/login`, `/logout`, `/leads`, `/dashboard/*` with Django views using `django.contrib.auth` and `principal_for_user` / `login_required` equivalents. POST-only logout. Apply login rate limit to the Django login path. Render existing Jinja templates via Django templates **or** port templates carefully (Flask `url_for` → `{% url %}`).
- **Files:** `apps/accounts/`, new dashboard app or `apps/tenants` views; `routes/auth.py`, `routes/dashboard.py`, `app.view_leads`; `templates/`; `wsgi.py` prefixes.
- **Dependencies:** M2 (webhook independent of browser session).
- **Data:** None. Users already Django `User`.
- **Tests:** Port `test_auth.py`, `test_csrf.py`, `test_dashboard.py`, `test_tenant_leads.py`, `test_login_rate_limit.py`. Add: one login cookie opens leads **and** `/accounts/`; GET `/logout` is 405.
- **Accept:** Tenant member read-only; cross-tenant service edit still 404/redirect; CSRF required.
- **Risk:** Jinja/`url_for` and flash messages. Mitigate by porting one dashboard page first (leads).

### Phase M4 — JSON `/admin`

- **Scope:** Django URLs under `/admin/` **or** a new `/api/admin/` with a compatibility shim if clients exist. Keep session-or-API-key, `X-Business-Id` rules, CSRF: session browser calls need CSRF **or** stay token-authenticated API-only.
- **Files:** `routes/admin.py` → Django; `wsgi.py` drop `/admin`.
- **Tests:** Port `test_admin_api.py` and platform-admin header tests.
- **Risk:** Name clash with `/platform/django-admin/`. Keep JSON API prefix distinct in code review. CSRF exemption only if API key is required for non-browser clients.

### Phase M5 — Remove Flask

- **Scope:** Delete `app.py` Flask factory usage, `routes/`, Flask-WTF if unused, `wsgi.py` dispatcher (Django `apex.wsgi` becomes Gunicorn target). `collectstatic` in entrypoint. Dockerfile comment/CMD update.
- **Dependencies:** M1–M4.
- **Tests:** Full pytest; dispatcher tests now all-Django; `python manage.py check`.
- **Accept:** `gunicorn apex.wsgi:application`; no Flask import in request path.
- **Rollback:** Revert M5 only if M4 still has a tag with Flask prefixes.

**Out of scope for this programme (unchanged):** billing, RAG, public signup, merging SQLAlchemy tables into Django ORM, Redis/RQ replacement.

---

## 10. Required regression tests

**Add before M1 (blockers):**

- WSGI/path ownership matrix (Flask vs Django) for every prefix in `wsgi.FLASK_PREFIXES` plus `/accounts/`, `/platform/`.
- `GET /` still Flask (or explicitly moved).
- Production `allowed_hosts_for_env` still rejects missing/`*` hosts.

**Keep and re-run every phase (already exist):**

| Area | Tests |
| --- | --- |
| Twilio signature | `tests/test_webhook.py` |
| Tenant `To` routing | `tests/test_routing.py` |
| Idempotency / `WEBHOOK_BASE_URL` | `tests/test_phase1_foundation.py` |
| Booking FSM | `tests/test_booking_flow.py`, `test_booking_errors.py`, `test_conversation_persistence.py` |
| Lead isolation | `tests/test_tenant_leads.py` |
| Dashboard IDOR | `tests/test_dashboard.py` |
| JSON admin | `tests/test_admin_api.py` |
| CSRF (Flask today) | `tests/test_csrf.py` |
| Intelligence | `tests/test_intelligence_foundation.py`, `test_intelligence_outcomes.py` |
| Auth | `tests/test_auth.py`, Django CSRF/logout in `test_phase1_foundation.py` |

**Missing today (add during M2–M4, not by weakening old tests):**

- Dispatcher / dual-stack HTTP
- Flask GET logout CSRF (C3) — then Django POST-only becomes the control
- Django login rate limit (C4)
- Single-session: Flask dashboard cookie is Django session (after M3)
- Django admin `outcomes_for_user` over HTTP (staff vs tenant member)
- `collectstatic` or admin static 200 in production-like config
- Request-size 413 through **Django** webhook once M2 lands (`test_oversized_payload_is_rejected` currently uses Flask `test_request_context`)

Do not skip live OpenAI or Redis tests to greener CI.

---

## 11. Rollback strategy

| Layer | Method |
| --- | --- |
| Application | Revert the phase commit. Keep `wsgi.FLASK_PREFIXES` until Flask handlers are gone so traffic can fall back. |
| Schema | None expected. Do not squash or rewrite Alembic/Django histories for HTTP work. |
| Sessions | After M3, old Flask `session` cookies become inert. Users log in again. No table rollback. |
| Webhook | Twilio URL stays `/whatsapp`. Rollback is code-only if TwiML contract is preserved. |
| Compose/prod | Restore previous image tag. |

Do not `alembic downgrade` or `migrate intelligence zero` as part of HTTP rollback.

---

## 12. Open questions and deployment assumptions

1. **Is any external client calling JSON `/admin` with `X-Admin-Key`?** If yes, M4 must keep header auth and URL path.
2. **Production `DJANGO_ALLOWED_HOSTS` and `WEBHOOK_BASE_URL` values** are not in-repo (correct). Compose as committed is incomplete (C1).
3. **TLS terminator** and whether Flask `request.url` ever reaches Twilio without `WEBHOOK_BASE_URL` — deployment assumption; code prefers `WEBHOOK_BASE_URL`.
4. **Gunicorn `gthread` + APScheduler:** `start_scheduler()` only runs under `python app.py`, not Gunicorn. Reminders are `worker.py` / RQ when Redis is set. Consolidation must not start a per-worker scheduler.
5. **Cookie domain/path** are defaults (`/` , host-only). No custom `SESSION_COOKIE_DOMAIN` in settings or Flask config.
6. **Whether to rename JSON `/admin` to avoid confusion with Django admin** is a product choice; functionally they are already different paths (`/admin/` vs `/platform/django-admin/`).

---

## 13. Explicit statement: no application code was changed

This audit created only `docs/apex-flask-django-consolidation-audit.md`.

It did not modify Python modules, tests, settings, dependencies, migrations, Docker files, or environment variables. It did not merge, push as part of the inspection, deploy, or call Twilio/OpenAI. It did not start Flask/Django consolidation implementation.

---

*End of audit. Stop here until the recommended Option B phases are explicitly approved.*
