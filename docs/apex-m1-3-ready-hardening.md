# Apex M1.3 — Flask `/ready` contract lock and bounded-timeout hardening

**Date:** 4 November 2026 (Africa/Johannesburg)  
**Base:** `feature/apex-m1-2-ready-audit` @ `610a4ff20ea726eea29dfbc38b01e94b61afd920`  
**Implementation branch:** `feature/apex-m1-3-ready-hardening`

This milestone does **not** migrate `/ready` to Django. Flask still owns the route.

---

## 1. Existing readiness contract (preserved)

`GET /ready` is Flask `routes.ops.ready` on `ops_bp`, dispatched by `wsgi.app` because `"/ready"` remains in `apex/http_dispatch.py` `FLASK_PREFIXES`.

Readiness still means: SQLAlchemy `engine.connect()` + `SELECT 1`, and Redis `PING` **only when `REDIS_URL` is set**. Redis remains optional for conversations (inline jobs). This milestone does not change that policy.

| Request | Behaviour |
| --- | --- |
| `GET /ready` | `200` when configured checks pass |
| `GET /ready` | `503` when a configured check fails |
| `HEAD /ready` | `200`, empty body, GET `Content-Length` |
| `OPTIONS /ready` | `200`, empty body (Flask automatic OPTIONS) |
| `POST` / `PUT` / `PATCH` / `DELETE` | `405` HTML, not CSRF `400`/`403` |
| `GET /ready/` | `404` (`strict_slashes=True`) |
| `GET /ready?foo=bar` | Same as `GET /ready` |
| Unapproved `Host` | Flask ignores Django `ALLOWED_HOSTS` → still `200` when checks pass |

JSON (Flask `jsonify`, `sort_keys=True`, trailing newline):

| Situation | Body | Status |
| --- | --- | --- |
| Redis unset, DB ok | `{"checks":{"database":"ok"},"status":"ready"}\n` | 200 |
| Redis configured, both ok | `{"checks":{"database":"ok","redis":"ok"},"status":"ready"}\n` | 200 |
| DB down, Redis unset | `{"checks":{"database":"unavailable"},"status":"not_ready"}\n` | 503 |
| DB ok, Redis configured and down | `{"checks":{"database":"ok","redis":"unavailable"},"status":"not_ready"}\n` | 503 |

Status strings remain `ready` / `not_ready` / `ok` / `unavailable`. Exception text, URLs, and credentials are not included in the body. Auth is none; `ops_bp` stays CSRF-exempt.

---

## 2. Changes made

- PostgreSQL engines pass `connect_args={"connect_timeout": …}` (`database.postgres_connect_args`). SQLite is unchanged (`check_same_thread` only).
- Redis clients created with `socket_connect_timeout`, `socket_timeout`, and `retry_on_timeout=False`.
- Failed Redis clients are closed. `/ready` uses `redis_is_reachable()` which closes a successful probe client so probes do not leak connections. Job enqueue still uses `get_redis_connection()` and keeps the client open.
- HTTP/WSGI/Redis/timeout tests added. No new routes. No Django ownership change. No migrations.

---

## 3. Database timeout decisions

| Setting | Env | Default | What it bounds |
| --- | --- | --- | --- |
| TCP/auth handshake | `DB_CONNECT_TIMEOUT` | **3** seconds | New PostgreSQL connections (`psycopg2` `connect_timeout`) |
| Pool slot wait | `DB_POOL_TIMEOUT` | **30** seconds (unchanged) | Wait for a free SQLAlchemy pool connection |
| Pool size / overflow / recycle / pre-ping | existing `DB_POOL_*` | 5 / 10 / 1800 / on | Unchanged |

`connect_timeout` and `pool_timeout` are independent. Zero/`invalid` `DB_CONNECT_TIMEOUT` falls back to 3 because psycopg2 treats `0` as wait forever.

The process-global `database.engine` is still reused. `/ready` does not call `create_engine` per request.

SQLite development/tests do not receive `connect_timeout`.

---

## 4. Redis timeout decisions

| Setting | Env | Default | What it bounds |
| --- | --- | --- | --- |
| TCP connect | `REDIS_CONNECT_TIMEOUT` | **3** seconds | `socket_connect_timeout` |
| Read/PING | `REDIS_SOCKET_TIMEOUT` | **3** seconds | `socket_timeout` |

`retry_on_timeout=False` so a timeout is not doubled. Conditional check unchanged: no `REDIS_URL` → no `checks.redis` key; set and failing → `503`.

---

## 5. Environment variables

New:

- `DB_CONNECT_TIMEOUT` (seconds, default 3, must be > 0)
- `REDIS_CONNECT_TIMEOUT` (seconds, default 3, must be > 0)
- `REDIS_SOCKET_TIMEOUT` (seconds, default 3, must be > 0)

Unchanged and still relevant: `DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`, `REDIS_URL`, `GUNICORN_TIMEOUT` (default 30).

---

## 6. Timeout rationale

No in-repo Kubernetes/load-balancer probe interval exists. Compose Postgres/Redis healthchecks already use **3s** timeouts. Gunicorn worker timeout defaults to **30s**.

3s connect/read budgets fail fast for probes while remaining under the worker kill time when the pool has a free connection.

`DB_POOL_TIMEOUT` stays 30s so ordinary request threads are not failed sooner than before under pool pressure. That choice is deliberate: changing it would affect `/whatsapp` and dashboard traffic, which is out of scope.

---

## 7. Test coverage

- `tests/test_ops.py` — GET success bytes, DB 503 without leaks, Redis absent/ok/unavailable, HEAD, query string, slash 404, OPTIONS 200, 405 methods, CSRF-enabled GET/POST, no per-request `create_engine`.
- `tests/test_postgres_config.py` — connect vs pool timeout kwargs, zero/invalid connect timeout, SQLite not given Postgres args.
- `tests/test_ready_timeouts.py` — **live** Postgres handshake timeout against a silent TCP listener; **live** Redis connect/PING timeout against a silent listener; Redis connection refused; QueuePool checkout timeout (SQLite QueuePool); `/ready` maps SQLAlchemy pool timeout to 503; Redis kwargs actually passed; client close on ping failure and on successful `/ready` probe.
- `tests/test_wsgi_dispatch.py` — live `wsgi.app` `/ready` JSON/HEAD/OPTIONS/POST; unapproved Host forwarded to Flask; ownership of `/ready`, `/health`, `/whatsapp`, `/leads`, `/accounts`.

---

## 8. Operational implications

Typical healthy `/ready` on SQLite/Postgres with a warm pool is milliseconds plus optional Redis PING.

Worst-case **known** bound when Redis is configured, assuming a free pool slot:

`DB_CONNECT_TIMEOUT` + `SELECT 1` / `pool_pre_ping` + `REDIS_CONNECT_TIMEOUT` + `REDIS_SOCKET_TIMEOUT`

≈ 3 + cheap query + 3 + 3 ≈ **9 seconds**, plus Gunicorn/Flask logging overhead.

If the SQLAlchemy pool is exhausted, checkout can wait **`DB_POOL_TIMEOUT` (30s)** in addition to a later connect. That can equal `GUNICORN_TIMEOUT`. `/ready` can therefore still occupy a gthread for up to the pool wait.

Repeated probes still run a real `SELECT 1` on the shared engine. Redis probes open a client, PING, and **close** it.

---

## 9. Known limitations

- DNS resolution for `DATABASE_URL` / `REDIS_URL` hosts is **not** bounded by these socket timeouts.
- PostgreSQL `SELECT 1` and `pool_pre_ping` have no separate `statement_timeout`. A wedged session after a successful handshake can still block until TCP fails or Gunicorn kills the worker.
- `/ready` still does not check Django ORM, RQ workers, Twilio, or OpenAI.
- Redis down still yields `503` even though conversations can continue inline.
- Flask `logger.exception` on DB failure may still put driver text (including URLs) in **logs**; it is not returned in the HTTP body.

---

## 10. Rollback procedure

1. Revert the M1.3 commit on this branch (or restore `database.py`, `apex_receptionist/services/jobs.py`, `services/jobs.py`, `routes/ops.py`, and tests).
2. No database migrations to reverse.
3. `/ready` remains Flask either way.

---

## 11. Flask ownership (explicit)

`GET /ready` remains Flask-owned. `"/ready"` stays in `FLASK_PREFIXES`. Django `apps.ops` still serves only `/health`. No other Flask route was migrated.
