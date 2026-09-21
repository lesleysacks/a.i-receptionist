# AI Receptionist

A multi-tenant, WhatsApp-powered AI receptionist (Flask + Twilio + OpenAI). Each
business has its own WhatsApp number; inbound messages are routed to the correct
business, answered from that business's configured data, and can book
appointments through a guided, **durable** conversation. Bookings become leads
that authenticated business admins can view — scoped strictly to their own
business.

> For the original end-user/Twilio walkthrough, see [`README-SETUP.md`](README-SETUP.md).

---

## Architecture

```
Inbound WhatsApp ──"To" number──▶ Business (tenant) ──▶ Conversation FSM ──▶ Booking ──▶ Lead
                    (routing)         (isolation)        (durable state)     (idempotent)

Admin ──login (session)──▶ Authenticated ──scoped to──▶ Business ──▶ that business's Leads only
```

- **Routing** — the Twilio `To` number is normalized and looked up against
  `Business.whatsapp_number`. Unknown/missing numbers get a safe reply and are
  never silently attributed to another tenant.
- **Isolation** — every business-scoped query takes an explicit `business_id`;
  there is no "default business" fallback in any customer- or admin-facing path.
- **Durable conversation state** — the booking FSM is persisted per
  `(business_id, sender)` in the `conversation_states` table, so a conversation
  resumes after an application/process restart.
- **Auth** — admins log in with a hashed password (session cookie). `/leads` and
  the `/admin/*` API are protected and scoped to the admin's own business.

## Status: works locally vs. requires real credentials

| Capability | Status |
| --- | --- |
| Multi-business routing, booking FSM, tenant isolation | WORKS LOCALLY |
| Durable conversation state (survives restart) | WORKS LOCALLY |
| Admin login/logout, tenant-scoped `/leads`, admin API | WORKS LOCALLY |
| Twilio webhook signature validation | WORKS LOCALLY (computed test signature) |
| AI free-form answers via OpenAI | REQUIRES REAL CREDENTIALS (`OPENAI_API_KEY`); tested via mocked seam, safe fallback otherwise |
| Live WhatsApp send / owner notifications / reminders | REQUIRES REAL CREDENTIALS (real Twilio account) |

The booking flow does **not** require OpenAI (booking intent is detected
deterministically); OpenAI only powers free-form question answering.

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

(On Debian/Ubuntu you may first need `sudo apt-get install -y python3.12-venv`.)

## Initialize the database and bootstrap a tenant

```bash
python manage.py init-db
python manage.py create-business --name "Business A" --whatsapp "whatsapp:+27111111111"
python manage.py add-service --business-id 1 --name "PLC Programming" --price 750
python manage.py create-admin --business-id 1 --email admin@a.com   # prompts for password
```

The SQLite tables are also created automatically on first app boot.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Yes (to boot) | Twilio credentials; the auth token also validates webhook signatures. Dev placeholders are fine locally. |
| `SECRET_KEY` | Recommended | Flask session signing key. Without it an ephemeral key is used and admin sessions do not survive a restart. |
| `SESSION_COOKIE_SECURE` | No | Set `true` in production (HTTPS) so session cookies are only sent over TLS. |
| `ADMIN_API_KEY` | No | Enables operator API-key access to `/admin/*` (must be paired with an `X-Business-Id` header). |
| `OPENAI_API_KEY` | No | Enables live AI answers. Without it, answers fall back safely. |
| `OPENAI_MODEL` / `OPENAI_TIMEOUT` | No | Chat model (default `gpt-4.1-mini`) and request timeout seconds (default `15`). |
| `TWILIO_WHATSAPP_NUMBER` / `OWNER_PHONE_NUMBER` | No | Outbound sender and fallback owner notification number. |
| `DATABASE_URL` | No | SQLAlchemy URL (default `sqlite:///receptionist.db`). |
| `PORT` / `LOG_LEVEL` / `FLASK_DEBUG` | No | Server port (5000), log level (INFO), debug (off). |

**Secrets come only from the environment** — never hard-coded, committed, or logged.

### Configuring OpenAI

Set `OPENAI_API_KEY` (optionally `OPENAI_MODEL`, `OPENAI_TIMEOUT`). If the key is
missing or OpenAI errors/times out, the receptionist returns a safe "a team
member will assist you" message; the booking flow is unaffected.

### Configuring Twilio

Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and each business's WhatsApp number
(`manage.py create-business --whatsapp ...`). Point each Twilio WhatsApp
number's webhook at `POST /whatsapp`. Requests without a valid
`X-Twilio-Signature` are rejected with HTTP 403.

## Running the application

```bash
. .venv/bin/activate
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=dev_placeholder_token
export SECRET_KEY=dev-only-secret
python app.py
```

- Health check: `GET /`
- Admin login: `GET /login` (then the tenant-scoped `GET /leads`)
- Admin API: `GET /admin/business` (requires login or API key + `X-Business-Id`)

## Running tests

```bash
. .venv/bin/activate
python -m pytest
```

Tests use a temporary SQLite database and never call external services.

## Multi-business routing & tenant isolation

- A business is identified by its `whatsapp_number`. Inbound `To` numbers are
  normalized (channel prefix and formatting stripped) before lookup.
- Services, FAQs, leads, conversations, and admins are all keyed by `business_id`.
  Admin actions derive their tenant from the authenticated session (or API-key +
  `X-Business-Id`), never from the request body, so one admin cannot modify
  another business.
- SQLite foreign keys are enforced (via `PRAGMA foreign_keys=ON`), so invalid
  cross-references are rejected at the database level.

## Conversation persistence

The booking FSM (`idle → ask_name → ask_date → ask_service → confirm`) is stored
in `conversation_states` keyed by `(business_id, sender)`. A restart resumes the
conversation exactly where it left off. Confirmation is idempotent: a duplicate
"yes" (e.g. a network retry) does not create a second booking.

## Security limitations (not production-hardened)

- No CSRF tokens yet; session cookies use `SameSite=Lax` and `HttpOnly`. Enable
  `SESSION_COOKIE_SECURE=true` behind HTTPS.
- No login rate-limiting / brute-force lockout yet.
- The admin API-key principal is an operator-level key (can target any business
  via `X-Business-Id`); scope it carefully.
- SQLite is the default store; use a managed database (e.g. Postgres) and real
  migrations for production. FK enforcement is enabled for SQLite here.
- Live OpenAI and live Twilio delivery require real credentials and are not
  validated against the real services in this environment.
