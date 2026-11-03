# Apex local development

Python 3.12, pip, and a virtualenv are enough for tests. PostgreSQL is required
for production-like runs.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Environment (placeholders only):

```bash
export APP_ENV=development
export SECRET_KEY=dev-only-secret
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=dev_placeholder_token
export DJANGO_SETTINGS_MODULE=apex.settings
# optional
export DATABASE_URL=sqlite:///receptionist.db
export WEBHOOK_BASE_URL=https://your-public-host.example
```

## Migrations

On a new database:

```bash
alembic upgrade head
python manage.py migrate
```

Production (`APP_ENV=production`) never calls SQLAlchemy `create_all`. Docker
entrypoint runs both Alembic and Django migrate.

Rollback (disposable data only):

```bash
python manage.py migrate accounts zero
alembic downgrade 379ee94dc59e   # drops processed_webhooks
```

## Run

Receptionist (Flask, includes Django setup):

```bash
python app.py
```

Bootstrap a tenant (creates SQLAlchemy business + Django tenant + admin user):

```bash
python receptionist_cli.py create-business --name "Business A" --whatsapp "whatsapp:+27111111111"
python receptionist_cli.py add-service --business-id 1 --name "PLC Programming" --price 750
python receptionist_cli.py create-admin --business-id 1 --email admin@example.com
```

Platform administrator (no public signup):

```bash
python manage.py create_platform_admin --email staff@example.com --password 'a-long-password'
```

- Receptionist login: `http://localhost:5000/login`
- Django login: `http://localhost:5000/accounts/login/` (via `wsgi:app` dispatcher)
- Health: `GET /health`, `GET /ready`
- Leads: `GET /leads` (authenticated, tenant-scoped)

Gunicorn:

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

Docker Compose (app + PostgreSQL + Redis + worker): `docker compose up --build`.

## Tests

```bash
. .venv/bin/activate
python -m pytest
```

Tests use a temporary SQLite database, Django migrations, and mocked
OpenAI/Twilio. They do not send WhatsApp messages or call paid APIs. The live
OpenAI test is skipped unless `OPENAI_API_KEY` is set; do not set it in CI.

## Deployment notes

1. Set `APP_ENV=production`, `SECRET_KEY`, `DATABASE_URL` (PostgreSQL), Twilio vars.
2. Set `WEBHOOK_BASE_URL` to the public HTTPS origin Twilio calls.
3. Set `DJANGO_ALLOWED_HOSTS` to the public hostname (comma-separated; no `*`).
4. Run Alembic then Django migrate (or use the Docker entrypoint).
5. Serve `wsgi:app` with Gunicorn; run `python worker.py` when `REDIS_URL` is set.
6. Point the Twilio WhatsApp webhook to `https://<host>/whatsapp`.
