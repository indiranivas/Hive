"""Request/response contracts for the REST API (blueprint section 15)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    team_id: uuid.UUID | None = None
    scope: Literal["team", "org"] = "team"


class SourceModel(BaseModel):
    artifact_id: str
    type: str
    title: str
    author: str | None = None
    date: str | None = None
    relevance: float
    excerpt: str
    reference: str | None = None


class QueryResponseModel(BaseModel):
    answer: str
    sources: list[SourceModel] = Field(default_factory=list)
    has_gap: bool = False
    latency_ms: int = 0
    model: str = ""
    attempts: int = 1
    rewrites: list[str] = Field(default_factory=list)


class ExpertModel(BaseModel):
    person_id: uuid.UUID
    display_name: str
    email: str
    topics: list[str]
    score: float
    evidence_count: int
    last_seen: datetime | None = None


class ExpertSearchResponse(BaseModel):
    topic: str
    experts: list[ExpertModel]


class ConnectorStatus(BaseModel):
    connector: str
    last_status: str
    last_run_at: datetime | None = None
    cursor_at: datetime | None = None
    artifacts_ingested: int
    last_error: str | None = None


class IngestionStatusResponse(BaseModel):
    connectors: list[ConnectorStatus]
    artifact_count: int
    chunk_count: int
    people_count: int


class IngestTriggerResponse(BaseModel):
    runs: list[dict]


class AuditLogEntry(BaseModel):
    id: uuid.UUID
    user_email: str | None = None
    query_text: str
    surface: str
    latency_ms: int | None = None
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    environment: str
    llm_provider: str
    embedding_provider: str
    vector_provider: str
    database: str
