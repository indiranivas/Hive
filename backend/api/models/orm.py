"""SQLAlchemy models for the schemas in blueprint section 5.1.

Deviations from the raw SQL in the blueprint, all deliberate:
  * people.azure_ad_id is nullable -- artifacts resolve authors by email long
    before those people ever sign in through Entra ID.
  * knowledge_requests.related_artifacts is TEXT[] of UUID strings so the same
    model works on SQLite.
  * ingestion_state and vector_chunks are additions: incremental connector
    cursors and the SQL-backed vector store.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from api.models.types import GUID, FloatArray, JSONDict, StringArray


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Org(Base):
    __tablename__ = "orgs"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    teams: Mapped[list[Team]] = relationship(back_populates="org")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    org_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("orgs.id"))
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("people.id", use_alter=True, name="fk_teams_manager")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    org: Mapped[Org | None] = relationship(back_populates="teams")
    members: Mapped[list[Person]] = relationship(
        back_populates="team", foreign_keys="Person.team_id"
    )


class Person(Base):
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    azure_ad_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    team_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("teams.id"))
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    team: Mapped[Team | None] = relationship(back_populates="members", foreign_keys=[team_id])


class WorkArtifact(Base):
    """The universal record every connector normalizes into."""

    __tablename__ = "work_artifacts"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_artifact_source"),
        Index("idx_artifacts_author", "author_id"),
        Index("idx_artifacts_team", "team_id"),
        Index("idx_artifacts_type", "artifact_type"),
        Index("idx_artifacts_occurred", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(512), nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("people.id"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("teams.id"))
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONDict, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    author: Mapped[Person | None] = relationship()


class ExpertiseScore(Base):
    __tablename__ = "expertise_scores"
    __table_args__ = (
        UniqueConstraint("person_id", "topic", name="uq_expertise_person_topic"),
        Index("idx_expertise_topic", "topic"),
        Index("idx_expertise_score", "score"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    person_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("people.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String(256), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    person: Mapped[Person] = relationship()


class KnowledgeRequest(Base):
    __tablename__ = "knowledge_requests"
    __table_args__ = (Index("idx_kr_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    requester_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("people.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")
    routed_to_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("people.id"))
    answer: Mapped[str | None] = mapped_column(Text)
    answered_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("people.id"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list[str]] = mapped_column(StringArray, default=list)
    related_artifacts: Mapped[list[str]] = mapped_column(StringArray, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    requester: Mapped[Person] = relationship(foreign_keys=[requester_id])
    routed_to: Mapped[Person | None] = relationship(foreign_keys=[routed_to_id])
    answered_by: Mapped[Person | None] = relationship(foreign_keys=[answered_by_id])


class StatusReport(Base):
    __tablename__ = "status_reports"
    __table_args__ = (
        UniqueConstraint("person_id", "period_start", "period_end", name="uq_status_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    person_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("people.id"), nullable=False)
    team_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("teams.id"))
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONDict, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    person: Mapped[Person] = relationship()


class QueryLog(Base):
    __tablename__ = "query_log"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("people.id"))
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text)
    sources_used: Mapped[dict] = mapped_column(JSONDict, default=dict)
    surface: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionState(Base):
    """Per-connector watermark so scheduled pulls stay incremental."""

    __tablename__ = "ingestion_state"

    connector: Mapped[str] = mapped_column(String(128), primary_key=True)
    cursor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(32), default="never_run")
    last_error: Mapped[str | None] = mapped_column(Text)
    artifacts_ingested: Mapped[int] = mapped_column(Integer, default=0)


class VectorChunk(Base):
    """Embedding rows for the SQL vector store (dev default; Chroma/Qdrant in prod)."""

    __tablename__ = "vector_chunks"
    __table_args__ = (
        Index("idx_vector_collection", "collection"),
        Index("idx_vector_ref", "ref_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection: Mapped[str] = mapped_column(String(64), nullable=False)
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(FloatArray, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONDict, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BotConversation(Base):
    """Where to reach a person proactively.

    A bot can only start a conversation it has seen before, so every turn stores
    the Bot Framework conversation reference. Phase 5's dependency alerts read it.
    """

    __tablename__ = "bot_conversations"

    person_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("people.id"), primary_key=True)
    service_url: Mapped[str | None] = mapped_column(String(512))
    conversation_reference: Mapped[dict] = mapped_column(JSONDict, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Notification(Base):
    """Outbox for anything Hive wants to tell a person.

    The routing graph writes rows here instead of calling Teams inline: delivery
    needs the Bot Framework SDK and a live channel, so decoupling it keeps routing
    testable and makes a failed send retryable rather than lost.
    """

    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_uuid)
    person_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("people.id"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(GUID, ForeignKey("teams.id"))
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONDict, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    person: Mapped[Person | None] = relationship()
