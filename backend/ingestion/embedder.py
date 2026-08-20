"""Persist + chunk + embed + score. The single write path into the knowledge layer.

Idempotent on (source, source_id): re-ingesting the same commit updates the row
and replaces its chunks instead of duplicating evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.embeddings import get_embedder
from api.core.vectorstore import ARTIFACT_COLLECTION, VectorRecord, get_vector_store
from api.models.orm import WorkArtifact as WorkArtifactRow
from api.services.expertise_mapper import update_expertise
from api.services.topics import extract_topics
from ingestion.normalizer import WorkArtifact, chunk_content

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    chunks: int = 0

    def merge(self, other: IngestResult) -> IngestResult:
        return IngestResult(
            created=self.created + other.created,
            updated=self.updated + other.updated,
            skipped=self.skipped + other.skipped,
            chunks=self.chunks + other.chunks,
        )


def persist_artifact(session: Session, artifact: WorkArtifact) -> IngestResult:
    if not (artifact.content or "").strip():
        return IngestResult(skipped=1)

    existing = session.execute(
        select(WorkArtifactRow).where(
            WorkArtifactRow.source == artifact.source,
            WorkArtifactRow.source_id == artifact.source_id,
        )
    ).scalar_one_or_none()

    result = IngestResult()
    if existing:
        unchanged = existing.content == artifact.content and existing.title == artifact.title
        if unchanged:
            return IngestResult(skipped=1)
        existing.title = artifact.title
        existing.content = artifact.content
        existing.meta = artifact.metadata
        existing.occurred_at = artifact.occurred_at
        if artifact.author_id:
            existing.author_id = artifact.author_id
        if artifact.team_id:
            existing.team_id = artifact.team_id
        row = existing
        result.updated = 1
    else:
        row = WorkArtifactRow(
            id=artifact.id,
            source=artifact.source,
            source_id=artifact.source_id,
            author_id=artifact.author_id,
            team_id=artifact.team_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=artifact.content,
            meta=artifact.metadata,
            occurred_at=artifact.occurred_at,
        )
        session.add(row)
        result.created = 1
    session.flush()

    store = get_vector_store()
    store.delete_by_ref(session, ARTIFACT_COLLECTION, str(row.id))

    embed_text = f"{artifact.title}\n{artifact.content}" if artifact.title else artifact.content
    chunks = chunk_content(embed_text)
    if chunks:
        embeddings = get_embedder().encode(chunks)
        metadata_base = {
            "artifact_id": str(row.id),
            "source": artifact.source,
            "artifact_type": artifact.artifact_type,
            "author_id": str(artifact.author_id) if artifact.author_id else None,
            "author_name": artifact.author_name,
            "team_id": str(artifact.team_id) if artifact.team_id else None,
            "occurred_at": artifact.occurred_at.isoformat(),
            "title": artifact.title or "",
        }
        store.upsert(
            session,
            ARTIFACT_COLLECTION,
            [
                VectorRecord(
                    id=f"{row.id}_{index}",
                    ref_id=str(row.id),
                    document=chunk,
                    embedding=embedding,
                    metadata={**metadata_base, "chunk_index": index},
                )
                for index, (chunk, embedding) in enumerate(
                    zip(chunks, embeddings, strict=True)
                )
            ],
        )
        result.chunks = len(chunks)

    topics = extract_topics(embed_text, artifact.metadata)
    if topics:
        row.meta = {**(row.meta or {}), "topics": topics}
        update_expertise(session, artifact.author_id, topics, artifact.occurred_at)

    return result


def persist_artifacts(session: Session, artifacts: list[WorkArtifact]) -> IngestResult:
    total = IngestResult()
    for artifact in artifacts:
        # Savepoint per artifact: one bad payload must not discard the batch.
        try:
            with session.begin_nested():
                total = total.merge(persist_artifact(session, artifact))
        except Exception:
            logger.exception(
                "failed to persist artifact source=%s source_id=%s",
                artifact.source,
                artifact.source_id,
            )
            total = total.merge(IngestResult(skipped=1))
    return total
