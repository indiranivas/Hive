"""Surface-agnostic dispatch for @Hive.

Everything the bot decides happens here, in sync code with no botbuilder import,
so the whole path is testable without the Bot Framework SDK. bot/app.py is a thin
transport shim over this module.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models.orm import Person
from api.services.expertise_mapper import find_experts
from api.services.kr_manager import UNROUTED_NOTE, create_knowledge_request, routed_note
from api.services.query_engine import answer_query
from bot import cards
from bot.commands import Command, parse_command

logger = logging.getLogger(__name__)

SURFACE = "teams"


@dataclass(slots=True)
class BotUser:
    """Who sent the activity, as Teams reports them."""

    aad_object_id: str | None = None
    email: str | None = None
    name: str | None = None


@dataclass(slots=True)
class BotReply:
    kind: str
    card: dict[str, Any] | None = None
    text: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def attachments(self) -> list[dict[str, Any]]:
        return [cards.as_attachment(self.card)] if self.card else []


def resolve_bot_person(session: Session, user: BotUser) -> Person:
    """Map a Teams identity to a person, linking the Entra ID on first contact.

    Commit emails usually created the row long before this, so match on email
    second and backfill azure_ad_id rather than creating a duplicate person.
    """
    person: Person | None = None
    if user.aad_object_id:
        person = session.execute(
            select(Person).where(Person.azure_ad_id == user.aad_object_id)
        ).scalar_one_or_none()

    email = (user.email or "").strip().lower()
    if person is None and email:
        person = session.execute(
            select(Person).where(func.lower(Person.email) == email)
        ).scalar_one_or_none()

    if person is None:
        if not email:
            # Teams did not surface an email (guest or stripped payload). Fall back
            # to a stable synthetic address keyed on the Entra object id.
            email = f"{user.aad_object_id or uuid.uuid4().hex}@teams.local"
        person = Person(
            azure_ad_id=user.aad_object_id,
            email=email,
            display_name=user.name or email,
        )
        session.add(person)
    elif user.aad_object_id and not person.azure_ad_id:
        person.azure_ad_id = user.aad_object_id

    session.flush()
    return person


def _expert_payload(expert) -> dict[str, Any]:
    return {
        "display_name": expert.display_name,
        "email": expert.email,
        "topics": expert.topics,
        "score": round(expert.score, 2),
        "evidence_count": expert.evidence_count,
        "last_seen": expert.last_seen.date().isoformat() if expert.last_seen else None,
    }


def handle_ask(session: Session, person: Person, question: str) -> BotReply:
    result = answer_query(
        session,
        question,
        user_id=person.id,
        team_id=person.team_id,
        scope="team",
        surface=SURFACE,
    )
    payload = result.to_dict()
    return BotReply(
        kind="answer",
        card=cards.answer_card(
            question=question,
            answer=result.answer,
            sources=payload["sources"],
            has_gap=result.has_gap,
            model=result.model,
        ),
        meta={"has_gap": result.has_gap, "sources": len(result.sources)},
    )


def handle_who_knows(session: Session, person: Person, topic: str) -> BotReply:
    if not topic:
        return BotReply(
            kind="notice",
            card=cards.notice_card(
                "Which topic?", 'Try "@Hive who knows billing-service".'
            ),
        )
    experts = find_experts(session, topic, limit=5, team_id=person.team_id)
    return BotReply(
        kind="experts",
        card=cards.experts_card(topic, [_expert_payload(expert) for expert in experts]),
        meta={"experts": len(experts)},
    )


def handle_kr(session: Session, person: Person, question: str,
              context: str | None = None) -> BotReply:
    if not question:
        return BotReply(
            kind="notice",
            card=cards.notice_card(
                "What should I ask?", 'Try "@Hive kr how do we rotate the ADO PAT?".'
            ),
        )
    kr = create_knowledge_request(session, person.id, question, context)
    expert = session.get(Person, kr.routed_to_id) if kr.routed_to_id else None
    note = (
        routed_note(expert.display_name, "they have the strongest recent evidence")
        if expert
        else UNROUTED_NOTE
    )
    return BotReply(
        kind="kr_created",
        card=cards.kr_created_card(
            question=kr.question,
            kr_id=str(kr.id),
            tags=list(kr.tags or []),
            routing_note=note,
        ),
        meta={"kr_id": str(kr.id), "routed_to": expert.display_name if expert else None},
    )


def handle_activity(session: Session, *, text: str | None = None,
                    value: dict[str, Any] | None = None,
                    user: BotUser | None = None) -> BotReply:
    """Single entry point: card action first, then typed text."""
    person = resolve_bot_person(session, user or BotUser())

    if value:
        action = str(value.get("action") or "")
        if action == "raise_kr":
            return handle_kr(
                session, person, str(value.get("question") or ""),
                context=value.get("context"),
            )
        logger.warning("unknown card action: %s", action)
        return BotReply(
            kind="notice",
            card=cards.notice_card("Unknown action", "That button is not wired to anything."),
        )

    command: Command = parse_command(text)
    if command.kind == "help":
        return BotReply(kind="help", card=cards.help_card())
    if command.kind == "who_knows":
        return handle_who_knows(session, person, command.text)
    if command.kind == "kr":
        return handle_kr(session, person, command.text)
    if command.kind == "status":
        return BotReply(
            kind="notice",
            card=cards.notice_card(
                "Auto-status is not built yet",
                "Weekly per-person status arrives in Phase 3. For now ask me a question, "
                'or try "@Hive who knows <topic>".',
            ),
        )
    return handle_ask(session, person, command.text)
