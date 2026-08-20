"""Manager dashboard data: team pulse, activity breakdown, expertise map."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.security import require
from api.models.orm import Person
from api.services.dashboard_service import activity_breakdown, expertise_map, team_pulse

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _scope(user: Person, requested: uuid.UUID | None) -> uuid.UUID | None:
    """Admins may inspect any team; everyone else sees their own."""
    if requested and (user.role == "admin" or requested == user.team_id):
        return requested
    return user.team_id


@router.get("/pulse")
def get_pulse(
    team_id: uuid.UUID | None = None,
    window_days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_view_dashboard")),
) -> dict:
    return team_pulse(db, _scope(user, team_id), window_days=window_days).to_dict()


@router.get("/activity")
def get_activity(
    team_id: uuid.UUID | None = None,
    weeks: int = Query(default=8, ge=1, le=52),
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_view_dashboard")),
) -> dict:
    return {"weeks": activity_breakdown(db, _scope(user, team_id), weeks=weeks)}


@router.get("/expertise-map")
def get_expertise_map(
    team_id: uuid.UUID | None = None,
    min_score: float = Query(default=0.1, ge=0.0, le=100.0),
    limit: int = Query(default=120, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_view_dashboard")),
) -> dict:
    return expertise_map(db, _scope(user, team_id), min_score=min_score, limit=limit)
