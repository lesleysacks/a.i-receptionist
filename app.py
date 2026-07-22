# AI Receptionist Flask App
# Handles WhatsApp messages using Twilio and OpenAI

from flask import Flask, request, render_template_string
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import os
import datetime
import logging

from database import init_database
from services.booking_service import BookingService
from services.business_service import BusinessService
from services.ai_service import AIService
from routes.admin import admin_bp

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = Flask(__name__)
app.register_blueprint(admin_bp)

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
users = {}

# -----------------------------
# Database initialisation
# -----------------------------
init_database()
ai_service = AIService()


def current_business():
    """Resolve the default tenant afresh so admin edits apply immediately."""
    return BusinessService.get_default_business()

# -----------------------------
# Twilio request validation
# -----------------------------
def is_valid_twilio_request():
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    params = {k: v for k, v in request.form.items()}
    return validator.validate(request.url, params, signature)

# -----------------------------
# Booking helpers
# -----------------------------
def parse_datetime(value):
    value = value.strip()
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M %p",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %I:%M %p",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            parsed = datetime.datetime.strptime(value, fmt)
            if fmt in ["%Y-%m-%d", "%d/%m/%Y"]:
                return parsed.replace(hour=9, minute=0)
            return parsed
        except ValueError:
            continue
    return None


def reset_user(sender):
    users[sender] = {"step": "start", "updated": datetime.datetime.now().isoformat()}


def save_booking(name, date, phone, message):
    booking = BookingService.create_booking(
        current_business().id,
        name,
        datetime.datetime.strptime(date, "%Y-%m-%d %H:%M"),
        phone,
        message,
    )
    lead = {
        "name": booking.customer.name,
        "date": booking.appointment_at.strftime("%Y-%m-%d %H:%M"),
        "phone": booking.customer.phone,
        "message": booking.service,
        "time": booking.created_at.strftime("%Y-%m-%d %H:%M"),
    }
    print("NEW LEAD:", lead)
    notify_owner(lead, current_business().owner_phone or OWNER_PHONE_NUMBER)


def notify_owner(lead, owner_phone):
    if not owner_phone:
        print("Owner notification skipped: no owner phone number is configured.")
        return
    text = f"""
📩 New WhatsApp Booking!

Name: {lead['name']}
Phone: {lead['phone']}
Date: {lead['date']}
Service: {lead['message']}
Time: {lead['time']}
"""
    try:
        client.messages.create(
            from_=TWILIO_PHONE_NUMBER,
            body=text,
            to=owner_phone,
        )
        print("Owner notified ✅")
    except Exception as exc:
        print("Failed to notify owner:", exc)


def ai_generate(message, sender):
    """Route booking-form messages or free-form questions through AIService."""
    if not sender:
        return "Unable to read your phone number. Please send your message again."
    message = (message or "").strip()
    if sender not in users:
        reset_user(sender)

    step = users[sender]["step"]
    if step == "ask_name":
        users[sender]["name"] = message
        users[sender]["step"] = "ask_date"
        reply = f"Thanks {message}! What date would you like to book? (e.g. 2025-09-30 14:30)"
        ai_service.record_booking_exchange(current_business().id, sender, message, reply)
        return reply

    if step == "ask_date":
        parsed_date = parse_datetime(message)
        if not parsed_date:
            reply = "Please send a valid date and time in one of these formats: YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM."
            ai_service.record_booking_exchange(current_business().id, sender, message, reply)
            return reply
        users[sender]["date"] = parsed_date.strftime("%Y-%m-%d %H:%M")
        users[sender]["step"] = "ask_service"
        reply = "Great. What service do you need for your booking?"
        ai_service.record_booking_exchange(current_business().id, sender, message, reply)
        return reply

    if step == "ask_service":
        users[sender]["service"] = message
        save_booking(users[sender]["name"], users[sender]["date"], sender, message)
        users[sender]["step"] = "done"
        reply = f"""
✅ Booking request received!

Name: {users[sender]['name']}
Date: {users[sender]['date']}
Service: {message}

A consultant will contact you shortly.
"""
        ai_service.record_booking_exchange(current_business().id, sender, message, reply)
        return reply

    result = ai_service.respond(current_business().id, sender, message)
    if result.action == "start_booking" and current_business().booking_enabled:
        reset_user(sender)
        users[sender]["step"] = "ask_name"
    return result.message

# -----------------------------
# WhatsApp webhook
# -----------------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    if not is_valid_twilio_request():
        return "Invalid request", 403

    incoming_msg = request.values.get("Body", "").strip()
    sender = request.values.get("From", "").strip()
    if not incoming_msg:
        return "Message body is required", 400
    if not sender:
        return "Sender number is required", 400

    reply = ai_generate(incoming_msg, sender)
    resp = MessagingResponse()
    resp.message(reply)
    print(f"{sender}: {incoming_msg} -> {reply}")
    return str(resp)

# -----------------------------
# Leads dashboard
# -----------------------------
@app.route("/leads")
def view_leads():
    html = """
    <h1>WhatsApp Leads Dashboard</h1>
    <table border="1" cellpadding="10">
        <tr>
            <th>Name</th>
            <th>Phone</th>
            <th>Date</th>
            <th>Service</th>
            <th>Time</th>
        </tr>
        {% for lead in leads %}
        <tr>
            <td>{{ lead.name }}</td>
            <td>{{ lead.phone }}</td>
            <td>{{ lead.date }}</td>
            <td>{{ lead.message }}</td>
            <td>{{ lead.time }}</td>
        </tr>
        {% endfor %}
    </table>
    """
    leads = [
        {
            "name": booking.customer.name,
            "phone": booking.customer.phone,
            "date": booking.appointment_at.strftime("%Y-%m-%d %H:%M"),
            "message": booking.service,
            "time": booking.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for booking in BookingService.list_bookings()
    ]
    return render_template_string(html, leads=leads)

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
            print(f"Reminder sent to {booking.customer.name} ✅")
        except Exception as exc:
            print("Failed to send reminder:", exc)


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
