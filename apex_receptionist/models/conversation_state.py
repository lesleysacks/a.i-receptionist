"""Durable booking conversation state, scoped per (business, sender).

Persisting the finite-state machine lets a conversation resume after an
application or process restart. Only the minimal fields needed to resume a
booking are stored (no free-form message history is kept here).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ConversationState(Base):
    """The current booking-flow state for one customer of one business."""

    __tablename__ = "conversation_states"
    __table_args__ = (
        UniqueConstraint("business_id", "sender", name="uq_convstate_business_sender"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True, nullable=False)
    sender: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    name: Mapped[str | None] = mapped_column(String(160))
    appointment_at: Mapped[datetime | None] = mapped_column(DateTime)
    service: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    business = relationship("Business")
