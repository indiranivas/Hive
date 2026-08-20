"""Initial Hive schema: people, teams, artifacts, expertise, KRs, statuses, logs.

Revision ID: 0001_initial
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from api.models.types import GUID, FloatArray, JSONDict, StringArray

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now()),
    )

    op.create_table(
        "teams",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("org_id", GUID(), sa.ForeignKey("orgs.id")),
        sa.Column("manager_id", GUID(), nullable=True),
        sa.Column("created_at", TS, server_default=sa.func.now()),
    )

    op.create_table(
        "people",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("azure_ad_id", sa.String(128), unique=True),
        sa.Column("email", sa.String(256), nullable=False, unique=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("team_id", GUID(), sa.ForeignKey("teams.id")),
        sa.Column("role", sa.String(32), server_default="member"),
        sa.Column("created_at", TS, server_default=sa.func.now()),
        sa.Column("updated_at", TS, server_default=sa.func.now()),
    )
    # Circular reference: teams.manager_id -> people.id, created after both tables.
    op.create_foreign_key("fk_teams_manager", "teams", "people", ["manager_id"], ["id"])

    op.create_table(
        "work_artifacts",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(512), nullable=False),
        sa.Column("author_id", GUID(), sa.ForeignKey("people.id")),
        sa.Column("team_id", GUID(), sa.ForeignKey("teams.id")),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", JSONDict(), server_default="{}"),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("ingested_at", TS, server_default=sa.func.now()),
        sa.UniqueConstraint("source", "source_id", name="uq_artifact_source"),
    )
    op.create_index("idx_artifacts_author", "work_artifacts", ["author_id"])
    op.create_index("idx_artifacts_team", "work_artifacts", ["team_id"])
    op.create_index("idx_artifacts_type", "work_artifacts", ["artifact_type"])
    op.create_index("idx_artifacts_occurred", "work_artifacts", ["occurred_at"])

    op.create_table(
        "expertise_scores",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("person_id", GUID(), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("topic", sa.String(256), nullable=False),
        sa.Column("score", sa.Float(), server_default="0"),
        sa.Column("evidence_count", sa.Integer(), server_default="0"),
        sa.Column("last_seen", TS),
        sa.Column("updated_at", TS, server_default=sa.func.now()),
        sa.UniqueConstraint("person_id", "topic", name="uq_expertise_person_topic"),
    )
    op.create_index("idx_expertise_topic", "expertise_scores", ["topic"])
    op.create_index("idx_expertise_score", "expertise_scores", ["score"])

    op.create_table(
        "knowledge_requests",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("requester_id", GUID(), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text()),
        sa.Column("status", sa.String(32), server_default="open"),
        sa.Column("routed_to_id", GUID(), sa.ForeignKey("people.id")),
        sa.Column("answer", sa.Text()),
        sa.Column("answered_by_id", GUID(), sa.ForeignKey("people.id")),
        sa.Column("answered_at", TS),
        sa.Column("tags", StringArray()),
        sa.Column("related_artifacts", StringArray()),
        sa.Column("created_at", TS, server_default=sa.func.now()),
        sa.Column("updated_at", TS, server_default=sa.func.now()),
    )
    op.create_index("idx_kr_status", "knowledge_requests", ["status"])

    op.create_table(
        "status_reports",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("person_id", GUID(), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("team_id", GUID(), sa.ForeignKey("teams.id")),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", JSONDict(), server_default="{}"),
        sa.Column("generated_at", TS, server_default=sa.func.now()),
        sa.UniqueConstraint("person_id", "period_start", "period_end", name="uq_status_period"),
    )

    op.create_table(
        "query_log",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("user_id", GUID(), sa.ForeignKey("people.id")),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text()),
        sa.Column("sources_used", JSONDict(), server_default="{}"),
        sa.Column("surface", sa.String(16), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", TS, server_default=sa.func.now()),
    )

    op.create_table(
        "ingestion_state",
        sa.Column("connector", sa.String(128), primary_key=True),
        sa.Column("cursor_at", TS),
        sa.Column("last_run_at", TS),
        sa.Column("last_status", sa.String(32), server_default="never_run"),
        sa.Column("last_error", sa.Text()),
        sa.Column("artifacts_ingested", sa.Integer(), server_default="0"),
    )

    op.create_table(
        "vector_chunks",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("collection", sa.String(64), nullable=False),
        sa.Column("ref_id", sa.String(64), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("embedding", FloatArray(), nullable=False),
        sa.Column("metadata", JSONDict(), server_default="{}"),
        sa.Column("created_at", TS, server_default=sa.func.now()),
    )
    op.create_index("idx_vector_collection", "vector_chunks", ["collection"])
    op.create_index("idx_vector_ref", "vector_chunks", ["ref_id"])


def downgrade() -> None:
    op.drop_table("vector_chunks")
    op.drop_table("ingestion_state")
    op.drop_table("query_log")
    op.drop_table("status_reports")
    op.drop_table("knowledge_requests")
    op.drop_table("expertise_scores")
    op.drop_table("work_artifacts")
    op.drop_constraint("fk_teams_manager", "teams", type_="foreignkey")
    op.drop_table("people")
    op.drop_table("teams")
    op.drop_table("orgs")
