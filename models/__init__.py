"""Compatibility shims for SQLAlchemy models.

Canonical definitions live in ``apex_receptionist.models``.
"""

from apex_receptionist.models import *  # noqa: F403
from apex_receptionist.models import (  # noqa: F401
    AdminUser,
    Booking,
    Business,
    Conversation,
    ConversationState,
    Customer,
    FAQ,
    KnowledgeDocument,
    ProcessedWebhook,
    Service,
)

__all__ = [
    "Business",
    "Booking",
    "Conversation",
    "ConversationState",
    "Customer",
    "KnowledgeDocument",
    "Service",
    "FAQ",
    "AdminUser",
    "ProcessedWebhook",
]
