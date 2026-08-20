"""Knowledge Request capture and routing (blueprint section 8).

Creating a request immediately runs the routing graph, so a gap gets an owner
rather than sitting in a queue. Routing itself lives in kr_routing_graph; this
module is the entry point the bot, the API and the dashboard all share.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models.orm import KnowledgeRequest
from api.services.topics import extract_topics

logger = logging.getLogger(__name__)

UNROUTED_NOTE = (
    "Recorded and visible to the team. Nobody has evidence on these topics yet, so it is "
    "open to whoever can answer it."
)


def routed_note(name: str, reason: str) -> str:
    return f"Routed to {name} -- {reason}. They have been notified."


def create_knowledge_request(session: Session, requester_id: uuid.UUID, question: str,
                             context: str | None = None,
                             route: bool = True) -> KnowledgeRequest:
    """Record a knowledge gap and route it. Idempotent per requester on identical
    open questions, so a double-tapped button cannot create two requests."""
    question = (question or "").strip()
    if not question:
        raise ValueError("a Knowledge Request needs a question")

    existing = session.execute(
        select(KnowledgeRequest).where(
            KnowledgeRequest.requester_id == requester_id,
            KnowledgeRequest.question == question,
            KnowledgeRequest.status == "open",
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    kr = KnowledgeRequest(
        requester_id=requester_id,
        question=question,
        context=context,
        status="open",
        tags=extract_topics(question),
    )
    session.add(kr)
    session.flush()

    if route:
        # Imported here: the routing graph imports topics/expertise, which would
        # otherwise close an import cycle back through this module.
        from api.services.kr_routing_graph import route_knowledge_request

        try:
            route_knowledge_request(session, kr)
        except Exception:  # noqa: BLE001 - a failed routing must not lose the request
            logger.exception("routing failed for KR %s; left open", kr.id)
    return kr


def open_requests(session: Session, limit: int = 50) -> list[KnowledgeRequest]:
    return list(
        session.execute(
            select(KnowledgeRequest)
            .where(KnowledgeRequest.status.in_(["open", "routed"]))
            .order_by(KnowledgeRequest.created_at.desc())
            .limit(limit)
        ).scalars()
    )
