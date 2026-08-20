"""Notification outbox for Knowledge Request routing.

Revision ID: 0003_notifications
Revises: 0002_bot_conversations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from api.models.types import GUID, JSONDict

revision = "0003_notifications"
down_revision = "0002_bot_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("person_id", GUID(), sa.ForeignKey("people.id")),
        sa.Column("team_id", GUID(), sa.ForeignKey("teams.id")),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("payload", JSONDict(), server_default="{}"),
        sa.Column("status", sa.String(16), server_default="pending"),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_notifications_status", "notifications", ["status"])


def downgrade() -> None:
    op.drop_table("notifications")
