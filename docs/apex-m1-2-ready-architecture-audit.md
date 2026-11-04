# Apex M1.2 — Read-only `/ready` architecture audit

**Audit type:** Read-only operational and architecture review of Flask `GET /ready`  
**Date:** 4 November 2026 (Africa/Johannesburg)  
**Repository:** `lesleysacks/a.i-receptionist`  
**Baseline branch:** `feature/apex-m1-1-1-health-parity`  
**Baseline commit:** `9ad504019f55128627fefae4357d1d422e7a27af` (`fix(apex): preserve health endpoint HTTP parity`)  
**Audit branch:** `feature/apex-m1-2-ready-audit`  
**Previous milestone:** M1.1.1 — Django `/health` HTTP parity (CSRF 405, HEAD `Content-Length` 16)

This document is an audit, not an implementation. No application code, routes, tests, configuration, or migrations were changed for this milestone.

Legend:

- **Verified** — observed in source, configuration, existing tests, or a local read-only probe on this commit.
- **Inferred** — follows from the verified code path but was not executed in this run.
- **Not verified** — outside this repository or deliberately not exercised.

---

## 1. Executive summary

In the current Apex process, **readiness means: the SQLAlchemy engine can run `SELECT 1`, and if `REDIS_URL` is set, Redis answers `PING`.** That is the entire runtime check in `routes.ops.ready`. It does not mean “the application can process a customer WhatsApp conversation”, “Django accounts/tenants are migrated”, “the RQ worker is alive”, or “Twilio/OpenAI are reachable”.

`GET /ready` is still a Flask route on `ops_bp`, reached only because `wsgi.app` sends `/ready` to Flask (`apex/http_dispatch.py` `FLASK_PREFIXES`). Django `apps.ops` owns `/health` only.

The check is **safe as a coarse dependency probe** and **unsafe as a perfect orchestration readiness signal**:

- It can return **503** while conversations still work (Redis configured but down; jobs already fall back to inline execution).
- It can return **200** while management/auth or intelligence persistence cannot work (Django schema not checked) or while outbound messaging cannot work (Twilio/OpenAI not checked).
- Timeouts are **not fully bounded**. PostgreSQL checkout can wait `DB_POOL_TIMEOUT` (default 30s). Redis `from_url` + `ping()` has **no socket timeout**. Either can occupy a Gunicorn gthread until `GUNICORN_TIMEOUT` (default 30s).
- Every probe runs a real SQL statement against the **process-global** SQLAlchemy engine. When `REDIS_URL` is set, every probe also opens a **new** Redis client and pings it. There is no caching, debounce, or circuit breaker.

**Recommendation:** do **not** migrate `/ready` to Django in the next milestone. Remain on Flask (**Option A**) until the HTTP/JSON contract, Redis behaviour, and timeouts are locked in tests. A 1:1 Django port (**Option B**) is technically possible later, but M1.1.1 showed that Django `ALLOWED_HOSTS`, CSRF decorator order, OPTIONS, and HEAD `Content-Length` change probe behaviour. Redesigning into split probes (**Option C**) is the better *product* meaning of readiness, but it would change 200/503 semantics and must not be bundled with a framework move.

Do not implement that recommendation until it is approved.

---

## 2. Current `/ready` implementation

### 2.1 Route registration

| Item | Value | Evidence |
| --- | --- | --- |
| Blueprint | `ops_bp = Blueprint("ops", __name__)` | `routes/ops.py` |
| Handler | `ready` (`ops.ready`) | `routes/ops.py` `@ops_bp.get("/ready")` |
| Flask registration | `app.register_blueprint(ops_bp)` with no url prefix | `app.py` |
| HTTP methods on the rule | `GET`, `HEAD`, `OPTIONS` | Flask `url_map` on this commit: `'/ready' ['GET', 'HEAD', 'OPTIONS'] ops.ready strict True` |
| Trailing slash | Exact `/ready` only; `strict_slashes=True` | Same `url_map`; `GET /ready/` is 404 |
| Auth | None | `ready()` has no decorator and does not read session |
| CSRF | Blueprint exempt | `app.py` `csrf.exempt(ops_bp)` |
| Tenant | None | Handler does not call business/tenant services |
| Response helper | Flask `jsonify` | `routes/ops.py` |

Verified local contract (Flask test client and live `wsgi.app`, SQLite, `REDIS_URL` unset):

| Request | Result |
| --- | --- |
| `GET /ready` | `200`, `Content-Type: application/json`, body `{"checks":{"database":"ok"},"status":"ready"}\n`, `Content-Length: 46` |
| `HEAD /ready` | `200`, empty body, `Content-Type: application/json`, `Content-Length: 46` |
| `GET /ready?foo=bar` | Same 200 JSON as GET |
| `GET /ready` with `Host: not-allowed.example` | `200` (Flask does not apply Django `ALLOWED_HOSTS`) |
| `POST` / `PUT` / `PATCH` / `DELETE` | `405` HTML (Werkzeug), not JSON |
| `OPTIONS /ready` | `200`, empty body, `Content-Type: text/html; charset=utf-8` |
| `GET /ready/` | `404` HTML (no slash redirect) |
| `GET /readyz` | Dispatcher sends this to Django (`flask_owns_path` is false); Flask itself also has no such rule |

JSON key order is sorted (`app.json.sort_keys` is `True` on Flask 3.1.3). `status` is therefore emitted after `checks`. This matches the captured body above.

`routes/ops.py` still documents that `GET /health` moved to Django and that this blueprint keeps `GET /ready` only.

### 2.2 What the handler actually does

```22:44:routes/ops.py
@ops_bp.get("/ready")
def ready():
    """Readiness: required dependencies are available to serve traffic."""
    checks: dict[str, str] = {}
    ready_ok = True

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("Readiness check failed: database")
        checks["database"] = "unavailable"
        ready_ok = False

    # Redis is only required when configured (jobs / shared rate limiting).
    if redis_url():
        checks["redis"] = "ok" if get_redis_connection() is not None else "unavailable"
        if checks["redis"] != "ok":
            ready_ok = False

    status = "ready" if ready_ok else "not_ready"
    return jsonify({"status": status, "checks": checks}), (200 if ready_ok else 503)
```

Call tree from the handler (no other application services):

1. `database.engine.connect()` then `sqlalchemy.text("SELECT 1")` / `connection.execute`
2. `services.jobs.redis_url` → `apex_receptionist.services.jobs.redis_url` (`os.getenv("REDIS_URL")`)
3. If that value is truthy: `services.jobs.get_redis_connection` → `apex_receptionist.services.jobs.get_redis_connection` (`redis.Redis.from_url` + `ping()`)
4. `flask.jsonify` + HTTP 200 or 503
5. Flask `app._log_request` after every request (`app.py`)
6. Database failures: `logger.exception("Readiness check failed: database")`
7. Redis failures inside `get_redis_connection`: `logger.warning("Redis is configured but unreachable; falling back to inline execution.")` — even though this call is a probe, not a job enqueue
8. Uncaught exceptions (not expected from `ready()` itself) would hit `app._unexpected_error` (`500` HTML, no exception text)

The docstring says “required dependencies are available to serve traffic.” The code’s actual required set is: SQLAlchemy `SELECT 1` always, Redis ping **only when `REDIS_URL` is set**.

---

## 3. Full request and dependency flow

```
probe GET /ready
  → gunicorn -c gunicorn.conf.py wsgi:app     (timeout default 30s, gthread)
    → wsgi.app
      → apex.http_dispatch.dispatch_wsgi
        → flask_owns_path("/ready") is True     (FLASK_PREFIXES includes "/ready")
          → Flask app (app.py)
            → before_request _start_timer
            → CSRFProtect (ops_bp exempt)
            → ops.ready
               → SQLAlchemy engine.connect() + SELECT 1
               → optional Redis from_url + ping
            → jsonify 200|503
            → after_request _log_request (JSON access log)
```

### 3.1 WSGI dispatcher ownership — verified

`wsgi.py` documents Flask ownership of `/ready`. `apex/http_dispatch.py` includes `"/ready"` in `FLASK_PREFIXES`. Nested paths match `prefix` or `prefix + "/"`:

- `/ready` → Flask
- `/ready/` → Flask (then Flask 404)
- `/ready/something` → Flask (then Flask 404)
- `/readyz` → Django (lookalike, not a prefix match)

Tests: `tests/test_wsgi_dispatch.py` (`test_leads_dashboard_admin_and_ops_paths_go_to_flask_only`, `test_wsgi_app_callable_uses_the_same_prefix_rules`, `test_health_is_django_and_other_receptionist_paths_stay_flask`, `test_similar_but_non_matching_prefixes_go_to_django`).

This audit also invoked live `wsgi.app` for `GET/HEAD/POST/OPTIONS /ready`, `GET /ready/`, unapproved `Host`, and `GET /health`. `/ready` responses came from Flask; `/health` from Django.

### 3.2 Middleware and decorators — verified

Flask process (`app.py`):

- `load_dotenv()`, `setup_django()`, `configure_logging()`, `init_sentry()`, `apply_config(app)`
- `CSRFProtect(app)` then `csrf.exempt(ops_bp)`
- `before_request` timer; `after_request` JSON log including `/ready`
- Generic `errorhandler(Exception)` for uncaught errors
- Boot requires `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` (process start, not the ready handler)
- `init_database()` at import (schema create in non-production; no-op when `APP_ENV=production`)

There is no Flask-CORS usage in application Python (`flask-cors` is in `requirements.txt` but not imported).

Django middleware (`apex/settings.py`) does **not** run for `/ready` because the dispatcher never calls Django for that path. `ALLOWED_HOSTS`, `CsrfViewMiddleware`, and Django auth are therefore irrelevant to the current endpoint. They **would** become relevant under Option B.

### 3.3 Authentication and CSRF — verified

- No login, API key, or Twilio signature check on `ready()`.
- Blueprint CSRF exemption: `app.py` `csrf.exempt(ops_bp)`.
- With `APP_ENV=development` (`WTF_CSRF_ENABLED True`), this run observed `GET /ready` → 200 JSON and `POST /ready` → 405 (method), not CSRF 400. Contrast: `POST /login` without a token → 400 `"The CSRF token is missing."`
- Pytest default profile disables CSRF globally (`config.py` `TestingConfig.WTF_CSRF_ENABLED = False`), so default tests do not prove the exemption. The development-profile probe above does.

### 3.4 Logging and exceptions — verified

- Success: `app._log_request` at INFO (`event=request`, method, path, status, latency_ms). High probe rates produce high log volume.
- Database failure: stack trace via `logger.exception`; response body does **not** include the exception text (`tests/test_ops.py` `test_ready_fails_when_database_unavailable` asserts `"db down"` is absent).
- Redis failure: warning from `get_redis_connection`, no exception text in the JSON. **No unit test covers this `/ready` path.**
- Optional Sentry (`services.observability.init_sentry`, Flask integration): a database `logger.exception` **may** become an event if `SENTRY_DSN` is set. **Not verified** in this run (DSN unset; no live Sentry). Repeated 503 probes could theoretically flood Sentry.

---

## 4. Database findings

### 4.1 Which database

**Verified:** `/ready` uses the **SQLAlchemy** engine from `database.py`, not Django’s `django.db`.

- `DATABASE_URL` is read once at import: `database.DATABASE_URL = _normalize_url(os.getenv("DATABASE_URL", "sqlite:///receptionist.db"))`
- `postgres://` is rewritten to `postgresql://`
- Default without env: SQLite file `receptionist.db`
- Compose and CI set PostgreSQL URLs; pytest `tests/conftest.py` **overwrites** `DATABASE_URL` to a temporary SQLite file **before** importing `database`, so default tests never exercise the PostgreSQL branch of `/ready`

Django uses the **same** `DATABASE_URL` for `DATABASES["default"]` (`apex/settings.py` `_database_from_url`) but a **different** connection pool (`CONN_MAX_AGE` 60 on PostgreSQL). `/ready` never touches it.

README line “checks PostgreSQL” is imprecise relative to the code: the handler checks whichever backend `DATABASE_URL` selected when `database.py` was imported.

### 4.2 Query and connection reuse

**Verified:**

- Operation: `engine.connect()` context manager, then `connection.execute(text("SELECT 1"))`.
- This is a real statement, not a pool-status flag.
- The **engine is process-global** (`database.engine`). Each request checks out a pooled connection and returns it when the `with` block exits. It does not call `create_engine` per request.
- SQLAlchemy 2 `connect()` + `execute()` begins a transaction that is rolled back on context exit if not committed. `SELECT 1` does not write data.

PostgreSQL engine options (`database._create_engine`):

| Setting | Default | Source |
| --- | --- | --- |
| `pool_size` | 5 | `DB_POOL_SIZE` |
| `max_overflow` | 10 | `DB_MAX_OVERFLOW` |
| `pool_timeout` | 30 | `DB_POOL_TIMEOUT` |
| `pool_recycle` | 1800 | `DB_POOL_RECYCLE` |
| `pool_pre_ping` | `True` | hard-coded |

**Inferred:** on PostgreSQL, `pool_pre_ping=True` issues a driver liveness check (typically another `SELECT 1`) at checkout, then `ready()` runs a second `SELECT 1`. Two round-trips per healthy probe.

SQLite branch: `create_engine(url, connect_args={"check_same_thread": False}, future=True)` — no `pool_pre_ping`, no explicit `pool_timeout`. This run still observed SQLAlchemy’s default `QueuePool` (`size` 5, `timeout` 30.0, `pre_ping` False) for SQLite. The comment in `database.py` about “default single-file connection handling” is therefore slightly misleading; SQLite is still pooled.

**Verified not present:** no `connect_timeout` in `create_engine` or documented `DATABASE_URL` query parameters. A blackholed PostgreSQL host can hang at TCP connect until the Gunicorn worker timeout, independent of `pool_timeout` (which only waits for a free pool slot).

### 4.3 Failure handling and subsequent requests

**Verified:**

- Any `Exception` during connect/execute sets `checks["database"] = "unavailable"` and HTTP 503.
- There is **no sticky latch**. The next request repeats the check. A recovered database can return 200 without restart.
- The existing failure test monkeypatches `routes.ops.engine.connect` to raise `RuntimeError`; it does not stop a real PostgreSQL. Behaviour when the pool holds a dead connection is therefore **inferred**: `pool_pre_ping` should reconnect on PostgreSQL; SQLite has no pre-ping.

Failed checks do not modify business rows. The statement is read-only.

### 4.4 Load from repeated probes

**Verified / inferred:**

- Each `GET /ready` executes at least one SQL statement on the receptionist engine.
- Frequent load-balancer probes share the same pool as `/whatsapp` and dashboard traffic (`pool_size` default 5, `max_overflow` 10 on PostgreSQL).
- Pool exhaustion: a probe can block up to `pool_timeout` (30s) waiting for a connection, then raise, then 503. During that wait it also occupies a Gunicorn thread (`GUNICORN_THREADS` default 4, `workers` default 2).
- `SELECT 1` is cheap compared with conversation work, but it is not free and is not rate-limited.

### 4.5 Dual ORM gap

**Verified:** `/ready` does not run Django `connection.ensure_connection()`, `SELECT 1` on Django, or a migration check. A process can report `ready` after SQLAlchemy `create_all` / Alembic while Django `migrate` has not been applied. Docker `docker-entrypoint.sh` runs both Alembic and `manage.py migrate` before Gunicorn, which reduces this gap **in Compose**. Bare `python app.py` in development can serve Flask tables without Django tables. That path was **not** booted end-to-end in this audit beyond `manage.py check`.

---

## 5. Redis findings

### 5.1 Is Redis checked?

**Verified:** only when `redis_url()` is truthy (`os.getenv("REDIS_URL")`). Empty or unset → the `checks` object has **no** `redis` key. Compose and CI set `REDIS_URL`; pytest `tests/conftest.py` **pops** `REDIS_URL` before imports, so default tests never take the Redis branch.

### 5.2 Mandatory, optional, or unused?

| Layer | Redis role | Evidence |
| --- | --- | --- |
| `/ready` | **Conditional-mandatory**: if `REDIS_URL` is set, ping failure → 503 | `routes/ops.py` |
| Customer conversations | **Optional** | `apex_receptionist/services/jobs.py` `_enqueue` runs `_run_inline` when `get_queue()` is `None`; `tests/test_jobs.py` `test_enqueue_runs_inline_without_redis` |
| Login rate limit | **Optional** with local fallback | `services/rate_limiter.py` `build_login_rate_limiter` |
| RQ worker process | **Required to boot** | `worker.py` exits if `get_redis_connection()` is `None` |
| Compose `app` and `worker` | `REDIS_URL` always set; Redis service healthchecked | `docker-compose.yml` |

So: the **application can process customer conversations without Redis**. `/ready` in Compose/production-style env **cannot** report ready without Redis, because `REDIS_URL` is set. That is a semantic mismatch between “can serve WhatsApp” and “readiness”.

### 5.3 What `get_redis_connection` does

**Verified** (`apex_receptionist/services/jobs.py`):

- `redis.Redis.from_url(url)` with **no** `socket_timeout`, `socket_connect_timeout`, or `health_check_interval`
- `conn.ping()`
- Success: return the client
- Any `Exception`: log warning, return `None`
- No connection cache at module level; `/ready` constructs a new client **every probe** when `REDIS_URL` is set
- `services/jobs.py` is only a compatibility shim re-exporting these functions

**Inferred:** a hung Redis TCP connect/ping can block the worker thread until Gunicorn `timeout` (default 30s). The probe then looks like a timeout, not a clean 503. Package `redis==8.1.0` is pinned in `requirements.txt`.

### 5.4 Environment differences

| Environment | `REDIS_URL` | `/ready` Redis key | Notes |
| --- | --- | --- | --- |
| Local `python app.py` (docs) | unset unless the operator exports it | omitted | README/AGENTS: optional |
| Pytest | popped in `conftest.py` | omitted | Redis path untested |
| GitHub Actions | job env sets `redis://localhost:6379/0`, then conftest pops it | omitted in tests | CI Redis is for optional rate-limit tests via `TEST_REDIS_URL` / localhost, **not** `/ready` |
| Docker Compose | `redis://redis:6379/0` on `app` and `worker` | expected `redis: ok` | `AGENTS.md` curl example includes `"redis":"ok"` |
| Production (README) | optional but recommended for multi-worker jobs | present iff set | Worker will not start without it |

`test_rate_limit_redis.py` talks to Redis independently of `/ready` and skips when ping fails. It is **not** coverage of the readiness Redis branch.

### 5.5 Does the response accurately reflect Redis?

**When `REDIS_URL` is unset:** yes — Redis is omitted, and the process is designed to run without it.

**When `REDIS_URL` is set and ping succeeds:** yes, `checks.redis = "ok"`.

**When `REDIS_URL` is set and ping fails:** the response says `unavailable` / `not_ready`. That is accurate about Redis, **inaccurate** as a statement that the app cannot serve traffic. Jobs already fall back to inline execution (`apex_receptionist/services/jobs.py`).

**When Redis is up but the RQ worker is down:** `/ready` still returns redis `ok`. Worker liveness is not checked. Notifications/reminders then sit in the queue. **Inferred** from `worker.py` being a separate process with no probe.

---

## 6. Other dependency findings

| Dependency | Required to boot the web process? | Checked by `/ready`? | Required to handle a WhatsApp turn? | Evidence |
| --- | --- | --- | --- | --- |
| SQLAlchemy / `DATABASE_URL` | Yes (import `database`) | **Yes** (`SELECT 1`) | Yes (conversation/booking state) | `database.py`, `routes/ops.py` |
| PostgreSQL vs SQLite | Production expects PostgreSQL; default is SQLite | Indirectly (whichever URL) | Same | `database.py`, README |
| Django DB / migrations | Django apps imported via `setup_django()` | **No** | Intelligence outcomes / login use Django models | `apex/settings.py`, `app.py` |
| Redis | No for web; yes for `worker.py` | **Only if `REDIS_URL` set** | No (inline jobs) | jobs module, `worker.py` |
| RQ worker | No | **No** | No for inbound reply; yes for async notify/remind if not inline | `app.notify_owner`, `enqueue_due_reminders` |
| APScheduler | Started only in `python app.py` `__main__`, not Gunicorn | **No** | Reminders under Gunicorn are supposed to use worker/beat (`app.start_scheduler` comment) | `app.py` |
| Twilio SID/token | **Yes** (`RuntimeError` at import if missing) | **No** | Signature validation yes; live send only with real creds | `app.py` |
| Twilio network / WhatsApp | No | **No** | Outbound messages | not called |
| OpenAI | No (`OPENAI_API_KEY` optional) | **No** | Unknown-question answers only | README, `AIService` |
| Sentry | No | **No** | No | `services/observability.py` |
| Filesystem | SQLite file if that URL is used | Indirectly via `SELECT 1` | SQLite only | `database.py` |
| `SECRET_KEY` | Production Django/Flask config | **No** | Sessions | `config.py`, `apex/settings.py` |
| `DJANGO_ALLOWED_HOSTS` | Production Django import | **No** for Flask `/ready` | Django routes only | `apex/settings.py` |
| External HTTP APIs | No | **No** | No for the ready path | handler imports |

This audit did **not** call Twilio, OpenAI, or any paid API.

**Basic application operation** (accept a signed webhook, persist a turn, reply TwiML): SQLAlchemy + Twilio credentials at boot. Redis, RQ, OpenAI, Sentry, and Django tables are **not** all required for that path, though Django intelligence persistence and accounts login need Django migrations.

---

## 7. Operational and monitoring assessment

### 7.1 Load balancer health checks

**Partially suitable**, with caveats:

- Unauthenticated GET JSON, no CSRF, no slash redirect, Flask ignores `Host`. IP-style probes that would fail Django `ALLOWED_HOSTS` still get 200 from `/ready` (verified with `Host: not-allowed.example` on `wsgi.app`).
- 503 on dependency failure is the usual LB “remove instance” signal.
- A slow/hung check (unbounded Redis ping or 30s pool wait) is **worse** than 503: Gunicorn may kill the worker (`timeout` 30s in `gunicorn.conf.py`).
- Logging every probe at INFO will dominate access logs if the interval is a few seconds.

`GET /health` (Django, no DB) is the better **liveness** target. `/ready` is closer to **readiness**, but it over-weights Redis and under-weights Django.

### 7.2 Container / orchestration probes

**Verified in repo:**

- `docker-compose.yml`: Postgres and Redis have `healthcheck`; the **`app` service has none**. `depends_on` waits for Postgres/Redis **startup**, not for `/ready`.
- `Dockerfile`: no `HEALTHCHECK`.
- No Kubernetes, Helm, Terraform, or nginx config in this repository.
- `docker-entrypoint.sh` waits up to ~30s for SQLAlchemy `SELECT 1`, then migrates, then `exec` Gunicorn. That is startup gating, not a runtime probe.

**Not verified:** any real hosting platform (Render, Fly, Cloud Run, k8s) that might already point at `/ready`. Nothing in-tree references it except docs, README, AGENTS.md, tests, and source.

### 7.3 False ready / false not-ready

**Can report ready when the process cannot do useful work (verified by absence of checks):**

- Django migrations missing / Django DB down while SQLAlchemy still answers `SELECT 1`
- RQ worker dead while Redis pings
- Twilio API down (inbound signature check still uses local token; outbound notify fails)
- OpenAI down (FAQ/booking path may still work)
- Disk-full later writes fail even if `SELECT 1` succeeded

**Can report not ready when the process can still serve WhatsApp (verified):**

- `REDIS_URL` set and Redis down (inline job fallback exists and is tested)
- Transient pool timeout / one slow `SELECT 1` while other threads still serve

### 7.4 Response format consumers

**Verified in-tree consumers of the JSON shape:**

- `tests/test_ops.py` — `status`, `checks.database`, HTTP 200 vs 503
- README troubleshooting, AGENTS.md curl example (`checks.database` and `checks.redis`)
- `docs/apex-m1-1-django-health.md`, `docs/apex-m1-route-selection-audit.md`, consolidation audit (M1 intended to keep `status` / `checks`)

No in-tree scraper, dashboard, or alert rule parses `/ready`. Changing keys, status codes, or omitting `checks.redis` when `REDIS_URL` is set **could** still break **external** monitoring that this repo cannot see. Flask `jsonify` sorted keys and trailing newline are part of the observed byte contract (`Content-Length: 46` without Redis).

M1.1.1 is the cautionary tale: Django HEAD `Content-Length` and CSRF 403 vs 405 were enough to need a follow-up. The same class of breakage applies to `/ready` (`OPTIONS` is 200 on Flask today; a Django `@require_http_methods(["GET", "HEAD"])` view would return 405, as `/health` does now).

### 7.5 Known infrastructure references

| Location | How `/ready` appears |
| --- | --- |
| `README.md` | Documented ops URL; 503 troubleshooting |
| `AGENTS.md` | Compose curl example including redis |
| `docs/apex-local-development.md` | One-line Flask readiness |
| `docs/apex-m1-1-django-health.md` | Explicitly still Flask |
| `docker-compose.yml` / `Dockerfile` / Gunicorn | **No** healthcheck path |
| `.github/workflows/ci.yml` | Does not curl `/ready`; pytest only |

---

## 8. Existing test coverage and gaps

### 8.1 What exists (verified)

| Test | What it proves |
| --- | --- |
| `test_ready_reports_database_ok` | Flask client GET 200, `status=ready`, `checks.database=ok` on SQLite with `REDIS_URL` absent |
| `test_ready_fails_when_database_unavailable` | Monkeypatched `engine.connect` → 503, `not_ready`, `database=unavailable`, exception text not leaked |
| `test_health_is_ok_and_independent_of_database` | Django `/health` still 200 if SQLAlchemy is broken |
| `tests/test_wsgi_dispatch.py` | `/ready` and `/ready/` are Flask-owned; `/readyz` is Django; live `wsgi.app` recording backend sees `/ready` on Flask |
| `test_enqueue_runs_inline_without_redis` | Conversations/jobs work without Redis (**not** a `/ready` test) |
| `test_rate_limit_redis.py` | Redis limiter (skip if down); **does not call `/ready`** |

There is **no** live `wsgi.app` assertion of the `/ready` JSON body (unlike `/health` in `test_wsgi_live_health_returns_ok_json`).

### 8.2 Gaps (recommended tests; not added in this audit)

1. **Redis configured and reachable** — `REDIS_URL` set, `get_redis_connection` returns a dummy, assert `checks.redis == "ok"` and HTTP 200.
2. **Redis configured and unavailable** — `REDIS_URL` set, `get_redis_connection` returns `None` or raises inside the helper, assert 503, `redis=unavailable`, no exception text, database still `ok` if the engine works.
3. **Redis unset** — assert `"redis" not in body["checks"]` (today this is only incidental).
4. **Timeouts** — Redis ping/connect hang is bounded (once timeouts are added); PostgreSQL `pool_timeout` / connect hang does not exceed a documented budget. These need fakes/clocks, not a real hang in CI.
5. **Repeated requests** — two GETs both 200 (or both 503) with no sticky latch; monkeypatch connect counter to show one checkout per request.
6. **Methods and slash** — HEAD empty body + `Content-Length` of GET payload; POST/PUT/PATCH/DELETE 405 not 403 with CSRF enabled; OPTIONS documented (200 Flask vs 405 if Django); `GET /ready/` 404; query string ignored.
7. **WSGI live contract** — `wsgi.app` GET `/ready` returns the JSON bytes and 200/503; unapproved `Host` still 200 **while Flask-owned**; after any Django migration, unapproved `Host` must be an explicit accepted change.
8. **Dispatcher** — already good; keep `/ready` owner assertions if the prefix moves.
9. **Missing configuration** — `DATABASE_URL` default SQLite still 200 in dev; empty `REDIS_URL` treated as unset.
10. **Django DB down, SQLAlchemy up** — documents current false-ready (should fail if the contract is later expanded; should pass if the contract stays SQLAlchemy-only).

Do not migrate `/ready` until at least items 1–3 and 6–7 exist. That matches the M1 route-selection audit’s warning that the Redis path is untested (`docs/apex-m1-route-selection-audit.md`).

---

## 9. Risks and severity

| ID | Risk | Severity | Kind | Evidence |
| --- | --- | --- | --- | --- |
| R1 | Unbounded Redis ping/connect blocks a Gunicorn thread | **High** (ops) | Timeout | `get_redis_connection` has no socket timeout; `gunicorn.conf.py` `timeout` 30 |
| R2 | PostgreSQL connect without `connect_timeout`; pool wait up to 30s | **High** (ops) | Timeout | `database._create_engine` |
| R3 | Compose `/ready` 503 when Redis is down even though WhatsApp still works | **Medium** | False not-ready | `routes/ops.py` + inline job fallback |
| R4 | `/ready` 200 when Django schema/worker/Twilio are not usable | **Medium** | False ready | handler scope vs `apps.*`, `worker.py` |
| R5 | Probe load: SQL `SELECT 1` (+ pre-ping) and a new Redis TCP client every request | **Medium** | Load | `ready()`, `get_redis_connection`, `pool_pre_ping` |
| R6 | Django migration of `/ready` inherits M1.1.1 failures: CSRF 403, HEAD length 0, OPTIONS 405, `ALLOWED_HOSTS` 400 | **High** if migrated without parity tests | Compatibility | `apps/ops/views.py`, M1.1.1 commit, this run’s Flask OPTIONS 200 / Host ignored |
| R7 | Redis warning log wording (“falling back to inline execution”) on a probe | **Low** | Observability | `apex_receptionist/services/jobs.py` |
| R8 | INFO access log per probe | **Low–medium** | Noise / cost | `app._log_request` |
| R9 | Possible Sentry event per DB 503 if DSN set | **Low–medium** | Cost | `logger.exception` + Flask Sentry integration |
| R10 | Dual ORM: operators may assume `/ready` covers Django | **Medium** | Operations | README “PostgreSQL” wording vs SQLAlchemy-only check |
| R11 | Changing JSON keys/status without warning external monitors | **Medium** | Compatibility | README/AGENTS; no in-repo alert config |
| R12 | Sticky-failure: none today; a future cache could hide recovery or outage | n/a currently | Design | each request independent |

---

## 10. Options A, B and C comparison

### Option A — remain on Flask

Keep `ops.ready`, keep `"/ready"` in `FLASK_PREFIXES`. Optionally harden timeouts and tests without moving the owner.

| Criterion | Assessment |
| --- | --- |
| Reliability | Current behaviour is small, battle-tested in unit tests for DB up/down. Redis still untested. No `ALLOWED_HOSTS` surprise. |
| Operational simplicity | Matches Compose/docs. Flask ignores Host, which is convenient for IP probes. |
| Dependency handling | Still SQLAlchemy + optional Redis; Django remains unchecked. Framework choice does not fix that. |
| Performance | Unchanged. Timeouts still need hardening regardless of owner. |
| Security | Unauthenticated by design. CSRF already exempt. Django Host check would not apply (slightly weaker Host filtering than `/health`). |
| Maintainability | Ops split (`/health` Django, `/ready` Flask) is ugly but each handler is tiny. |
| Integration risk | **Lowest.** |
| Testing | Can add Redis/method/WSGI tests against Flask now. |

### Option B — migrate to Django via the existing dispatcher

Remove `"/ready"` from `FLASK_PREFIXES`. Add `apps.ops.views.ready` using the **same** SQLAlchemy `engine` and Redis helpers. Delete Flask `ops.ready` so the path is not dual-owned (same lesson as `/health`).

| Criterion | Assessment |
| --- | --- |
| Reliability | No improvement to the check itself. Adds Django middleware (`ALLOWED_HOSTS`, CSRF decorator order). M1.1.1 required a follow-up for exactly this class of defect. |
| Operational simplicity | One more Django ops URL, but the view would still import the Flask SQLAlchemy stack — coupling increases, not decreases. |
| Dependency handling | Same unless the contract is silently changed (dangerous). |
| Performance | Same SQL and Redis work, plus Django middleware. |
| Security | `ALLOWED_HOSTS` would start applying (stricter; can break probes). CSRF must be outer `csrf_exempt` or POST becomes 403. |
| Maintainability | Aligns with consolidation, but a Django view that pings SQLAlchemy is not “more Django”. |
| Integration risk | **High** unless JSON bytes, HEAD length, OPTIONS, Host, and 405-vs-403 are specified and tested. |
| Testing | Needs the `/health` parity suite **plus** Redis and 503 cases. |

Smallest safe B boundary **if** later approved:

1. Characterise Redis in tests first (still on Flask).
2. Move **only** exact `/ready` (not `/ready/`).
3. Django view calls `database.engine` + `services.jobs` helpers — do **not** switch the DB check to `django.db`.
4. Outer `@csrf_exempt`, methods GET/HEAD only **or** explicitly keep Flask OPTIONS 200.
5. Preserve JSON keys `status` / `checks`, values `ready` / `not_ready` / `ok` / `unavailable`, 200/503, sorted compact JSON + newline, HEAD empty body with GET `Content-Length`.
6. Document `ALLOWED_HOSTS` for probes (Compose default `localhost,127.0.0.1`).
7. Remove Flask `ready` and the dispatcher prefix in the **same** change.
8. Do not change Redis mandatory semantics in that PR.

### Option C — redesign into separate checks

Examples: keep Django `/health` as liveness; SQLAlchemy `/ready` (or `/ready/db`); optional `/ready/redis`; maybe Django `/ready/django`. Orchestrators would probe the subset they need.

| Criterion | Assessment |
| --- | --- |
| Reliability | Best match to real failure modes (R3, R4) **after** consumers are updated. |
| Operational simplicity | Worse until probe config exists (none in-tree today). |
| Dependency handling | Explicit, which the current handler is not. |
| Performance | Can make Redis and DB probe intervals independent. |
| Security | Each URL still public GET; Host/CSRF rules depend on owner. |
| Maintainability | More routes and docs. |
| Integration risk | **Highest** for anyone already curling `/ready` and expecting Redis inside `checks`. AGENTS.md Compose example would break. |
| Testing | New contract tests; old 200/503 cases must be rewritten on purpose. |

Architectural consistency alone is not a reason to pick B. Option C is the right **product** conversation, not a silent migration.

---

## 11. Recommended approach with technical reasoning

**Remain on Flask (Option A) for the next implementation milestone.**

Reasons, in order:

1. **The dangerous parts of `/ready` are the check semantics and timeouts, not the web framework.** Moving the function to Django does not bound Redis ping, add `connect_timeout`, or decide whether Redis should fail the instance.
2. **M1.1.1 proved Django ownership changes probe HTTP.** Flask `/ready` today: unapproved Host 200, OPTIONS 200, HEAD `Content-Length` 46 (no Redis), CSRF-exempt 405 on POST. A Django port that copies `/health`’s decorators would change OPTIONS and Host immediately.
3. **The Django view would still depend on SQLAlchemy `database.engine`.** That is not a simplification of the hybrid process.
4. **Redis behaviour is untested on this endpoint.** The M1 route-selection audit already treated that as a migration blocker. Pytest pops `REDIS_URL`, so CI’s Redis service does not exercise `/ready`.
5. **False 503 on Redis (R3) is a contract issue.** Fixing it is Option C, not Option B. Combining a framework move with a semantics change would make rollback and monitoring blame ambiguous.

Option B is acceptable **later**, only as a copy of a **locked** Flask contract, not as the next change. Option C needs an explicit product decision: should Redis outage take the instance out of a load balancer when WhatsApp still works?

This recommendation disagrees with the earlier consolidation plan’s combined “M1 migrate `/health` and `/ready`” (`docs/apex-flask-django-consolidation-audit.md`) on purpose: `/health` was the low-risk first route; `/ready` is not the same risk class.

---

## 12. Proposed implementation scope for a future milestone

Suggested name: **M1.3 — Flask `/ready` contract lock and bounded-timeout hardening** (not a Django migration; not Option C).

In scope (after approval):

1. Tests listed in §8.2 items 1–3 and 6–7, still hitting Flask `ops.ready` and live `wsgi.app`.
2. Bounded Redis client timeouts in `get_redis_connection` (connect + socket), documented, with a test that a hang becomes `None` rather than blocking the handler indefinitely.
3. Documented PostgreSQL `connect_timeout` (engine `connect_args` or URL) so readiness cannot exceed a budget smaller than `GUNICORN_TIMEOUT`.
4. Docs: README “PostgreSQL” wording → “SQLAlchemy `DATABASE_URL` backend”; note that Django is not checked; note Redis 503 vs inline fallback.
5. Keep dispatcher prefix `/ready` on Flask.

Out of scope for that milestone:

- Django ownership of `/ready`
- Split URLs (Option C)
- Checking Twilio, OpenAI, RQ workers, or Django ORM
- Production deploy, merges beyond the M1.3 PR, paid APIs

A later **M1.4** (only if still wanted) would be Option B using the locked tests as the acceptance suite. A later **readiness-semantics** milestone would be Option C.

---

## 13. Rollback considerations

This audit only adds documentation. Rollback is `git revert` of the docs commit; no schema, route, or config rollback is required.

If a future Flask hardening change (timeouts) causes unexpected 503s: revert that commit; Redis/SQLAlchemy clients return to blocking defaults.

If a future Option B migration ships:

1. Put `"/ready"` back in `FLASK_PREFIXES`.
2. Restore `routes.ops.ready`.
3. Remove or stop including the Django `/ready` url (avoid dual ownership).
4. No database migration is involved.
5. Re-run dispatcher tests and a live `wsgi.app` GET `/ready`.

If a future Option C ships: restoring the single `/ready` JSON shape is required for any monitor that still expects `checks.redis` on that URL.

---

## 14. Items not inspected or not verifiable

- Production hosting, DNS, TLS, and any live load balancer or Kubernetes probe targeting `/ready` (no manifests in repo).
- This run did **not** start Docker Compose, Gunicorn as a service, Redis, or PostgreSQL. PostgreSQL `pool_pre_ping` double-`SELECT 1` is inferred from SQLAlchemy settings, not traced on a live server.
- Redis hung-ping duration and Gunicorn worker kill were **not** reproduced (would be a destructive/slow experiment).
- Sentry event emission on 503 was not exercised (`SENTRY_DSN` unset).
- Paid OpenAI/Twilio, real WhatsApp sends, and live Redis `/ready` JSON bytes (`checks.redis`) were not executed. Redis JSON shape is inferred from `jsonify` + `sort_keys True`.
- Whether CI’s Redis service is reachable for `test_rate_limit_redis.py` on this machine (one of two pytest skips; not investigated further).
- Django `manage.py check --deploy` (only default `manage.py check`).
- `flask-cors` unused import surface beyond confirming no application `CORS(` usage.
- Content of previous live Gunicorn acceptance logs from M1.1.1 except as historical context in docs.
- Worker scheduler / RQ dashboard.
- Database record contents (no queries beyond what `/ready` already does; no writes).

---

## Validation performed in this audit

| Check | Result |
| --- | --- |
| `git` HEAD | `9ad504019f55128627fefae4357d1d422e7a27af` on `feature/apex-m1-2-ready-audit` (branched from M1.1.1) |
| Working tree before docs | Clean |
| `python -m pytest` | **174 passed, 2 skipped**, exit 0 (23.17s this run) |
| `python manage.py check` | `System check identified no issues (0 silenced)` |
| Application source / routes / config / tests | Unchanged |
| Alembic / Django migrations generated | None |
| Merge / deploy | None |
| Paid APIs / WhatsApp | Not called |

Read-only probes used a temporary SQLite file and placeholder Twilio env vars only.
