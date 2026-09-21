# AI Receptionist Flask App
# Handles WhatsApp messages using Twilio and OpenAI

from flask import Flask, g, request, render_template, url_for
from flask_wtf import CSRFProtect
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import os
import time
import datetime
import logging

from config import apply_config
from database import init_database
from services.booking_service import BookingService
from services.business_service import BusinessService
from services.ai_service import AIService
from services.conversation_service import ConversationService
from services.jobs import enqueue_owner_notification, enqueue_booking_reminder
from services.logging_setup import configure_logging
from services.observability import init_sentry
from routes.admin import admin_bp
from routes.auth import auth_bp, login_required, login_rate_limiter
from routes.dashboard import dashboard_bp
from routes.ops import ops_bp

load_dotenv()
configure_logging()
init_sentry()
logger = logging.getLogger(__name__)
app = Flask(__name__)

# Environment-aware config (debug, session/cookie hardening, CSRF, secret key).
apply_config(app)

# CSRF protection for browser/session forms. The Twilio webhook and the JSON
# admin API (session- or API-key-authenticated machine clients) are exempted
# below so they keep their own auth mechanisms.
csrf = CSRFProtect(app)

app.register_blueprint(ops_bp)
csrf.exempt(ops_bp)
app.register_blueprint(admin_bp)
csrf.exempt(admin_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)

# -----------------------------
# Twilio credentials (for webhook signature validation)
# -----------------------------
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

missing_env = [name for name, value in {
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
}.items() if not value]
if missing_env:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing_env)}")

validator = RequestValidator(TWILIO_AUTH_TOKEN)

# -----------------------------
# Database initialisation
# -----------------------------
init_database()


def notify_owner(business, booking):
    """Hand owner notification to the background job system (never blocks booking).

    The booking is already persisted at this point; enqueue failures are logged
    but never propagate, so a customer's booking never depends on notification.
    """
    outcome = enqueue_owner_notification(booking.id)
    logger.info(
        "Owner notification dispatched",
        extra={"event": "owner_notify_dispatch", "booking_id": booking.id,
               "business_id": business.id, "outcome": outcome},
    )


# The conversation service owns the booking finite-state machine and AI routing.
conversation_service = ConversationService(
    ai_service=AIService(),
    notifier=notify_owner,
)


# -----------------------------
# Twilio request validation
# -----------------------------
def is_valid_twilio_request():
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    params = {k: v for k, v in request.form.items()}
    return validator.validate(request.url, params, signature)


def _mask(sender: str) -> str:
    """Mask a phone/identifier for logging so we never log full customer numbers."""
    if not sender:
        return "<unknown>"
    tail = sender[-4:]
    return f"***{tail}"


# -----------------------------
# Request/performance logging
# -----------------------------
@app.before_request
def _start_timer():
    g._start_time = time.perf_counter()


@app.after_request
def _log_request(response):
    start = getattr(g, "_start_time", None)
    latency_ms = round((time.perf_counter() - start) * 1000, 1) if start is not None else None
    # Structured request log — no bodies, no PII beyond a masked business id.
    logger.info(
        "request completed",
        extra={
            "event": "request",
            "method": request.method,
            "path": request.path,
            "status": response.status_code,
            "latency_ms": latency_ms,
            "business_id": getattr(g, "business_id", None),
        },
    )
    return response


# -----------------------------
# WhatsApp webhook
# -----------------------------
@app.route("/whatsapp", methods=["POST"])
@csrf.exempt
def whatsapp():
    if not is_valid_twilio_request():
        return "Invalid request", 403

    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "").strip()
    recipient = request.values.get("To", "").strip()
    if not incoming_msg:
        return "Message body is required", 400
    if not sender:
        return "Sender number is required", 400

    # Route to the business that owns the inbound number. Never fall back to
    # another tenant when the number is unknown or missing.
    business = BusinessService.get_by_whatsapp_number(recipient) if recipient else None
    if business is None:
        logger.warning("Inbound WhatsApp to unrecognized number %s from %s", _mask(recipient), _mask(sender))
        resp = MessagingResponse()
        resp.message("Sorry, we couldn't match this number to a business. Please double-check and try again.")
        return str(resp)

    g.business_id = business.id
    reply = conversation_service.handle(business.id, sender, incoming_msg)
    resp = MessagingResponse()
    resp.message(reply)
    logger.info(
        "Handled inbound WhatsApp",
        extra={"event": "whatsapp_inbound", "business_id": business.id, "outcome": "handled"},
    )
    return str(resp)


# -----------------------------
# Leads dashboard
# -----------------------------
@app.route("/leads")
@login_required
def view_leads(admin):
    business = BusinessService.get_business(admin.business_id)
    leads = [
        {
            "name": booking.customer.name,
            "phone": booking.customer.phone,
            "date": booking.appointment_at.strftime("%Y-%m-%d %H:%M"),
            "message": booking.service,
            "time": booking.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for booking in BookingService.list_bookings(admin.business_id)
    ]
    return render_template("leads.html", admin=admin, business=business, leads=leads)

# -----------------------------
# Reminders (foundation)
# -----------------------------
def enqueue_due_reminders():
    """Find bookings due for a reminder and hand each to the job system.

    Actual delivery happens in the durable `send_booking_reminder` job and
    depends on live Twilio credentials.
    """
    now = datetime.datetime.now()
    for booking in BookingService.bookings_due_for_reminder(now):
        enqueue_booking_reminder(booking.id)


@app.route("/")
def home():
    return "WhatsApp Receptionist Bot Running"


scheduler = BackgroundScheduler()

def start_scheduler():
    """Dev-only in-process scheduler. Under Gunicorn use a dedicated worker/beat
    so reminders are not scheduled once per web worker."""
    if not scheduler.running:
        scheduler.add_job(enqueue_due_reminders, "interval", minutes=60,
                          next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10))
        scheduler.start()


if __name__ == "__main__":
    start_scheduler()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False,
    )
