"""Admin surface: connector health, manual ingestion trigger, query audit trail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.security import require
from api.models.orm import IngestionState, Person, QueryLog, VectorChunk, WorkArtifact
from api.models.schemas import (
    AuditLogEntry,
    ConnectorStatus,
    IngestionStatusResponse,
    IngestTriggerResponse,
)
from ingestion.runner import run_git_ingestion

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/ingestion-status", response_model=IngestionStatusResponse)
def ingestion_status(
    db: Session = Depends(get_db),
    _: Person = Depends(require("can_manage_connectors")),
) -> IngestionStatusResponse:
    states = db.execute(select(IngestionState).order_by(IngestionState.connector)).scalars()
    return IngestionStatusResponse(
        connectors=[
            ConnectorStatus(
                connector=state.connector,
                last_status=state.last_status,
                last_run_at=state.last_run_at,
                cursor_at=state.cursor_at,
                artifacts_ingested=state.artifacts_ingested,
                last_error=state.last_error,
            )
            for state in states
        ],
        artifact_count=db.execute(select(func.count(WorkArtifact.id))).scalar_one(),
        chunk_count=db.execute(select(func.count(VectorChunk.id))).scalar_one(),
        people_count=db.execute(select(func.count(Person.id))).scalar_one(),
    )


@router.post("/ingest/git", response_model=IngestTriggerResponse)
def trigger_git_ingestion(
    db: Session = Depends(get_db),
    _: Person = Depends(require("can_manage_connectors")),
) -> IngestTriggerResponse:
    runs = run_git_ingestion(db)
    return IngestTriggerResponse(
        runs=[
            {
                "connector": run.connector,
                "status": run.status,
                "fetched": run.fetched,
                "created": run.result.created,
                "updated": run.result.updated,
                "skipped": run.result.skipped,
                "chunks": run.result.chunks,
                "error": run.error,
            }
            for run in runs
        ]
    )


@router.get("/audit-log", response_model=list[AuditLogEntry])
def audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Person = Depends(require("can_view_audit_log")),
) -> list[AuditLogEntry]:
    rows = db.execute(
        select(QueryLog, Person.email)
        .outerjoin(Person, Person.id == QueryLog.user_id)
        .order_by(QueryLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        AuditLogEntry(
            id=log.id,
            user_email=email,
            query_text=log.query_text,
            surface=log.surface,
            latency_ms=log.latency_ms,
            created_at=log.created_at,
        )
        for log, email in rows
    ]
