"""Expertise scoring and expert lookup (blueprint section 7.3).

Scores decay toward recent evidence: each new artifact multiplies the standing
score by 0.95 and adds a recency-weighted increment, so someone who touched a
topic last week outranks someone who touched it constantly two years ago.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.core.embeddings import get_embedder
from api.core.timeutil import to_utc
from api.core.vectorstore import ARTIFACT_COLLECTION, get_vector_store
from api.models.orm import ExpertiseScore, Person

DECAY = 0.95
INCREMENT_WEIGHT = 0.3
VECTOR_EVIDENCE_WEIGHT = 0.12


@dataclass(slots=True)
class ExpertResult:
    person_id: uuid.UUID
    display_name: str
    email: str
    topics: list[str]
    score: float
    evidence_count: int
    last_seen: datetime | None
    recency_weight: float = 0.0
    routing_score: float = 0.0


def recency_weight(occurred_at: datetime | None) -> float:
    reference = to_utc(occurred_at)
    if reference is None:
        return 0.0
    days = (datetime.now(UTC) - reference).days
    return 1.0 / max(1.0, days / 30.0)


def update_expertise(session: Session, person_id: uuid.UUID | None, topics: list[str],
                     occurred_at: datetime) -> None:
    if not person_id or not topics:
        return
    occurred_at = to_utc(occurred_at) or datetime.now(UTC)
    weight = recency_weight(occurred_at)
    for topic in dict.fromkeys(topics):
        existing = session.execute(
            select(ExpertiseScore).where(
                ExpertiseScore.person_id == person_id, ExpertiseScore.topic == topic
            )
        ).scalar_one_or_none()
        if existing:
            existing.score = existing.score * DECAY + weight * INCREMENT_WEIGHT
            existing.evidence_count += 1
            last_seen = to_utc(existing.last_seen)
            if last_seen is None or occurred_at > last_seen:
                existing.last_seen = occurred_at
        else:
            session.add(
                ExpertiseScore(
                    person_id=person_id,
                    topic=topic,
                    score=max(weight, INCREMENT_WEIGHT),
                    evidence_count=1,
                    last_seen=occurred_at,
                )
            )
    session.flush()


def _match_weight(topic: str, needle: str) -> float:
    """How much a stored topic counts toward the searched topic.

    An exact or containment match counts fully; a shared word counts partially,
    so `azure` alone never outranks `azure-devops-api` for that search.
    """
    if topic == needle:
        return 1.0
    if needle in topic or topic in needle:
        return 0.8
    topic_parts = set(topic.split("-"))
    needle_parts = set(needle.split("-"))
    shared = topic_parts & needle_parts
    if not shared:
        return 0.0
    return 0.5 * len(shared) / max(len(needle_parts), 1)


def _vector_author_evidence(session: Session, topic: str,
                            team_id: uuid.UUID | None) -> Counter[str]:
    embedding = get_embedder().encode_one(topic.replace("-", " "))
    hits = get_vector_store().query(
        session,
        ARTIFACT_COLLECTION,
        embedding,
        n_results=50,
        where={"team_id": str(team_id)} if team_id else None,
    )
    # Hold semantic evidence to the same relevance floor as retrieval: a barely
    # positive cosine is not evidence that someone knows a topic.
    floor = get_settings().retrieval_min_score
    counts: Counter[str] = Counter()
    for hit in hits:
        author_id = hit.metadata.get("author_id")
        if author_id and author_id != "None" and hit.score >= floor:
            counts[str(author_id)] += 1
    return counts


def find_experts(session: Session, topic: str, limit: int = 5,
                 team_id: uuid.UUID | None = None) -> list[ExpertResult]:
    """Blend explicit topic scores with semantic evidence from the artifact index."""
    needle = topic.strip().lower().replace(" ", "-")
    if not needle:
        return []

    # Match the whole phrase AND its parts: topics are extracted per artifact, so
    # "azure-devops-api" must still find someone scored on "azure" and "devops".
    parts = [part for part in needle.split("-") if len(part) > 2]
    patterns = [needle, *parts]
    stmt = (
        select(ExpertiseScore, Person)
        .join(Person, Person.id == ExpertiseScore.person_id)
        .where(or_(*[ExpertiseScore.topic.ilike(f"%{pattern}%") for pattern in patterns]))
        .order_by(ExpertiseScore.score.desc())
        .limit(limit * 20)
    )
    if team_id:
        stmt = stmt.where(Person.team_id == team_id)

    merged: dict[uuid.UUID, ExpertResult] = {}
    for score_row, person in session.execute(stmt).all():
        weight = _match_weight(score_row.topic, needle)
        contribution = score_row.score * weight
        result = merged.get(person.id)
        last_seen = to_utc(score_row.last_seen)
        if result is None:
            merged[person.id] = ExpertResult(
                person_id=person.id,
                display_name=person.display_name,
                email=person.email,
                topics=[score_row.topic],
                score=contribution,
                evidence_count=score_row.evidence_count,
                last_seen=last_seen,
                recency_weight=recency_weight(last_seen),
            )
        else:
            result.topics.append(score_row.topic)
            result.score += contribution
            result.evidence_count += score_row.evidence_count
            if last_seen and (result.last_seen is None or last_seen > result.last_seen):
                result.last_seen = last_seen
                result.recency_weight = recency_weight(last_seen)

    # Semantic evidence re-ranks people who already have a matching topic score;
    # it never introduces an expert on its own. Otherwise a vaguely similar commit
    # is enough to name someone an expert on a topic they never touched.
    for author_id, count in _vector_author_evidence(session, needle, team_id).items():
        try:
            person_uuid = uuid.UUID(author_id)
        except ValueError:
            continue
        result = merged.get(person_uuid)
        if result:
            result.score += VECTOR_EVIDENCE_WEIGHT * count

    ranked = sorted(merged.values(), key=lambda item: item.score, reverse=True)
    return ranked[:limit]
