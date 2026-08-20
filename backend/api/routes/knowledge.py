"""Knowledge Requests: browse the repo, raise a gap, answer one, read gap analytics.

Answering closes the loop the query engine depends on: the answer is embedded
into the knowledge repo collection, so the next person asking gets the answer
instead of the gap. Automatic routing to an expert is still Phase 4.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta  # noqa: F401

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.security import require
from api.core.timeutil import to_utc
from api.models.orm import ExpertiseScore, KnowledgeRequest, Person
from api.services.kr_manager import create_knowledge_request
from api.services.kr_routing_graph import answer_knowledge_request, route_knowledge_request

router = APIRouter(prefix="/api/knowledge-requests", tags=["knowledge"])

ANSWERED_STATUSES = ("answered", "indexed")


class CreateKRRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    context: str | None = Field(default=None, max_length=4000)


class AnswerKRRequest(BaseModel):
    answer: str = Field(min_length=3, max_length=8000)


def _serialize(kr: KnowledgeRequest, people: dict[uuid.UUID, str]) -> dict:
    created = to_utc(kr.created_at)
    answered = to_utc(kr.answered_at)
    resolution_hours = None
    if created and answered:
        resolution_hours = round((answered - created).total_seconds() / 3600, 1)
    return {
        "id": str(kr.id),
        "question": kr.question,
        "context": kr.context,
        "status": kr.status,
        "answer": kr.answer,
        "tags": list(kr.tags or []),
        "requester": people.get(kr.requester_id),
        "routed_to": people.get(kr.routed_to_id) if kr.routed_to_id else None,
        "answered_by": people.get(kr.answered_by_id) if kr.answered_by_id else None,
        "created_at": created.isoformat() if created else None,
        "answered_at": answered.isoformat() if answered else None,
        "resolution_hours": resolution_hours,
    }


def _people_index(session: Session) -> dict[uuid.UUID, str]:
    return dict(session.execute(select(Person.id, Person.display_name)).all())


@router.get("")
def list_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    tag: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Person = Depends(require("can_create_kr")),
) -> dict:
    stmt = select(KnowledgeRequest).order_by(KnowledgeRequest.created_at.desc())
    if status_filter == "open":
        stmt = stmt.where(KnowledgeRequest.status.in_(["open", "routed"]))
    elif status_filter == "answered":
        stmt = stmt.where(KnowledgeRequest.status.in_(ANSWERED_STATUSES))
    elif status_filter:
        stmt = stmt.where(KnowledgeRequest.status == status_filter)
    if search:
        needle = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(KnowledgeRequest.question).like(needle)
            | func.lower(func.coalesce(KnowledgeRequest.answer, "")).like(needle)
        )

    people = _people_index(db)
    items = [_serialize(kr, people) for kr in db.execute(stmt.limit(limit)).scalars()]
    # tags is TEXT[] on Postgres and JSON on SQLite, so filter in Python rather
    # than writing two dialect-specific queries.
    if tag:
        items = [item for item in items if tag in item["tags"]]
    return {"items": items, "count": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_request(
    payload: CreateKRRequest,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_create_kr")),
) -> dict:
    kr = create_knowledge_request(db, user.id, payload.question, payload.context)
    return _serialize(kr, _people_index(db))


@router.put("/{kr_id}/answer")
def answer_request(
    kr_id: uuid.UUID,
    payload: AnswerKRRequest,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_answer_kr")),
) -> dict:
    kr = db.get(KnowledgeRequest, kr_id)
    if kr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown request")
    if kr.status in ANSWERED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="already answered"
        )

    # One place owns store -> index -> credit expertise -> notify the asker.
    answer_knowledge_request(db, kr, user, payload.answer)
    return _serialize(kr, _people_index(db))


@router.post("/{kr_id}/route")
def reroute_request(
    kr_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: Person = Depends(require("can_create_kr")),
) -> dict:
    """Re-run routing, e.g. after expertise has shifted or the first pick declined."""
    kr = db.get(KnowledgeRequest, kr_id)
    if kr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown request")
    result = route_knowledge_request(db, kr)
    return {
        "kr_id": result.kr_id,
        "status": result.status,
        "routed_to": result.routed_to_name,
        "reason": result.reason,
        "considered": [
            {
                "name": expert["name"],
                "routing_score": expert["routing_score"],
                "open_krs": expert["open_krs"],
            }
            for expert in result.considered
        ],
    }


@router.get("/analytics")
def analytics(
    weeks: int = Query(default=8, ge=1, le=52),
    db: Session = Depends(get_db),
    _: Person = Depends(require("can_view_gap_analytics")),
) -> dict:
    requests = list(db.execute(select(KnowledgeRequest)).scalars())
    people = _people_index(db)

    open_krs = [kr for kr in requests if kr.status in ("open", "routed")]
    answered = [kr for kr in requests if kr.status in ANSWERED_STATUSES]

    durations = []
    for kr in answered:
        created, answered_at = to_utc(kr.created_at), to_utc(kr.answered_at)
        if created and answered_at:
            hours = (answered_at - created).total_seconds() / 3600
            # Backfilled or imported rows can be answered "before" they were
            # created; a negative average is worse than no average.
            if hours >= 0:
                durations.append(hours)

    topics: Counter[str] = Counter()
    for kr in requests:
        topics.update(kr.tags or [])

    # Bus factor: topics where exactly one person holds the evidence.
    owners: dict[str, set[uuid.UUID]] = defaultdict(set)
    for topic, person_id in db.execute(
        select(ExpertiseScore.topic, ExpertiseScore.person_id).where(ExpertiseScore.score > 0.2)
    ).all():
        owners[topic].add(person_id)

    solo: dict[uuid.UUID, list[str]] = defaultdict(list)
    for topic, holders in owners.items():
        if len(holders) == 1:
            solo[next(iter(holders))].append(topic)

    routed_counts = Counter(kr.routed_to_id for kr in open_krs if kr.routed_to_id)
    bus_factor = [
        {
            "person": people.get(person_id, "unknown"),
            "solo_topics": sorted(topics_held)[:12],
            "solo_topic_count": len(topics_held),
            "routed_krs": routed_counts.get(person_id, 0),
        }
        for person_id, topics_held in sorted(
            solo.items(), key=lambda item: len(item[1]), reverse=True
        )
    ][:10]

    today = datetime.now(UTC).date()
    current_week = today - timedelta(days=today.weekday())
    trend = []
    for index in range(weeks - 1, -1, -1):
        week_start = current_week - timedelta(weeks=index)
        week_end = week_start + timedelta(days=7)
        trend.append(
            {
                "week": week_start.isoformat(),
                "new": sum(
                    1
                    for kr in requests
                    if (created := to_utc(kr.created_at))
                    and week_start <= created.date() < week_end
                ),
                "resolved": sum(
                    1
                    for kr in answered
                    if (answered_at := to_utc(kr.answered_at))
                    and week_start <= answered_at.date() < week_end
                ),
            }
        )

    return {
        "open_krs": len(open_krs),
        "answered_krs": len(answered),
        "avg_resolution_hours": round(sum(durations) / len(durations), 1) if durations else None,
        "top_requested_topics": [
            {"topic": topic, "count": count} for topic, count in topics.most_common(12)
        ],
        "bus_factor": bus_factor,
        "trend": trend,
    }
