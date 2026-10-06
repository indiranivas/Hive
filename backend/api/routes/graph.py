"""GET /api/graph/* -- the knowledge graph over people, topics, repos and KRs.

Answers the multi-hop questions vector search cannot: who collaborates with
whom (shared repos and topics), which topics rest on a single person, and the
neighborhood around any node for visualisation. Backed by GRAPH_PROVIDER:
`memory` (derived from SQL, always current) or `neo4j` (Cypher mirror).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.core.db import get_db
from api.core.graph import get_graph
from api.core.security import require
from api.models.orm import Person
from api.models.schemas import (
    BusFactorResponse,
    BusFactorTopicModel,
    CollaboratorModel,
    CollaboratorsResponse,
    GraphEdgeModel,
    GraphNodeModel,
    GraphResponse,
    GraphSyncResponse,
)

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _to_response(provider: str, nodes, edges) -> GraphResponse:
    return GraphResponse(
        provider=provider,
        nodes=[GraphNodeModel(id=n.id, label=n.label, kind=n.kind, meta=n.meta) for n in nodes],
        edges=[
            GraphEdgeModel(source=e.source, target=e.target, kind=e.kind, weight=e.weight)
            for e in edges
        ],
    )


@router.get("/overview", response_model=GraphResponse)
def graph_overview(
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_query")),
) -> GraphResponse:
    graph = get_graph()
    nodes, edges = graph.overview(db, team_id=user.team_id)
    return _to_response(graph.provider, nodes, edges)


@router.get("/neighborhood", response_model=GraphResponse)
def graph_neighborhood(
    node_id: str = Query(min_length=3, max_length=512, description="e.g. topic:billing-auth"),
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_query")),
) -> GraphResponse:
    graph = get_graph()
    nodes, edges = graph.neighborhood(db, node_id, team_id=user.team_id)
    return _to_response(graph.provider, nodes, edges)


@router.get("/collaborators", response_model=CollaboratorsResponse)
def graph_collaborators(
    person_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_query")),
) -> CollaboratorsResponse:
    target = person_id or user.id
    collaborators = get_graph().collaborators(db, target, team_id=user.team_id)
    return CollaboratorsResponse(
        person_id=target,
        collaborators=[
            CollaboratorModel(
                person_id=c.person_id,
                display_name=c.display_name,
                email=c.email,
                shared_topics=c.shared_topics,
                shared_repos=c.shared_repos,
                strength=c.strength,
            )
            for c in collaborators
        ],
    )


@router.get("/bus-factor", response_model=BusFactorResponse)
def graph_bus_factor(
    db: Session = Depends(get_db),
    user: Person = Depends(require("can_query")),
) -> BusFactorResponse:
    topics = get_graph().bus_factor(db, team_id=user.team_id)
    return BusFactorResponse(
        at_risk=[
            BusFactorTopicModel(
                topic=t.topic,
                expert_id=t.expert_id,
                expert_name=t.expert_name,
                score=t.score,
                evidence_count=t.evidence_count,
            )
            for t in topics
        ]
    )


@router.post("/sync", response_model=GraphSyncResponse)
def graph_sync(
    db: Session = Depends(get_db),
    _: Person = Depends(require("can_manage_connectors")),
) -> GraphSyncResponse:
    """Rebuild the graph mirror (a no-op for `memory`, which is always live).

    Deliberately org-wide rather than scoped to the caller's team: sync replaces
    the entire mirror, so scoping it to one team would silently delete every
    other team's nodes. The endpoint is admin-only, which is the scope gate.
    """
    stats = get_graph().sync(db, team_id=None)
    return GraphSyncResponse(**stats)
