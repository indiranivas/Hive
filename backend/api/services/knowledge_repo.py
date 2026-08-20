"""Indexing answered Knowledge Requests into the permanent repo collection.

The capture side of the KR loop lands in Phase 4; this is the piece the query
engine already depends on, so it lives here rather than in the seed script.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from api.core.embeddings import get_embedder
from api.core.vectorstore import KNOWLEDGE_COLLECTION, VectorRecord, get_vector_store
from api.models.orm import KnowledgeRequest, Person


def index_knowledge_request(session: Session, kr: KnowledgeRequest) -> bool:
    """Embed an answered KR so future questions hit the answer, not the gap."""
    if not kr.answer:
        return False

    answered_by = session.get(Person, kr.answered_by_id) if kr.answered_by_id else None
    document = f"Q: {kr.question}\nA: {kr.answer}"
    get_vector_store().upsert(
        session,
        KNOWLEDGE_COLLECTION,
        [
            VectorRecord(
                id=str(kr.id),
                ref_id=str(kr.id),
                document=document,
                embedding=get_embedder().encode_one(document),
                metadata={
                    "question": kr.question,
                    "answer": kr.answer,
                    "answered_by": str(kr.answered_by_id) if kr.answered_by_id else None,
                    "answered_by_name": answered_by.display_name if answered_by else None,
                    "tags": ",".join(kr.tags or []),
                    "created_at": kr.created_at.isoformat() if kr.created_at else None,
                },
            )
        ],
    )
    kr.status = "indexed"
    session.flush()
    return True
