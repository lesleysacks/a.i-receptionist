"""Add processed_webhooks for Twilio MessageSid idempotency.

Revision ID: c4a1e9d2b7f0
Revises: 379ee94dc59e
Create Date: 2026-11-03
"""

from alembic import op
import sqlalchemy as sa

revision = "c4a1e9d2b7f0"
down_revision = "379ee94dc59e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_webhooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_message_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "provider_message_id", name="uq_processed_webhook"),
    )
    op.create_index("ix_processed_webhooks_provider_message_id", "processed_webhooks", ["provider_message_id"])


def downgrade() -> None:
    op.drop_index("ix_processed_webhooks_provider_message_id", table_name="processed_webhooks")
    op.drop_table("processed_webhooks")
