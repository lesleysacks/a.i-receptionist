"""Idempotency records for provider webhook deliveries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ProcessedWebhook(Base):
    """A provider message id that has already been handled.

    Used to ignore Twilio retries of the same MessageSid so a duplicate
    delivery cannot create a second booking.
    """

    __tablename__ = "processed_webhooks"
    __table_args__ = (UniqueConstraint("provider", "provider_message_id", name="uq_processed_webhook"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="twilio", nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
