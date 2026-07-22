"""Business tenant model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Business(Base):
    """A business that owns its customers, bookings, and knowledge."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(120))
    owner_name: Mapped[str | None] = mapped_column(String(160))
    owner_phone: Mapped[str | None] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    booking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    booking_duration: Mapped[int] = mapped_column(default=60, nullable=False)
    website_chat_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opening_hours: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    customers = relationship("Customer", back_populates="business")
    bookings = relationship("Booking", back_populates="business")
    conversations = relationship("Conversation", back_populates="business")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="business")
    services = relationship("Service", back_populates="business", cascade="all, delete-orphan")
    faqs = relationship("FAQ", back_populates="business", cascade="all, delete-orphan")
