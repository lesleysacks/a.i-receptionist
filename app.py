# AI Receptionist Flask App
# Handles WhatsApp messages using Twilio and OpenAI

from flask import Flask, g, request, render_template
from flask_wtf import CSRFProtect
from twilio.twiml.messaging_response import MessagingResponse
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException
import os
import time
import datetime
import logging

from apex.setup_django import setup_django
from config import apply_config
from database import get_session, init_database
from services.booking_service import BookingService
from services.business_service import BusinessService
from services.ai_service import AIService
from services.conversation_service import ConversationService
from services.jobs import enqueue_owner_notification, enqueue_booking_reminder
from services.logging_setup import configure_logging
from services.observability import init_sentry
from apex_receptionist.adapters.twilio_webhook import is_valid_twilio_signature
from apex_receptionist.models.processed_webhook import ProcessedWebhook

# Blueprints import Django models. Load .env then initialise Django before
# those imports so production host validation runs at boot and the app
# registry is ready (Gunicorn `wsgi:app` does not go through tests/conftest).
load_dotenv()
setup_django()

from routes.admin import admin_bp  # noqa: E402
from routes.auth import auth_bp, login_required, login_rate_limiter  # noqa: E402
from routes.dashboard import dashboard_bp  # noqa: E402
from routes.ops import ops_bp  # noqa: E402

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
    return is_valid_twilio_signature(request, TWILIO_AUTH_TOKEN, path="/whatsapp")


def _mask(sender: str) -> str:
    """Mask a phone/identifier for logging so we never log full customer numbers."""
    if not sender:
        return "<unknown>"
    tail = sender[-4:]
    return f"***{tail}"


def _already_processed(message_sid: str) -> bool:
    if not message_sid:
        return False
    with get_session() as session:
        found = session.scalar(
            select(ProcessedWebhook.id).where(
                ProcessedWebhook.provider == "twilio",
                ProcessedWebhook.provider_message_id == message_sid,
            )
        )
        return found is not None


def _mark_processed(message_sid: str) -> None:
    if not message_sid:
        return
    try:
        with get_session() as session:
            session.add(ProcessedWebhook(provider="twilio", provider_message_id=message_sid))
    except IntegrityError:
        return


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


@app.errorhandler(Exception)
def _unexpected_error(exc):
    if isinstance(exc, HTTPException):
        return exc
    logger.exception("Unhandled application error")
    return "An unexpected error occurred.", 500


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
    message_sid = (request.values.get("MessageSid") or "").strip()
    if not incoming_msg:
        return "Message body is required", 400
    if not sender:
        return "Sender number is required", 400
    if _already_processed(message_sid):
        return str(MessagingResponse())

    # Route to the business that owns the inbound number. Never fall back to
    # another tenant when the number is unknown or missing.
    business = BusinessService.get_by_whatsapp_number(recipient) if recipient else None
    if business is None:
        logger.warning("Inbound WhatsApp to unrecognized number %s from %s", _mask(recipient), _mask(sender))
        resp = MessagingResponse()
        resp.message("Sorry, we couldn't match this number to a business. Please double-check and try again.")
        _mark_processed(message_sid)
        return str(resp)

    g.business_id = business.id
    reply = conversation_service.handle(business.id, sender, incoming_msg)
    resp = MessagingResponse()
    resp.message(reply)
    _mark_processed(message_sid)
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

    Appointment times are stored naive-UTC-or-local as today; comparison uses
    timezone-aware UTC converted to naive UTC so reminder windows do not shift
    with the host timezone.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
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
                          next_run_time=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(seconds=10))
        scheduler.start()


if __name__ == "__main__":
    start_scheduler()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False,
    )
