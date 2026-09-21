# AI Receptionist

A multi-tenant, WhatsApp-powered AI receptionist (Flask + Twilio + OpenAI). Each
business has its own WhatsApp number; inbound messages are routed to the correct
business, answered from that business's configured data, and can book
appointments through a guided, durable conversation. Business admins log in to a
server-rendered dashboard to manage their services, FAQs, WhatsApp number, and
view their own leads.

> For the original end-user/Twilio walkthrough, see [`README-SETUP.md`](README-SETUP.md).

---

## Architecture

```
Inbound WhatsApp ──"To" number──▶ Business (tenant) ──▶ Conversation FSM ──▶ Booking ──▶ Lead
                    (routing)         (isolation)        (durable state)     (idempotent)

Admin ──login (session + CSRF)──▶ Dashboard ──scoped to──▶ Business ──▶ its Services / FAQs / Leads only
Operator ──ADMIN_API_KEY + X-Business-Id──▶ JSON /admin API (explicit tenant targeting)
```

## Database: SQLite (dev) vs PostgreSQL (production)

The app selects its backend from `DATABASE_URL` (SQLAlchemy URL):

- **Local development / tests**: SQLite (default `sqlite:///receptionist.db`). Foreign keys are enforced via `PRAGMA foreign_keys=ON`.
- **Production**: PostgreSQL, e.g. `DATABASE_URL=postgresql://user:pass@host:5432/dbname` (the `postgres://` alias is normalized automatically). Server databases use a SQLAlchemy `QueuePool` with `pool_pre_ping` and recycling; pool sizing is tunable via `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`.

No application code changes are needed to switch backends — only `DATABASE_URL`.

## Migrations (Alembic)

Schema is managed by Alembic (`migrations/`).

```bash
alembic upgrade head        # apply all migrations (fresh or existing DB)
alembic downgrade -1        # revert the last migration
alembic revision --autogenerate -m "describe change"   # create a new migration
```

- In **production** (`APP_ENV=production`) the app never calls `create_all`; the schema is owned by migrations, so tables are never silently rebuilt or dropped.
- In **development/testing** the app auto-creates tables on boot for convenience.

## Configuration profiles

`APP_ENV` selects a profile in `config.py`:

| Profile | Debug | Cookies Secure | CSRF | Notes |
| --- | --- | --- | --- | --- |
| `development` (default) | from `FLASK_DEBUG` | off | on | auto `create_all` |
| `testing` | off | off | off (per-test opt-in) | temp DB |
| `production` | off | on (default) | on | requires `SECRET_KEY`; migrations only |

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_ENV` | No | `development` (default) / `testing` / `production`. |
| `SECRET_KEY` | Prod: **yes** | Flask session signing key. Required in production; dev uses an ephemeral key. |
| `DATABASE_URL` | No | SQLAlchemy URL. Default `sqlite:///receptionist.db`; use `postgresql://...` for production. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | No | PostgreSQL pool tuning (defaults 5 / 10 / 30 / 1800). |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Yes (to boot) | Twilio credentials; the auth token validates webhook signatures. |
| `TWILIO_WHATSAPP_NUMBER` / `OWNER_PHONE_NUMBER` | No | Outbound sender and fallback owner-notification number. |
| `OPENAI_API_KEY` | No | Enables live AI answers; without it, answers fall back safely. |
| `OPENAI_MODEL` / `OPENAI_TIMEOUT` | No | Chat model (default `gpt-4.1-mini`) and request timeout seconds (default `15`). |
| `ADMIN_API_KEY` | No | Operator-level key for the JSON `/admin` API (must send `X-Business-Id`). |
| `REDIS_URL` | No | Enables Redis-backed distributed rate limiting and RQ background jobs (e.g. `redis://redis:6379/0`). Without it, jobs run inline and rate limiting is process-local. |
| `SENTRY_DSN` | No | Enables optional Sentry error tracking. Without it, error tracking is off and the app runs normally. |
| `SESSION_COOKIE_SECURE` | No | Force `Secure` session cookies (default on in production). |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS` / `LOGIN_LOCKOUT_SECONDS` | No | Login rate-limit tuning (defaults 5 / 300 / 300). |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` / `GUNICORN_TIMEOUT` | No | Gunicorn tuning (defaults 2 / 4 / 30). |
| `LOG_FORMAT` | No | `json` (default) or `plain`. |
| `PORT` / `LOG_LEVEL` / `FLASK_DEBUG` | No | Server port (5000), log level (INFO), debug (off). |
| `SENTRY_TRACES_SAMPLE_RATE` | No | Sentry tracing sample rate (default 0). |

**Secrets come only from the environment** — never hard-coded, committed, or logged.

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

(On Debian/Ubuntu you may first need `sudo apt-get install -y python3.12-venv`.)

### Initialize the database and bootstrap a tenant

```bash
# Development (SQLite): tables auto-create, or run migrations explicitly:
alembic upgrade head
python manage.py create-business --name "Business A" --whatsapp "whatsapp:+27111111111"
python manage.py add-service --business-id 1 --name "PLC Programming" --price 750
python manage.py create-admin --business-id 1 --email admin@a.com    # prompts for password
```

## Running the application

```bash
. .venv/bin/activate
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=dev_placeholder_token
export SECRET_KEY=dev-only-secret
python app.py
```

- Admin login: `GET /login` → dashboard at `/dashboard` (Services, FAQs, Business, Leads)
- Leads: `GET /leads` (tenant-scoped, login required)
- Webhook: `POST /whatsapp` (Twilio signature required)

## Docker development (full stack)

Run the complete stack (app + PostgreSQL + Redis + background worker) with Docker
Compose. Only the app's port is published; Postgres and Redis stay internal.

```bash
docker compose up --build
# app on http://localhost:5000
```

The app container's entrypoint waits for the database, runs `alembic upgrade head`
(never `create_all`), then starts Gunicorn. The `worker` service runs the RQ
background worker. Bootstrap tenants once the stack is up:

```bash
docker compose exec app python manage.py create-business --name "Business A" --whatsapp "whatsapp:+27111111111"
docker compose exec app python manage.py create-admin --business-id 1 --email admin@a.com
```

## Production startup (Gunicorn)

Do not use `flask run` in production. Serve the WSGI app with Gunicorn:

```bash
alembic upgrade head          # apply migrations first
gunicorn -c gunicorn.conf.py wsgi:app
```

Run the background worker as a separate process (requires `REDIS_URL`):

```bash
python worker.py
```

## Infrastructure

- **PostgreSQL** — source of truth for businesses, admins, services, FAQs,
  bookings, and conversation state.
- **Redis** — ephemeral/shared infrastructure only: distributed login rate
  limiting and the RQ job queue. It is never the source of truth for business
  data. If `REDIS_URL` is unset, rate limiting is process-local and jobs run
  inline (idempotent, so this is safe for single-process dev).
- **Background worker (RQ)** — runs owner notifications and booking reminders off
  the request path. Jobs are idempotent (`owner_notified` / `reminder_sent`) and
  retried a bounded number of times.

## Observability

- `GET /health` — liveness; returns `{"status":"ok"}` and never touches the DB.
- `GET /ready` — readiness; checks PostgreSQL (and Redis when configured); returns
  503 when a dependency is down.
- **Structured JSON logs** (`LOG_FORMAT=json`) with per-request timing
  (`event`, `method`, `path`, `status`, `latency_ms`, masked `business_id`). No
  secrets, request bodies, or unmasked customer numbers are logged.
- **Sentry** (optional) via `SENTRY_DSN`; PII is not sent.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on pushes and PRs: installs
dependencies, runs `alembic upgrade head` against a PostgreSQL service, and runs
`pytest` (with a Redis service). Live OpenAI/Twilio are not required for CI.

## Running tests

```bash
. .venv/bin/activate
python -m pytest
```

Tests use a temporary SQLite DB and never call external services. The live
OpenAI test is skipped unless `OPENAI_API_KEY` is set.

## Troubleshooting

- **`/ready` returns 503** — check `DATABASE_URL` (and `REDIS_URL` if set) and that
  Postgres/Redis are reachable.
- **Migrations fail on startup** — ensure the DB is reachable and run
  `alembic upgrade head` manually to see details.
- **Background jobs don't run** — ensure `REDIS_URL` is set and the `worker`
  process/service is running; without Redis, jobs execute inline instead.
- **Login always blocked / never blocked** — tune `LOGIN_MAX_ATTEMPTS` /
  `LOGIN_WINDOW_SECONDS` / `LOGIN_LOCKOUT_SECONDS`.

## LOCAL / MOCKED vs LIVE / EXTERNAL SERVICES

- **LOCAL / MOCKED**: booking flow, tenant routing/isolation, admin UI, auth,
  CSRF, rate limiting, health/readiness, background jobs, migrations, and the
  full Docker stack all run without any external credentials.
- **LIVE / EXTERNAL SERVICES** (require real secrets): OpenAI answers
  (`OPENAI_API_KEY`), Twilio delivery / owner notifications / reminders
  (`TWILIO_*` + a real WhatsApp number), and Sentry error tracking (`SENTRY_DSN`).

## Admin dashboard

Business admins sign in and manage, **scoped to their own business only**:

- **Services** — list / create / edit / delete
- **FAQs** — list / create / edit / delete
- **Business** — name, WhatsApp number, contact details, booking toggle
- **Leads** — bookings for their business

All browser forms are CSRF-protected. Business A can never view or modify
Business B's data (enforced at the query level, not just hidden in the UI).

## Security

- **Passwords**: hashed with werkzeug (`generate_password_hash`); never stored or logged in plaintext.
- **Sessions/cookies**: `HttpOnly`, `SameSite=Lax`, `Secure` in production.
- **CSRF**: Flask-WTF `CSRFProtect` on browser forms. The Twilio webhook (its own signature validation) and the JSON `/admin` API (session- or API-key-authenticated machine clients) are exempt.
- **Login abuse**: per-IP rate limiting with temporary lockout; generic responses that don't reveal whether an account exists.
- **Tenant isolation**: every business-scoped query takes an explicit `business_id`; the webhook routes by WhatsApp number with no default fallback; admin tenancy is derived from the authenticated principal, never the request body.
- **Webhook**: Twilio `X-Twilio-Signature` validation (HTTP 403 on failure) is unchanged.
- **Database**: foreign keys enforced; unique constraints on WhatsApp number, `(business_id, sender)` conversation state, and `(business_id, name)` services.

## Security limitations (not absolutely production-secure)

- Login rate limiting is in-process; a multi-worker deployment should use a shared store (e.g. Redis).
- The operator `ADMIN_API_KEY` can target any business (by design); distribute it carefully.
- Live OpenAI and live Twilio delivery require real credentials and are not validated in this environment.
- A customer message that is exactly a command word (e.g. "cancel"/"restart") is treated as that command even when a name is expected (minor edge case).
