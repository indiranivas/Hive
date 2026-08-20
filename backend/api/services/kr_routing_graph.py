"""Knowledge Request routing as a LangGraph state machine (blueprint section 8).

    tag -> find_experts -> rank -> route ----> notify_expert
                                \\-> unrouted -> notify_team

Routing is a branching decision with a real fork (an expert was found, or nobody
has evidence), which is what makes a graph worth its keep here. Durable state
still lives in Postgres -- the graph decides, the DB remembers, and delivery goes
through the notification outbox so a missing Teams channel cannot lose a routing.

As in retrieval_graph, LangGraph is the runtime only; the nodes call Hive's own
expertise and topic services.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.orm import KnowledgeRequest, Notification, Person
from api.services.expertise_mapper import find_experts, recency_weight
from api.services.knowledge_repo import index_knowledge_request
from api.services.topics import extract_topics

logger = logging.getLogger(__name__)

# Blueprint section 8: expertise, then recency, minus current load.
SCORE_WEIGHT = 0.5
RECENCY_WEIGHT = 0.3
LOAD_PENALTY = 0.2
EXPERTS_PER_TAG = 3


class RoutingState(TypedDict, total=False):
    kr_id: str
    question: str
    requester_id: str
    team_id: str | None
    tags: list[str]
    experts: list[dict[str, Any]]
    chosen: dict[str, Any] | None
    reason: str


@dataclass(slots=True)
class RoutingResult:
    kr_id: str
    status: str
    routed_to: str | None = None
    routed_to_name: str | None = None
    reason: str = ""
    tags: list[str] = field(default_factory=list)
    considered: list[dict[str, Any]] = field(default_factory=list)


def routing_score(expertise: float, last_seen, open_kr_count: int) -> float:
    return (
        expertise * SCORE_WEIGHT
        + recency_weight(last_seen) * RECENCY_WEIGHT
        - open_kr_count * LOAD_PENALTY
    )


def _open_load(session: Session, person_id: uuid.UUID) -> int:
    return int(
        session.execute(
            select(func.count(KnowledgeRequest.id)).where(
                KnowledgeRequest.routed_to_id == person_id,
                KnowledgeRequest.status == "routed",
            )
        ).scalar_one()
    )


def _already_notified(session: Session, kr_id: str, person_id: uuid.UUID) -> bool:
    """Has this person already been told about this request and not yet acted?"""
    existing = session.execute(
        select(Notification).where(
            Notification.person_id == person_id,
            Notification.kind == "kr_routed",
            Notification.status.in_(["pending", "sent"]),
        )
    ).scalars()
    return any(str((row.payload or {}).get("kr_id")) == kr_id for row in existing)


def _build_nodes(session: Session):
    def node_tag(state: RoutingState) -> RoutingState:
        if state.get("tags"):
            return {}
        return {"tags": extract_topics(state["question"])}

    def node_find_experts(state: RoutingState) -> RoutingState:
        team_id = uuid.UUID(state["team_id"]) if state.get("team_id") else None
        requester = uuid.UUID(state["requester_id"])
        found: dict[uuid.UUID, dict[str, Any]] = {}
        for tag in state.get("tags") or []:
            for expert in find_experts(session, tag, limit=EXPERTS_PER_TAG, team_id=team_id):
                # Routing a question back to the person who asked it is useless.
                if expert.person_id == requester:
                    continue
                existing = found.get(expert.person_id)
                if existing is None or expert.score > existing["score"]:
                    found[expert.person_id] = {
                        "person_id": str(expert.person_id),
                        "name": expert.display_name,
                        "score": expert.score,
                        "last_seen": expert.last_seen,
                        "topics": expert.topics,
                    }
        return {"experts": list(found.values())}

    def node_rank(state: RoutingState) -> RoutingState:
        ranked: list[dict[str, Any]] = []
        for expert in state.get("experts") or []:
            load = _open_load(session, uuid.UUID(expert["person_id"]))
            ranked.append(
                {
                    **expert,
                    "open_krs": load,
                    "routing_score": round(
                        routing_score(expert["score"], expert.get("last_seen"), load), 4
                    ),
                }
            )
        ranked.sort(key=lambda item: item["routing_score"], reverse=True)
        if not ranked:
            return {"experts": [], "chosen": None, "reason": "nobody has evidence on these topics"}
        best = ranked[0]
        return {
            "experts": ranked,
            "chosen": best,
            "reason": (
                f"highest expertise on {', '.join(best['topics'][:3])} "
                f"(score {best['score']:.2f}, {best['open_krs']} open request(s))"
            ),
        }

    def node_route(state: RoutingState) -> RoutingState:
        kr = session.get(KnowledgeRequest, uuid.UUID(state["kr_id"]))
        chosen = state.get("chosen")
        if kr is None or not chosen:
            return {}
        kr.routed_to_id = uuid.UUID(chosen["person_id"])
        kr.status = "routed"
        if not kr.tags:
            kr.tags = list(state.get("tags") or [])
        session.flush()
        return {}

    def node_notify_expert(state: RoutingState) -> RoutingState:
        chosen = state.get("chosen")
        if not chosen:
            return {}
        if _already_notified(session, state["kr_id"], uuid.UUID(chosen["person_id"])):
            # Re-routing to the same person must not ping them twice.
            return {}
        requester = session.get(Person, uuid.UUID(state["requester_id"]))
        session.add(
            Notification(
                person_id=uuid.UUID(chosen["person_id"]),
                team_id=uuid.UUID(state["team_id"]) if state.get("team_id") else None,
                kind="kr_routed",
                subject="A teammate needs your knowledge",
                body=(
                    f"{requester.display_name if requester else 'A teammate'} asked: "
                    f"{state['question']}"
                ),
                payload={
                    "kr_id": state["kr_id"],
                    "tags": list(state.get("tags") or []),
                    "reason": state.get("reason", ""),
                },
            )
        )
        session.flush()
        return {}

    def node_notify_team(state: RoutingState) -> RoutingState:
        """Nobody had evidence: put it to the team rather than dropping it."""
        session.add(
            Notification(
                person_id=None,
                team_id=uuid.UUID(state["team_id"]) if state.get("team_id") else None,
                kind="kr_unrouted",
                subject="Open question with no obvious expert",
                body=state["question"],
                payload={
                    "kr_id": state["kr_id"],
                    "tags": list(state.get("tags") or []),
                    "reason": state.get("reason", ""),
                },
            )
        )
        session.flush()
        return {}

    return node_tag, node_find_experts, node_rank, node_route, node_notify_expert, node_notify_team


def _has_expert(state: RoutingState) -> str:
    return "route" if state.get("chosen") else "unrouted"


def _langgraph_available() -> bool:
    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        return False
    return True


def route_knowledge_request(session: Session, kr: KnowledgeRequest) -> RoutingResult:
    """Pick the best-placed expert, record the routing, and queue the notification."""
    if kr.status not in ("open", "routed"):
        return RoutingResult(kr_id=str(kr.id), status=kr.status, reason="already answered")

    requester = session.get(Person, kr.requester_id)
    nodes = _build_nodes(session)
    initial: RoutingState = {
        "kr_id": str(kr.id),
        "question": kr.question,
        "requester_id": str(kr.requester_id),
        "team_id": str(requester.team_id) if requester and requester.team_id else None,
        "tags": list(kr.tags or []),
        "experts": [],
    }

    final = (
        _compiled_graph(*nodes).invoke(initial)
        if _langgraph_available()
        else _plain_flow(initial, *nodes)
    )

    session.refresh(kr)
    chosen = final.get("chosen")
    return RoutingResult(
        kr_id=str(kr.id),
        status=kr.status,
        routed_to=chosen["person_id"] if chosen else None,
        routed_to_name=chosen["name"] if chosen else None,
        reason=final.get("reason", ""),
        tags=list(final.get("tags") or kr.tags or []),
        considered=list(final.get("experts") or []),
    )


def _compiled_graph(node_tag, node_find_experts, node_rank, node_route, node_notify_expert,
                    node_notify_team):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(RoutingState)
    builder.add_node("tag", node_tag)
    builder.add_node("find_experts", node_find_experts)
    builder.add_node("rank", node_rank)
    builder.add_node("route", node_route)
    builder.add_node("notify_expert", node_notify_expert)
    builder.add_node("notify_team", node_notify_team)

    builder.add_edge(START, "tag")
    builder.add_edge("tag", "find_experts")
    builder.add_edge("find_experts", "rank")
    builder.add_conditional_edges(
        "rank", _has_expert, {"route": "route", "unrouted": "notify_team"}
    )
    builder.add_edge("route", "notify_expert")
    builder.add_edge("notify_expert", END)
    builder.add_edge("notify_team", END)
    return builder.compile()


def _plain_flow(state: RoutingState, node_tag, node_find_experts, node_rank, node_route,
                node_notify_expert, node_notify_team) -> RoutingState:
    for node in (node_tag, node_find_experts, node_rank):
        state = {**state, **node(state)}
    if _has_expert(state) == "route":
        state = {**state, **node_route(state)}
        state = {**state, **node_notify_expert(state)}
    else:
        state = {**state, **node_notify_team(state)}
    return state


def answer_knowledge_request(session: Session, kr: KnowledgeRequest, answered_by: Person,
                             answer: str) -> KnowledgeRequest:
    """Capture side of the loop: store, index, credit the answerer, notify the asker."""
    from api.services.expertise_mapper import update_expertise

    now = datetime.now(UTC)
    kr.answer = answer.strip()
    kr.answered_by_id = answered_by.id
    kr.answered_at = now
    kr.status = "answered"
    session.flush()

    index_knowledge_request(session, kr)
    update_expertise(session, answered_by.id, list(kr.tags or []), now)

    session.add(
        Notification(
            person_id=kr.requester_id,
            kind="kr_answered",
            subject="Your question has been answered",
            body=f"{answered_by.display_name} answered: {kr.question}",
            payload={"kr_id": str(kr.id), "answer": kr.answer},
        )
    )
    session.flush()
    return kr


def pending_notifications(session: Session, limit: int = 50) -> list[Notification]:
    return list(
        session.execute(
            select(Notification)
            .where(Notification.status == "pending")
            .order_by(Notification.created_at)
            .limit(limit)
        ).scalars()
    )
