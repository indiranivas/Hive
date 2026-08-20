"""Auto-generated status reports.

Scope rules from blueprint section 11: a member may read their own status,
a manager may read their team's. Nobody reads "up".
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.security import get_current_user, has_permission, require
from api.models.orm import Person
from api.services.status_generator import generate_status, generate_team_statuses, week_bounds

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("/team")
def my_team_status(
    week: date | None = Query(default=None, description="any date inside the target week"),
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_view_team_status")),
) -> dict:
    """The caller's own team -- saves every client from having to resolve an id."""
    if user.team_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="you are not assigned to a team",
        )
    start, end = week_bounds(week)
    results = generate_team_statuses(db, user.team_id, week, force=refresh)
    return {
        "team_id": str(user.team_id),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "statuses": [asdict(result) for result in results],
    }


@router.get("/team/{team_id}")
def team_status(
    team_id: uuid.UUID,
    week: date | None = Query(default=None, description="any date inside the target week"),
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_view_team_status")),
) -> dict:
    if team_id != user.team_id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="that is not your team"
        )
    start, end = week_bounds(week)
    results = generate_team_statuses(db, team_id, week, force=refresh)
    return {
        "team_id": str(team_id),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "statuses": [asdict(result) for result in results],
    }


@router.get("/person/{person_id}")
def person_status(
    person_id: uuid.UUID,
    week: date | None = None,
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: Person = Depends(get_current_user),
) -> dict:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown person")

    is_self = person.id == user.id
    can_view_team = has_permission(user.role, "can_view_team_status") and (
        person.team_id == user.team_id or user.role == "admin"
    )
    if not (is_self or can_view_team):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="members can only read their own status",
        )

    result = generate_status(db, person_id, person.team_id, week, None, force=refresh)
    return asdict(result)


@router.get("/me")
def my_status(
    week: date | None = None,
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_view_own_status")),
) -> dict:
    return asdict(generate_status(db, user.id, user.team_id, week, None, force=refresh))
