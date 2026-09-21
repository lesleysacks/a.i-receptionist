"""Conversation orchestration for the WhatsApp receptionist.

Implements a small, explicit finite-state machine for the booking flow and
delegates free-form questions to the AI seam. All customer-facing failures are
converted into safe, friendly messages; internal errors are logged for
developers but never surfaced to the customer.
"""

from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

from services import validators
from services.ai_service import AIService
from services.booking_service import BookingService
from services.business_service import BusinessService, NotFoundError

logger = logging.getLogger(__name__)

# Conversation states for the booking flow.
IDLE = "idle"
ASK_NAME = "ask_name"
ASK_DATE = "ask_date"
ASK_SERVICE = "ask_service"
CONFIRM = "confirm"

SAFE_ERROR_MESSAGE = (
    "Sorry, something went wrong on our side. Please try again in a moment."
)
NOT_CONFIGURED_MESSAGE = (
    "Thanks for your message! This service isn't fully set up yet. "
    "Please try again later."
)
DATE_FORMAT = "%Y-%m-%d %H:%M"


@dataclass
class _State:
    step: str = IDLE
    name: str | None = None
    appointment_at: datetime.datetime | None = None
    service: str | None = None
    updated: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def reset(self) -> None:
        self.step = IDLE
        self.name = None
        self.appointment_at = None
        self.service = None
        self.touch()

    def touch(self) -> None:
        self.updated = datetime.datetime.now(datetime.timezone.utc).isoformat()


class ConversationService:
    """Route inbound messages through the booking FSM or the AI seam."""

    def __init__(
        self,
        ai_service: AIService | None = None,
        state_store: dict | None = None,
        notifier: Callable[[object, object], None] | None = None,
    ) -> None:
        self.ai_service = ai_service or AIService()
        self._states: dict[tuple[int, str], _State] = state_store if state_store is not None else {}
        self._lock = threading.Lock()
        self.notifier = notifier

    # -- public API ---------------------------------------------------------
    def handle(self, business_id: int, sender: str, message: str) -> str:
        """Return a customer-facing reply, never raising to the caller."""
        if not sender:
            return "Sorry, I couldn't read your number. Please try sending your message again."
        try:
            reply, already_recorded = self._process(business_id, sender, message)
            if not already_recorded:
                self._safe_record(business_id, sender, message, reply)
            return reply
        except NotFoundError:
            logger.warning("Business %s is not configured", business_id)
            return NOT_CONFIGURED_MESSAGE
        except Exception:
            logger.exception("Unhandled error while handling message for business_id=%s", business_id)
            return SAFE_ERROR_MESSAGE

    # -- state helpers ------------------------------------------------------
    def _get_state(self, business_id: int, sender: str) -> _State:
        with self._lock:
            key = (business_id, sender)
            state = self._states.get(key)
            if state is None:
                state = _State()
                self._states[key] = state
            return state

    # -- core dispatch ------------------------------------------------------
    def _process(self, business_id: int, sender: str, message: str) -> tuple[str, bool]:
        message = (message or "").strip()
        if not message:
            return "Sorry, I didn't catch that. Could you send your message again?", False

        business = BusinessService.get_business(business_id)
        state = self._get_state(business_id, sender)

        # Global commands available at any point in an active booking.
        if state.step != IDLE and validators.is_cancel(message):
            state.reset()
            return (
                "No problem \u2014 I've cancelled that booking. "
                "Message me any time to start again.",
                False,
            )

        if validators.is_restart(message):
            if not business.booking_enabled:
                return self._booking_disabled_reply(), False
            state.reset()
            state.step = ASK_NAME
            state.touch()
            return "Sure, let's start over. What name should the booking be under?", False

        if state.step == IDLE:
            return self._handle_idle(business, business_id, sender, message)
        if state.step == ASK_NAME:
            return self._handle_name(business_id, state, message)
        if state.step == ASK_DATE:
            return self._handle_date(business_id, state, message)
        if state.step == ASK_SERVICE:
            return self._handle_service(business, business_id, state, message)
        if state.step == CONFIRM:
            return self._handle_confirm(business, business_id, sender, state, message)

        # Defensive: an unexpected state should never strand the customer.
        logger.error("Unexpected conversation state %r for business_id=%s", state.step, business_id)
        state.reset()
        return SAFE_ERROR_MESSAGE, False

    # -- individual steps ---------------------------------------------------
    def _handle_idle(self, business, business_id: int, sender: str, message: str) -> tuple[str, bool]:
        if business.booking_enabled and validators.is_booking_intent(message):
            state = self._get_state(business_id, sender)
            state.step = ASK_NAME
            state.touch()
            return "Happy to help you book! What name should the booking be under?", False

        # Free-form question: delegate to the AI seam (records the exchange itself).
        result = self.ai_service.respond(business_id, sender, message)
        if result.action == "start_booking" and business.booking_enabled:
            state = self._get_state(business_id, sender)
            state.step = ASK_NAME
            state.touch()
        return result.message, True

    def _handle_name(self, business_id: int, state: _State, message: str) -> tuple[str, bool]:
        name = message.strip()
        if len(name) > 120:
            return "That name looks a little long \u2014 could you share a shorter version?", False
        state.name = name
        state.step = ASK_DATE
        state.touch()
        return (
            f"Thanks, {name}! What date and time would you like? "
            "For example: 2026-09-30 14:00.",
            False,
        )

    def _handle_date(self, business_id: int, state: _State, message: str) -> tuple[str, bool]:
        parsed = validators.parse_datetime(message)
        if parsed is None:
            return (
                "I couldn't read that date. Please use a format like "
                "2026-09-30 14:00 or 30/09/2026 14:00.",
                False,
            )
        if parsed < datetime.datetime.now():
            return (
                "That date is in the past. Please share a future date and time, "
                "for example 2026-09-30 14:00.",
                False,
            )
        state.appointment_at = parsed
        state.step = ASK_SERVICE
        state.touch()
        return f"Great. {self._service_prompt(business_id)}", False

    def _handle_service(self, business, business_id: int, state: _State, message: str) -> tuple[str, bool]:
        names = self._active_service_names(business_id)
        if names:
            matched = validators.match_service(message, names)
            if matched is None:
                return (
                    "I couldn't find that service. "
                    f"{self._service_prompt(business_id)}",
                    False,
                )
            service = matched
        else:
            # No catalogue configured yet: accept the free-text service.
            service = message.strip()
        state.service = service
        state.step = CONFIRM
        state.touch()
        return self._summary(state), False

    def _handle_confirm(self, business, business_id: int, sender: str, state: _State, message: str) -> tuple[str, bool]:
        if validators.wants_change_service(message):
            state.step = ASK_SERVICE
            state.touch()
            return f"Sure \u2014 {self._service_prompt(business_id)}", False
        if validators.wants_change_date(message):
            state.step = ASK_DATE
            state.touch()
            return "No problem \u2014 what date and time works for you? e.g. 2026-09-30 14:00.", False
        if validators.wants_change_name(message):
            state.step = ASK_NAME
            state.touch()
            return "Sure \u2014 what name should I use for the booking?", False
        if validators.is_affirmative(message):
            return self._finalise_booking(business, business_id, sender, state)
        if validators.is_negative(message) or validators.is_cancel(message):
            state.reset()
            return (
                "Okay, I won't book that. Let me know if you'd like to try again.",
                False,
            )
        return (
            "Sorry, I didn't quite catch that. Reply 'yes' to confirm, 'no' to cancel, "
            "or tell me if you'd like to change the name, date, or service.",
            False,
        )

    def _finalise_booking(self, business, business_id: int, sender: str, state: _State) -> tuple[str, bool]:
        if not (state.name and state.appointment_at and state.service):
            logger.error("Confirm reached with incomplete state for business_id=%s", business_id)
            state.reset()
            return (
                "Something was missing from that booking. Let's try again \u2014 "
                "what name should the booking be under?",
                False,
            )
        booking = BookingService.create_booking(
            business_id,
            state.name,
            state.appointment_at,
            sender,
            state.service,
        )
        confirmed = self._confirmation(state)
        logger.info(
            "Booking %s created for business_id=%s (service=%s)",
            booking.id,
            business_id,
            state.service,
        )
        self._notify(business, booking)
        state.reset()
        return confirmed, False

    # -- messaging helpers --------------------------------------------------
    def _active_service_names(self, business_id: int) -> list[str]:
        return [service.name for service in BusinessService.get_services(business_id, active_only=True)]

    def _service_prompt(self, business_id: int) -> str:
        names = self._active_service_names(business_id)
        if names:
            return "Which service would you like to book? We offer: " + ", ".join(names) + "."
        return "Which service would you like to book?"

    def _summary(self, state: _State) -> str:
        return (
            "Please confirm your booking:\n\n"
            f"Name: {state.name}\n"
            f"Date: {state.appointment_at.strftime(DATE_FORMAT)}\n"
            f"Service: {state.service}\n\n"
            "Reply 'yes' to confirm, or 'no' to cancel."
        )

    def _confirmation(self, state: _State) -> str:
        return (
            "\u2705 Your booking is confirmed!\n\n"
            f"Name: {state.name}\n"
            f"Date: {state.appointment_at.strftime(DATE_FORMAT)}\n"
            f"Service: {state.service}\n\n"
            "A consultant will be in touch. Message me any time if you need changes."
        )

    def _booking_disabled_reply(self) -> str:
        return "Bookings aren't available right now, but I'm happy to answer any questions."

    # -- side effects (guarded) --------------------------------------------
    def _notify(self, business, booking) -> None:
        if self.notifier is None:
            return
        try:
            self.notifier(business, booking)
        except Exception:
            logger.exception("Owner notification failed for booking_id=%s", getattr(booking, "id", "?"))

    def _safe_record(self, business_id: int, sender: str, message: str, reply: str) -> None:
        try:
            self.ai_service.record_booking_exchange(business_id, sender, message, reply)
        except Exception:
            logger.exception("Failed to record conversation for business_id=%s", business_id)
