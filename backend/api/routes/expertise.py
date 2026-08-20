"""GET /api/expertise/search -- who at the company knows X, with evidence."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.security import require
from api.models.orm import Person
from api.models.schemas import ExpertModel, ExpertSearchResponse
from api.services.expertise_mapper import find_experts

router = APIRouter(prefix="/api/expertise", tags=["expertise"])


@router.get("/search", response_model=ExpertSearchResponse)
def search_experts(
    topic: str = Query(min_length=1, max_length=256),
    limit: int = Query(default=5, ge=1, le=25),
    team_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_query")),
) -> ExpertSearchResponse:
    experts = find_experts(db, topic, limit=limit, team_id=team_id or user.team_id)
    return ExpertSearchResponse(
        topic=topic,
        experts=[
            ExpertModel(
                person_id=expert.person_id,
                display_name=expert.display_name,
                email=expert.email,
                topics=expert.topics,
                score=round(expert.score, 4),
                evidence_count=expert.evidence_count,
                last_seen=expert.last_seen,
            )
            for expert in experts
        ],
    )
