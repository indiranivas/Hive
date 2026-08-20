"""Store Bot Framework conversation references for proactive messaging.

Revision ID: 0002_bot_conversations
Revises: 0001_initial
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from api.models.types import GUID, JSONDict

revision = "0002_bot_conversations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_conversations",
        sa.Column("person_id", GUID(), sa.ForeignKey("people.id"), primary_key=True),
        sa.Column("service_url", sa.String(512)),
        sa.Column("conversation_reference", JSONDict(), server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("bot_conversations")
