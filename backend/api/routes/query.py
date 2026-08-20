"""POST /api/query -- natural language Q&A over the team's work trail."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.security import has_permission, require
from api.models.orm import Person
from api.models.schemas import QueryRequest, QueryResponseModel
from api.services.query_engine import answer_query

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponseModel)
def post_query(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_query")),
) -> QueryResponseModel:
    # Scope enforcement: a member's own team is the ceiling unless they hold
    # can_query_org, and an explicit team_id is only honored for their own team.
    scope = payload.scope
    if scope == "org" and not has_permission(user.role, "can_query_org"):
        scope = "team"
    team_id = user.team_id
    if payload.team_id and (payload.team_id == user.team_id or user.role == "admin"):
        team_id = payload.team_id

    result = answer_query(
        db,
        payload.query,
        user_id=user.id,
        team_id=team_id,
        scope=scope,
        surface="dashboard",
    )
    return QueryResponseModel(**result.to_dict())
