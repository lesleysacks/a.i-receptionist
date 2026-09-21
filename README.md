# AI Receptionist

A WhatsApp-powered AI receptionist (Flask + Twilio + OpenAI) that answers
customer questions from configured business data and books appointments through
a guided, stateful conversation. Bookings are persisted per business and are
visible to owners through an admin API and a leads dashboard.

> For the original end-user/Twilio walkthrough, see [`README-SETUP.md`](README-SETUP.md).

---

## Status: what works locally vs. what needs real credentials

| Capability | Status |
| --- | --- |
| Booking conversation (start → name → date → service → confirm → persist) | **WORKS LOCALLY** (no external services required) |
| Input validation (date/time, unknown service, cancel/restart/change) | **WORKS LOCALLY** |
| Admin API (`/admin/*`) and leads dashboard (`/leads`) | **WORKS LOCALLY** |
| Twilio webhook signature validation | **WORKS LOCALLY** (uses `TWILIO_AUTH_TOKEN`; can be exercised with a computed test signature) |
| AI free-form answers via OpenAI | **REQUIRES REAL CREDENTIALS** (`OPENAI_API_KEY`). Fully tested through a mocked seam; falls back safely when unavailable. |
| Sending WhatsApp replies / owner notifications / reminders | **REQUIRES REAL CREDENTIALS** (real Twilio account) |

The booking flow does **not** require OpenAI: booking intent is detected
deterministically, so the full booking conversation and persistence work with no
external services. OpenAI is only used for free-form question answering.

---

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

(On Debian/Ubuntu you may first need `sudo apt-get install -y python3.12-venv`.)

Cloud Agent environment setup is defined in [`.cursor/environment.json`](.cursor/environment.json).

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `TWILIO_ACCOUNT_SID` | Yes (to boot) | Twilio account SID. A dev placeholder is fine locally. |
| `TWILIO_AUTH_TOKEN` | Yes (to boot) | Twilio auth token; also used to validate webhook signatures. |
| `TWILIO_WHATSAPP_NUMBER` / `TWILIO_PHONE_NUMBER` | No | Sender number for outbound WhatsApp messages. |
| `OWNER_PHONE_NUMBER` | No | Fallback owner number for booking notifications. |
| `OPENAI_API_KEY` | No | Enables live AI answers. Without it, answers fall back safely. |
| `OPENAI_MODEL` | No | Chat model (default `gpt-4.1-mini`). |
| `OPENAI_TIMEOUT` | No | OpenAI request timeout in seconds (default `15`). |
| `DATABASE_URL` | No | SQLAlchemy URL (default `sqlite:///receptionist.db`). |
| `ADMIN_API_KEY` | No | If set, `/admin/*` requires an `X-Admin-Key` header matching this value. |
| `FLASK_DEBUG` | No | `true` enables Flask debug mode (default `false`; keep off in production). |
| `PORT` / `LOG_LEVEL` | No | Server port (default `5000`) and log level (default `INFO`). |

**Secrets come only from the environment.** Never hard-code or commit credentials.

### Configuring OpenAI

Set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`, `OPENAI_TIMEOUT`) in your
environment or a `.env` file. If the key is missing or OpenAI errors/times out,
the receptionist returns a safe "a team member will assist you" message instead
of surfacing an error. The booking flow is unaffected.

### Configuring Twilio

Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_WHATSAPP_NUMBER`, then
point your Twilio WhatsApp sandbox webhook at `POST /whatsapp`. Signature
validation uses `TWILIO_AUTH_TOKEN`; requests without a valid `X-Twilio-Signature`
are rejected with HTTP 403.

## Running the application

```bash
. .venv/bin/activate
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
export TWILIO_AUTH_TOKEN=dev_placeholder_token
python app.py
```

Then:

- Health check: `GET http://localhost:5000/`
- Leads dashboard: `GET http://localhost:5000/leads`
- Admin API: `GET http://localhost:5000/admin/business`

## Running tests

```bash
. .venv/bin/activate
python -m pytest
```

Tests use a temporary SQLite database and never call external services (OpenAI
and Twilio are mocked / signature-computed).

## How the booking conversation works

The conversation is a small finite-state machine in
[`services/conversation_service.py`](services/conversation_service.py):

```
idle → ask_name → ask_date → ask_service → confirm → (persist) → idle
```

Example:

```
Customer:   I want to book an appointment
Bot:        Happy to help you book! What name should the booking be under?
Customer:   John Smith
Bot:        Thanks, John Smith! What date and time would you like? e.g. 2026-09-30 14:00.
Customer:   2026-12-30 14:00
Bot:        Great. Which service would you like to book? We offer: PLC Programming, Factory Automation.
Customer:   Factory Automation
Bot:        Please confirm your booking:
              Name: John Smith
              Date: 2026-12-30 14:00
              Service: Factory Automation
            Reply 'yes' to confirm, or 'no' to cancel.
Customer:   yes
Bot:        ✅ Your booking is confirmed! ...
```

Supported behaviours:

- **Validation** — unparseable/past dates and unknown services are rejected with
  a helpful reprompt; the state is preserved.
- **Corrections** — at the confirmation step the customer can say "change the
  service/date/name" and only that field is re-collected.
- **Cancel** — "cancel" / "never mind" ends the booking.
- **Restart** — "start over" restarts from the name step.
- **Business isolation** — services, FAQs, and leads are scoped to a single
  business; one tenant never sees another's data.

Free-form questions (e.g. "What are your opening hours?") are routed to
`AIService`, which answers using the configured business context and FAQs
(`services/context_builder.py`) — no business data is hard-coded in the webhook.

## Current MVP limitations

- Conversation state is in-memory per process (not durable; not shared across
  replicas). A restart clears in-progress bookings.
- The webhook maps all inbound traffic to the default business; per-number
  tenant routing is not implemented yet.
- The `/leads` dashboard is unauthenticated and shows all businesses' bookings —
  suitable for local/demo use only. Protect it (and scope it per tenant) before
  production.
- SQLite is the default store; migrations are minimal.
- Live OpenAI and live Twilio delivery require real credentials and have not been
  validated against the real services in this environment.
