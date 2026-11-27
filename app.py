# AI Receptionist Flask App
# Handles WhatsApp messages using Twilio and OpenAI

from dotenv import load_dotenv

# Load .env before importing modules that read configuration at import time (e.g. DATABASE_URL).
load_dotenv()

import datetime  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402
from flask import Flask, render_template_string, request  # noqa: E402
from twilio.request_validator import RequestValidator  # noqa: E402
from twilio.rest import Client  # noqa: E402
from twilio.twiml.messaging_response import MessagingResponse  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

from database import init_database  # noqa: E402
from routes.admin import admin_bp  # noqa: E402
from routes.auth import admin_required  # noqa: E402
from services.ai_service import AIService  # noqa: E402
from services.booking_flow import BookingFlow, START_PROMPT  # noqa: E402
from services.booking_service import BookingService  # noqa: E402
from services.business_service import BusinessService  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("receptionist")


def env_flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# -----------------------------
# Configuration
# -----------------------------
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886"))
OWNER_PHONE_NUMBER = os.getenv("OWNER_PHONE_NUMBER")
# Public URL Twilio calls (e.g. https://abc.ngrok-free.app). Used for signature checks behind proxies.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
VALIDATE_TWILIO_SIGNATURE = env_flag("TWILIO_VALIDATE_SIGNATURE", True)

missing_env = [name for name, value in {
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
}.items() if not value]
if missing_env:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing_env)}")

app = Flask(__name__)
# Trust one proxy hop (ngrok, Render, Railway, nginx) so request.url keeps the public https scheme/host.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.register_blueprint(admin_bp)

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
validator = RequestValidator(TWILIO_AUTH_TOKEN)

init_database()
ai_service = AIService()


def current_business():
    """Resolve the default tenant afresh so admin edits apply immediately."""
    return BusinessService.get_default_business()


def to_channel_address(number: str) -> str:
    """Match a bare phone number to the channel of the sending number (WhatsApp vs SMS)."""
    number = number.strip()
    if TWILIO_PHONE_NUMBER.startswith("whatsapp:") and not number.startswith("whatsapp:"):
        digits = "".join(ch for ch in number if ch.isdigit() or ch == "+")
        return f"whatsapp:{digits if digits.startswith('+') else '+' + digits}"
    return number


def send_message(to: str, body: str) -> bool:
    try:
        client.messages.create(from_=TWILIO_PHONE_NUMBER, body=body, to=to_channel_address(to))
        return True
    except Exception:
        logger.exception("Failed to send message to %s", to)
        return False


# -----------------------------
# Owner notification
# -----------------------------
def notify_owner(business, booking) -> None:
    owner_phone = business.owner_phone or OWNER_PHONE_NUMBER
    logger.info("New booking id=%s business_id=%s", booking.id, business.id)
    if not owner_phone:
        logger.warning("Owner notification skipped: no owner phone configured.")
        return
    text = (
        "📩 New booking request!\n\n"
        f"Name: {booking.customer.name}\n"
        f"Phone: {booking.customer.phone.removeprefix('whatsapp:')}\n"
        f"Date: {booking.appointment_at:%Y-%m-%d %H:%M}\n"
        f"Service: {booking.service}"
    )
    if send_message(owner_phone, text):
        logger.info("Owner notified for booking id=%s", booking.id)


booking_flow = BookingFlow(on_booking_created=notify_owner)


# -----------------------------
# Message routing
# -----------------------------
def handle_message(message: str, sender: str) -> str:
    """Continue an open booking, otherwise answer via the AI service."""
    business = current_business()
    message = (message or "").strip()

    if business.booking_enabled:
        reply = booking_flow.handle(business, sender, message)
        if reply is not None:
            ai_service.record_booking_exchange(business.id, sender, message, reply)
            return reply

    result = ai_service.respond(
        business.id, sender, message,
        booking_enabled=business.booking_enabled,
        booking_prompt=START_PROMPT,
    )
    if result.action == "start_booking":
        booking_flow.start(business, sender)
    return result.message


def is_valid_twilio_request() -> bool:
    if not VALIDATE_TWILIO_SIGNATURE:
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    url = request.url
    if PUBLIC_BASE_URL:
        url = PUBLIC_BASE_URL + request.full_path.rstrip("?")
    return validator.validate(url, request.form.to_dict(), signature)


# -----------------------------
# WhatsApp webhook
# -----------------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    if not is_valid_twilio_request():
        logger.warning("Rejected webhook with invalid Twilio signature for url=%s", request.url)
        return "Invalid request", 403

    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "").strip()
    if not sender:
        return "Sender number is required", 400

    resp = MessagingResponse()
    if not incoming_msg:
        resp.message("Sorry, I can only read text messages at the moment. Please type your question.")
        return str(resp), 200, {"Content-Type": "application/xml"}

    try:
        reply = handle_message(incoming_msg, sender)
    except Exception:
        logger.exception("Unhandled error while processing message from %s", sender)
        reply = "Sorry, something went wrong on our side. A team member will get back to you."
    resp.message(reply)
    logger.info("Handled message from %s", sender)
    return str(resp), 200, {"Content-Type": "application/xml"}


# -----------------------------
# Leads dashboard
# -----------------------------
LEADS_TEMPLATE = """
<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bookings · {{ business.name }}</title>
<style>
 body{font-family:system-ui,sans-serif;margin:24px;color:#222}
 table{border-collapse:collapse;width:100%}
 th,td{border-bottom:1px solid #ddd;padding:8px 10px;text-align:left}
 th{background:#f5f5f5} .muted{color:#777}
</style></head><body>
<h1>Bookings · {{ business.name }}</h1>
<p class="muted">Times are in {{ business.timezone }}. {{ leads|length }} booking(s).</p>
<table>
 <tr><th>Appointment</th><th>Name</th><th>Phone</th><th>Service</th><th>Reminder sent</th><th>Requested (UTC)</th></tr>
 {% for lead in leads %}
 <tr><td>{{ lead.date }}</td><td>{{ lead.name }}</td><td>{{ lead.phone }}</td><td>{{ lead.service }}</td>
     <td>{{ "yes" if lead.reminder_sent else "no" }}</td><td>{{ lead.created }}</td></tr>
 {% else %}
 <tr><td colspan="6" class="muted">No bookings yet.</td></tr>
 {% endfor %}
</table></body></html>
"""


@app.route("/leads")
@admin_required
def view_leads():
    business = current_business()
    leads = [
        {
            "name": booking.customer.name,
            "phone": booking.customer.phone.removeprefix("whatsapp:"),
            "date": booking.appointment_at.strftime("%Y-%m-%d %H:%M"),
            "service": booking.service,
            "reminder_sent": booking.reminder_sent,
            "created": booking.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for booking in BookingService.list_bookings(business.id)
    ]
    return render_template_string(LEADS_TEMPLATE, leads=leads, business=business)


# -----------------------------
# Reminders
# -----------------------------
def send_reminders() -> None:
    for booking in BookingService.bookings_due_for_reminder():
        text = (
            f"Hello {booking.customer.name}, this is a reminder of your {booking.service} "
            f"appointment with {booking.business.name} on {booking.appointment_at:%Y-%m-%d at %H:%M}."
        )
        if send_message(booking.customer.phone, text):
            BookingService.mark_reminder_sent(booking.id)
            logger.info("Reminder sent for booking id=%s", booking.id)


@app.route("/")
def home():
    return "WhatsApp Receptionist Bot Running"


@app.route("/health")
def health():
    return {"status": "ok"}


scheduler = BackgroundScheduler(timezone="UTC")


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.add_job(
            send_reminders, "interval",
            minutes=int(os.getenv("REMINDER_INTERVAL_MINUTES", "15")),
            next_run_time=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10),
            id="send_reminders", replace_existing=True,
        )
        scheduler.start()
        logger.info("Reminder scheduler started")


# Start reminders under any server (python app.py or gunicorn). Run a single gunicorn worker
# (use --threads for concurrency) or set RUN_SCHEDULER=false on all but one process.
if env_flag("RUN_SCHEDULER", True):
    start_scheduler()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=env_flag("FLASK_DEBUG", False),
        use_reloader=False,
    )
