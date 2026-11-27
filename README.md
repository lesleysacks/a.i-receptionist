# AI Receptionist (WhatsApp) — v1

A WhatsApp receptionist for a small business. It answers customer questions using the business
details you configure, takes appointment requests, notifies the owner, and sends reminders.

## What it does

- **Answers questions** with OpenAI, using only the business info, services, prices and FAQs you configure
  (it hands off to a human instead of guessing).
- **Takes bookings** in a guided chat: name → date/time → service (pick from your list).
  Customers can reply `CANCEL` at any point. Progress is saved in the database, so restarts don't lose it.
- **Notifies the owner** on WhatsApp for every new booking.
- **Sends reminders** within 24 hours of each appointment, in the business's timezone.
- **Dashboard** of bookings at `/leads` (password protected).
- Works **without an OpenAI key** in a reduced mode: booking still works, other questions are handed off.

## 1. Install

Requires Python 3.10+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

## 2. Configure

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Notes |
|---|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | yes | Twilio Console dashboard |
| `TWILIO_WHATSAPP_NUMBER` | yes | e.g. `whatsapp:+14155238886` (sandbox) |
| `ADMIN_PASSWORD` | yes, for admin/dashboard | protects `/admin/*` and `/leads` |
| `OPENAI_API_KEY` | recommended | without it, only booking is automated |
| `OWNER_PHONE_NUMBER` | optional | fallback if `owner_phone` isn't set via the admin API |
| `PUBLIC_BASE_URL` | if behind a proxy | your public https URL, e.g. the ngrok URL |

## 3. Run

```
python app.py
```

For production use gunicorn with **one** worker (the reminder scheduler runs inside the process):

```
gunicorn -w 1 --threads 4 -b 0.0.0.0:5000 app:app
```

## 4. Connect Twilio

1. Expose the app over HTTPS. Locally: `ngrok http 5000`.
2. Twilio Console → Messaging → Try it out → WhatsApp sandbox → **When a message comes in**:
   `https://<your-public-host>/whatsapp` (method POST).
3. Set `PUBLIC_BASE_URL=https://<your-public-host>` in `.env` and restart.
   If you get `403 Invalid request`, this URL doesn't exactly match the one configured in Twilio.

## 5. Set up your business

All admin calls need the admin password (`-u admin:<ADMIN_PASSWORD>` or `Authorization: Bearer <ADMIN_PASSWORD>`).

```
curl -u admin:PASSWORD -X PUT http://localhost:5000/admin/business -H "Content-Type: application/json" -d "{\"name\":\"Acme Automation\",\"description\":\"PLC programming and factory automation\",\"opening_hours\":\"Mon-Fri 08:00-17:00\",\"phone\":\"+27000000000\",\"owner_phone\":\"+27000000000\",\"timezone\":\"Africa/Johannesburg\",\"currency\":\"ZAR\",\"city\":\"Wellington\"}"

curl -u admin:PASSWORD -X POST http://localhost:5000/admin/services -H "Content-Type: application/json" -d "{\"name\":\"PLC Programming\",\"price\":750,\"duration_minutes\":60}"

curl -u admin:PASSWORD -X POST http://localhost:5000/admin/faq -H "Content-Type: application/json" -d "{\"question\":\"Do you work weekends?\",\"answer\":\"Only for emergency call-outs.\"}"
```

| Endpoint | Methods | Purpose |
|---|---|---|
| `/admin/business` | GET, PUT | business profile, hours, timezone, owner phone, `booking_enabled` |
| `/admin/services` | GET, POST | services offered (shown as booking options) |
| `/admin/services/<id>` | PUT, DELETE | |
| `/admin/faq` | GET, POST | FAQs used by the AI |
| `/admin/faq/<id>` | PUT, DELETE | |
| `/leads` | GET | bookings dashboard (opens a browser login; any username) |
| `/whatsapp` | POST | Twilio webhook |
| `/health` | GET | health check |

## Tests

```
pip install -r requirements-dev.txt
pytest
```

## Known limitations of v1

- **One business per deployment.** The data model is multi-tenant, but messages always go to the first business.
- **Booking requests are not checked against availability** or opening hours. The owner confirms them manually.
- **WhatsApp 24-hour rule:** Twilio only delivers free-form messages (reminders, owner alerts) within 24h of that
  person's last message to you. For production, register approved message templates for reminders, and have the
  owner message the bot number once a day (or use SMS for owner alerts).
- SQLite is fine for one small business. Set `DATABASE_URL` to Postgres for anything bigger.
