# AGENTS.md

Guidance for AI agents and developers working in this repository.

## Project overview

Multi-tenant WhatsApp AI receptionist (Flask + Twilio + OpenAI, SQLAlchemy;
SQLite for dev, PostgreSQL for production). Key modules:

- `app.py` — Flask app, config wiring, CSRF, `/whatsapp` webhook (routes by Twilio `To` number), `/leads`.
- `config.py` — environment profiles (development/testing/production).
- `database.py` — engine (SQLite or PostgreSQL via `DATABASE_URL`) + pooling + FK enforcement.
- `migrations/` — Alembic migrations (schema source of truth in production).
- `services/conversation_service.py` — booking FSM with durable, tenant-scoped state.
- `services/business_service.py` — tenant config, `get_by_whatsapp_number` routing.
- `services/auth_service.py`, `services/rate_limiter.py`, `routes/auth.py` — login (hashed passwords, sessions, rate limiting).
- `routes/dashboard.py` + `templates/` — server-rendered admin UI (services/FAQs/business/leads), CSRF-protected.
- `routes/admin.py` — tenant-scoped `/admin/*` JSON API (session or operator API key + `X-Business-Id`).
- `manage.py` — CLI to init the DB and create businesses/services/admins.

## Cursor Cloud specific instructions

The environment is defined in `.cursor/environment.json` (installs `python3.12-venv`,
creates `.venv`, installs `requirements.txt`, and runs the app on port 5000 with
dev placeholders). Commands below assume the repo root `/workspace`.

### Install

```bash
sudo apt-get update && sudo apt-get install -y python3.12-venv
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

### Initialize the database

```bash
. .venv/bin/activate
alembic upgrade head        # apply migrations (works for SQLite or PostgreSQL)
python manage.py init-db    # dev convenience (create_all); no-op in production
```

`DATABASE_URL` defaults to `sqlite:///receptionist.db`. For PostgreSQL set
`DATABASE_URL=postgresql://user:pass@host:5432/dbname`. In production
(`APP_ENV=production`) the app does not auto-create tables — run `alembic upgrade head`.

### Run Flask (dev)

```bash
. .venv/bin/activate
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=dev_placeholder_token
export SECRET_KEY=dev-only-secret
python app.py            # dev server on http://localhost:5000
```

### Run production-style (Gunicorn + optional Redis worker)

```bash
alembic upgrade head
gunicorn -c gunicorn.conf.py wsgi:app     # do NOT use flask run in prod
python worker.py                          # background jobs (needs REDIS_URL)
```

### Run the full stack with Docker

```bash
docker compose up --build                 # app + postgres + redis + worker
curl localhost:5000/health                # {"status":"ok"}
curl localhost:5000/ready                 # {"checks":{"database":"ok","redis":"ok"},"status":"ready"}
```

Ops endpoints: `GET /health` (liveness, no DB) and `GET /ready` (DB + Redis).
Logs are structured JSON (`LOG_FORMAT=json`).

### Run tests

```bash
. .venv/bin/activate
python -m pytest
```

Tests use a temporary SQLite DB and mock OpenAI/Twilio; no secrets required.

### End-to-end test (multi-tenant + persistence)

1. Start the app (above).
2. Bootstrap two tenants and admins:
   ```bash
   python manage.py create-business --name "Business A" --whatsapp "whatsapp:+27111111111"
   python manage.py add-service --business-id 1 --name "Service A1"
   python manage.py create-admin --business-id 1 --email a@example.com --password <pw>
   python manage.py create-business --name "Business B" --whatsapp "whatsapp:+27222222222"
   python manage.py add-service --business-id 2 --name "Service B1"
   python manage.py create-admin --business-id 2 --email b@example.com --password <pw>
   ```
3. POST signed `/whatsapp` requests with `To=whatsapp:+27111111111` to drive a
   booking for Business A (a valid `X-Twilio-Signature` is required; compute it
   with `twilio.request_validator.RequestValidator(TWILIO_AUTH_TOKEN)`).
4. Log in at `/login` as `a@example.com` and confirm `/leads` shows only
   Business A's lead; confirm Business B's admin does not see it.
5. Restart the app mid-conversation and confirm the booking resumes from
   persisted state.

### Secrets

- Optional for mocked tests / local dev: none required (OpenAI/Twilio are mocked
  or use placeholders). `SECRET_KEY` is recommended so admin sessions persist.
  `REDIS_URL` is optional (jobs run inline and rate limiting is process-local
  without it).
- Required for live integration testing:
  - `OPENAI_API_KEY` — live AI answers.
  - Real `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` (+ a real WhatsApp number) —
    live message delivery, owner notifications, and reminders.
  - `SENTRY_DSN` — live error tracking (optional).

## Conventions

- Never hard-code or log secrets. Resolve tenants by `business_id`, never a default.
- Add/keep tests under `tests/` and run `python -m pytest` before finishing.
