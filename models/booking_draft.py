"""In-progress booking conversation state, persisted so restarts and multiple workers are safe."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class BookingDraft(Base):
    """One open booking conversation per customer phone per business."""

    __tablename__ = "booking_drafts"
    __table_args__ = (UniqueConstraint("business_id", "phone", name="uq_booking_draft_business_phone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(160))
    appointment_at: Mapped[datetime | None] = mapped_column(DateTime)
    service: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
