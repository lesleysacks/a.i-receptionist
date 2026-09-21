# AI Receptionist Flask App
# Handles WhatsApp messages using Twilio and OpenAI

from flask import Flask, request, render_template, url_for
from flask_wtf import CSRFProtect
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import os
import datetime
import logging

from config import apply_config
from database import init_database
from services.booking_service import BookingService
from services.business_service import BusinessService
from services.ai_service import AIService
from services.conversation_service import ConversationService
from routes.admin import admin_bp
from routes.auth import auth_bp, login_required, login_rate_limiter
from routes.dashboard import dashboard_bp

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# Environment-aware config (debug, session/cookie hardening, CSRF, secret key).
apply_config(app)

# CSRF protection for browser/session forms. The Twilio webhook and the JSON
# admin API (session- or API-key-authenticated machine clients) are exempted
# below so they keep their own auth mechanisms.
csrf = CSRFProtect(app)

app.register_blueprint(admin_bp)
csrf.exempt(admin_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)

# -----------------------------
# Twilio credentials
# -----------------------------
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886"))
OWNER_PHONE_NUMBER = os.getenv("OWNER_PHONE_NUMBER")

missing_env = [name for name, value in {
    "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
    "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
}.items() if not value]
if missing_env:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing_env)}")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
validator = RequestValidator(TWILIO_AUTH_TOKEN)

# -----------------------------
# Database initialisation
# -----------------------------
init_database()


def notify_owner(business, booking):
    """Send the owner a WhatsApp notification about a new booking."""
    owner_phone = business.owner_phone or OWNER_PHONE_NUMBER
    if not owner_phone:
        logger.info("Owner notification skipped: no owner phone configured for business_id=%s", business.id)
        return
    text = (
        "New WhatsApp booking\n\n"
        f"Name: {booking.customer.name}\n"
        f"Phone: {booking.customer.phone}\n"
        f"Date: {booking.appointment_at:%Y-%m-%d %H:%M}\n"
        f"Service: {booking.service}"
    )
    client.messages.create(from_=TWILIO_PHONE_NUMBER, body=text, to=owner_phone)
    logger.info("Owner notified for booking_id=%s", booking.id)


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

    reply = conversation_service.handle(business.id, sender, incoming_msg)
    resp = MessagingResponse()
    resp.message(reply)
    logger.info("Handled inbound WhatsApp for business_id=%s from %s", business.id, _mask(sender))
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
# Reminders
# -----------------------------
def send_reminders():
    now = datetime.datetime.now()
    for booking in BookingService.bookings_due_for_reminder(now):
        text = (
            f"Hello {booking.customer.name}, this is a reminder for your appointment on "
            f"{booking.appointment_at:%Y-%m-%d %H:%M} for {booking.service}."
        )
        try:
            client.messages.create(from_=TWILIO_PHONE_NUMBER, body=text, to=booking.customer.phone)
            BookingService.mark_reminder_sent(booking.id)
            logger.info("Reminder sent for booking_id=%s", booking.id)
        except Exception:
            logger.exception("Failed to send reminder for booking_id=%s", booking.id)


@app.route("/")
def home():
    return "WhatsApp Receptionist Bot Running"


scheduler = BackgroundScheduler()

def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(send_reminders, "interval", minutes=60, next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10))
        scheduler.start()


if __name__ == "__main__":
    start_scheduler()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False,
    )
