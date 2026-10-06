"""What Claude can ask Hive, and how the answers are worded.

No `mcp` import anywhere in this file. Same split as the Teams bot: every
decision lives in plain sync Python so the whole surface is testable without the
SDK installed, and mcp_server/app.py is a thin transport over it.

Answers come back as text rather than JSON on purpose -- these are read by a
model mid-task, and a paragraph naming the person, the file and the reference is
more actionable than a nested object it has to re-serialise into prose. Every
claim carries its provenance, and when Hive has nothing it says so plainly
instead of returning an empty list that reads like a negative result.
"""

from __future__ import annotations

import functools
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.core.db import session_scope
from api.core.security import has_permission, resolve_dev_user
from api.models.orm import Person
from api.services.dependencies import blast_radius, known_repos
from api.services.expertise_mapper import find_experts
from api.services.kr_manager import UNROUTED_NOTE, create_knowledge_request, routed_note
from api.services.prior_art import area_briefing, days_since, find_prior_art
from api.services.query_engine import answer_query

logger = logging.getLogger("hive.mcp")

SURFACE = "mcp"
NOTHING_FOUND = (
    "Hive has no evidence on this in the team's work trail. That is a genuine gap, not a "
    "search failure -- nobody has committed, reviewed or documented anything matching it. "
    "Use hive_raise_request to record it so it gets routed to whoever is best placed to answer."
)


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., str]


def _safe(handler: Callable[..., str]) -> Callable[..., str]:
    """Turn any exception into a sentence.

    A raise reaches the model as a protocol error it cannot read or recover
    from; a sentence saying what broke is something it can act on. This lives
    here rather than in the transport so it holds for the CLI too, and so
    `functools.wraps` keeps the real signature -- FastMCP builds each tool's
    input schema from it, and a `**kwargs` wrapper would publish a tool whose
    only argument is `kwargs`.
    """

    @functools.wraps(handler)
    def guarded(*args: Any, **kwargs: Any) -> str:
        try:
            return handler(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - unreadable to a model as a raise
            logger.exception("hive tool %s failed", handler.__name__)
            return (
                f"Hive could not answer that: {type(exc).__name__}: {exc}. "
                "The error is logged server-side. Nothing was changed."
            )

    return guarded


def _identity(session: Session) -> Person:
    """Who is asking.

    The MCP server runs on the developer's own machine, so the local identity is
    the developer: DEV_USER_EMAIL, exactly as the CLI resolves it. That is what
    sets the scope below and what lands in the audit log.
    """
    return resolve_dev_user(session)


def _scope(user: Person) -> uuid.UUID | None:
    """Which team's trail to search. None means the whole org.

    These tools deliberately reach org-wide where the role allows it, unlike the
    dashboard, which defaults a member to their own team. The reason is the
    question being asked: "has anyone here solved this" and "what else breaks if
    I change this" are worthless answered inside one team's boundary -- the
    service that depends on yours is usually owned by somebody else. Gated on the
    existing `can_query_org` permission rather than a new rule of its own, so the
    role table stays the only place scope policy is decided.
    """
    return None if has_permission(user.role, "can_query_org") else user.team_id


def _scope_name(user: Person) -> str:
    return "org" if _scope(user) is None else "team"


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _describe(occurrence, index: int) -> str:
    """One prior-art hit, as a block a model can act on without a follow-up call."""
    who = occurrence.person or "unknown author"
    when = occurrence.date or "undated"
    ago = days_since(occurrence.date)
    when = f"{when} ({ago}d ago)" if ago is not None else when

    head = f"{index}. {who} — {occurrence.what}"
    detail = [f"   when: {when}"]
    if occurrence.repo:
        detail.append(f"   repo: {occurrence.repo}")
    if occurrence.reference:
        detail.append(f"   reference: {occurrence.reference}")
    if occurrence.files:
        detail.append(f"   files: {', '.join(occurrence.files)}")
    if occurrence.detail:
        detail.append(f"   what changed: {occurrence.detail}")
    return "\n".join([head, *detail])


# --- tools -----------------------------------------------------------------------


def prior_art(problem: str) -> str:
    """Has anyone on the team hit this before, and what did they do about it?"""
    with session_scope() as session:
        user = _identity(session)
        found = find_prior_art(session, problem, team_id=_scope(user), scope=_scope_name(user))

        if not found.found:
            return f"No prior art for: {problem}\n\n{NOTHING_FOUND}"

        blocks: list[str] = [f"Prior art for: {found.problem}"]

        if found.answers:
            blocks.append("\nAlready answered in the knowledge repo:")
            for entry in found.answers:
                by = f" (answered by {entry.answered_by})" if entry.answered_by else ""
                blocks.append(f"- {entry.question}{by}\n  {entry.answer}")

        if found.occurrences:
            blocks.append("\nTimes the team touched this, most recent first:")
            blocks.extend(
                _describe(occurrence, index)
                for index, occurrence in enumerate(found.occurrences, start=1)
            )

        if found.divergent:
            blocks.append(
                f"\nNote: {len(found.people)} different people ({', '.join(found.people)}) "
                "worked on this, so there may be more than one approach in play. Compare the "
                "entries above before assuming the most recent one is the agreed pattern."
            )
        blocks.append(
            "\nThis is retrieved evidence, not a verified fix — read the referenced change "
            "before applying it."
        )
        return "\n".join(blocks)


def blast_radius_of(target: str) -> str:
    """What else is likely to move if I change this, and who should know?"""
    with session_scope() as session:
        user = _identity(session)
        radius = blast_radius(session, target, team_id=_scope(user))

        repos = known_repos(session, _scope(user))
        if radius.target not in repos:
            listed = ", ".join(repos) or "none ingested yet"
            return (
                f"Hive has no ingested work for '{target}'.\n"
                f"Known repos: {listed}\n"
                "Pass a repo name or a file path inside one."
            )

        blocks = [f"Blast radius for {radius.target} (last {radius.window_days} days)"]

        if radius.owners:
            blocks.append("\nWho works here:")
            blocks.append(
                _bullet(
                    [
                        f"{owner.name} <{owner.email}> — {owner.artifacts} change(s), "
                        f"last {owner.last_seen or 'unknown'}"
                        for owner in radius.owners
                    ]
                )
            )
        else:
            blocks.append("\nNobody has changed this in the window.")

        if not radius.coupled:
            blocks.append(
                "\nNo other repo shows coupling to this one. Either it is genuinely "
                "standalone, or the connectors have not ingested the repos that depend on it."
            )
        else:
            blocks.append("\nRepos that move with it, strongest signal first:")
            for coupling in radius.coupled:
                owners = radius.owners_by_repo.get(coupling.other) or []
                tell = (
                    ", ".join(f"{owner.name} <{owner.email}>" for owner in owners)
                    or "no recent contributor"
                )
                blocks.append(
                    f"- {coupling.other} (strength {coupling.strength})\n"
                    f"  evidence: {coupling.why()}\n"
                    f"  worth telling: {tell}"
                )

        blocks.append(
            "\nHow to read this: Hive parses no manifests and no import graph. Coupling is "
            "inferred from the work trail — who changes both repos, in the same week, and "
            "which commits name the other repo. Treat it as a prompt to check, not proof of "
            "a dependency."
        )
        return "\n".join(blocks)


def area_brief(area: str) -> str:
    """Orient me in a part of the codebase I have never worked in."""
    with session_scope() as session:
        user = _identity(session)
        brief = area_briefing(session, area, team_id=_scope(user))

        if not brief.contributors and not brief.recent_work:
            return f"No ingested work under '{area}'.\n\n{NOTHING_FOUND}"

        ago = days_since(brief.last_touched)
        blocks = [
            f"Briefing on {brief.area} (matched as a {brief.resolved_as})",
            f"Last touched: {brief.last_touched or 'unknown'}"
            + (f" ({ago}d ago)" if ago is not None else ""),
        ]

        if brief.contributors:
            blocks.append("\nPeople who have worked here:")
            blocks.append(
                _bullet(
                    [
                        f"{person['name']} — {person['artifacts']} change(s), "
                        f"last {person['last_seen'] or 'unknown'}"
                        for person in brief.contributors
                    ]
                )
            )

        if brief.problems_solved:
            blocks.append("\nProblems already solved here, and by whom:")
            for entry in brief.problems_solved:
                by = f" — {entry.answered_by}" if entry.answered_by else ""
                blocks.append(f"- {entry.question}{by}\n  {entry.answer}")
        else:
            blocks.append(
                "\nNo answered Knowledge Requests touch this area yet — so the problems "
                "people hit here have not been written down anywhere Hive can see."
            )

        if brief.recent_work:
            blocks.append("\nMost recent changes:")
            blocks.extend(
                _describe(occurrence, index)
                for index, occurrence in enumerate(brief.recent_work, start=1)
            )
        return "\n".join(blocks)


def who_knows(topic: str) -> str:
    """Who has evidence of knowing this topic?"""
    with session_scope() as session:
        user = _identity(session)
        experts = find_experts(session, topic, limit=5, team_id=_scope(user))
        if not experts:
            return f"Nobody has scored evidence on '{topic}'.\n\n{NOTHING_FOUND}"
        return f"People with evidence on '{topic}':\n" + _bullet(
            [
                f"{expert.display_name} <{expert.email}> — score {expert.score:.2f}, "
                f"{expert.evidence_count} artifact(s), last seen "
                f"{expert.last_seen.date().isoformat() if expert.last_seen else 'unknown'}"
                f" (topics: {', '.join(expert.topics[:4])})"
                for expert in experts
            ]
        )


def ask(question: str) -> str:
    """Ask Hive anything about the team's work; answers carry their sources."""
    with session_scope() as session:
        user = _identity(session)
        result = answer_query(
            session,
            question,
            user_id=user.id,
            team_id=_scope(user),
            scope=_scope_name(user),
            surface=SURFACE,
        )
        blocks = [result.answer]
        if result.sources:
            blocks.append("\nSources:")
            blocks.append(
                _bullet(
                    [
                        f"{source.type} | {source.author or 'unknown'} | "
                        f"{source.date or '-'}"
                        f"{f' | {source.reference}' if source.reference else ''} — "
                        f"{source.title}"
                        for source in result.sources[:8]
                    ]
                )
            )
        if result.has_gap:
            blocks.append(
                "\nHive flagged this as a gap. hive_raise_request records it and routes it."
            )
        return "\n".join(blocks)


def raise_request(question: str, context: str | None = None) -> str:
    """Record a knowledge gap and route it to the best-placed expert."""
    question = (question or "").strip()
    if len(question) < 3:
        return "A Knowledge Request needs an actual question."

    with session_scope() as session:
        user = _identity(session)
        kr = create_knowledge_request(session, user.id, question, context)
        expert = session.get(Person, kr.routed_to_id) if kr.routed_to_id else None
        note = (
            routed_note(expert.display_name, "they have the strongest recent evidence")
            if expert
            else UNROUTED_NOTE
        )
        tags = ", ".join(kr.tags or []) or "none"
        return (
            f"Knowledge Request recorded.\n"
            f"  id: {kr.id}\n"
            f"  question: {kr.question}\n"
            f"  tags: {tags}\n"
            f"  {note}"
        )


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="hive_prior_art",
        description=(
            "Check whether this team has already hit a given error, bug or problem. Pass the "
            "error text, stack trace line or a description of the symptom. Returns who dealt "
            "with it, what they changed, the file and the commit/PR reference, newest first, "
            "and flags when different people took different approaches. Use this BEFORE "
            "debugging something from scratch."
        ),
        handler=_safe(prior_art),
    ),
    ToolSpec(
        name="hive_blast_radius",
        description=(
            "Before changing a service, find out what else moves with it and who to tell. "
            "Pass a repo name or a file path. Returns the repos coupled to it with the "
            "evidence behind each (shared contributors, co-change, cross-references) and the "
            "people who actually work in them. Coupling is inferred from the work trail, not "
            "from a manifest or import graph."
        ),
        handler=_safe(blast_radius_of),
    ),
    ToolSpec(
        name="hive_area_briefing",
        description=(
            "Orient yourself in an unfamiliar part of the codebase. Pass a repo name, a "
            "directory path or a topic. Returns who has worked there, the problems already "
            "solved there and by whom, and the most recent changes. Use this when picking up "
            "a ticket in code you have not touched."
        ),
        handler=_safe(area_brief),
    ),
    ToolSpec(
        name="hive_who_knows",
        description=(
            "Find who has demonstrable evidence of knowing a topic, service or technology, "
            "scored from their actual commits and answered questions rather than self-report."
        ),
        handler=_safe(who_knows),
    ),
    ToolSpec(
        name="hive_ask",
        description=(
            "Ask a free-form question about the team's work trail: commits, pull requests, "
            "tickets and answered questions. Every answer cites the artifacts behind it. Use "
            "the more specific tools first where they fit."
        ),
        handler=_safe(ask),
    ),
    ToolSpec(
        name="hive_raise_request",
        description=(
            "Record a knowledge gap when Hive has no answer, and route it to the best-placed "
            "expert. This is the only tool that writes anything. Use it when the other tools "
            "come back empty, so the next person asking gets an answer instead of the gap."
        ),
        handler=_safe(raise_request),
    ),
]

TOOLS_BY_NAME = {spec.name: spec for spec in TOOLS}


def dispatch(name: str, **kwargs: Any) -> str:
    """Call a tool by name. The transport and the tests share this entry point."""
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        return f"Unknown tool '{name}'. Available: {', '.join(sorted(TOOLS_BY_NAME))}"
    return spec.handler(**kwargs)


def warm_providers() -> None:
    """Force the heavy providers to load on the main thread, at boot.

    Not an optimisation -- a correctness fix. The MCP runtime executes sync tools
    in an anyio worker thread, and the first tool call would otherwise be the
    thing that first imports chromadb (and through it numpy's C extensions).
    Importing a C extension from a worker thread while the main thread is inside
    the event loop deadlocks on the import lock: the call never returns and the
    client waits forever with no error to show.

    Doing it here, before the loop starts, also means the first question a
    developer asks is not the one that pays the import cost.
    """
    from api.core.embeddings import get_embedder
    from api.core.vectorstore import get_vector_store

    for load in (get_embedder, get_vector_store):
        try:
            load()
        except Exception:  # noqa: BLE001 - surface per-tool, do not block startup
            logger.warning("could not warm %s", load.__name__, exc_info=True)


def server_banner() -> str:
    """One line of provenance, so the operator can see what they connected to."""
    settings = get_settings()
    with session_scope() as session:
        user = _identity(session)
        team = user.team.name if user.team else "no team"
    return (
        f"Hive MCP: {len(TOOLS)} tools | identity {user.email} ({team}) | "
        f"llm={settings.llm_provider} vectors={settings.vector_provider} "
        f"graph={settings.graph_provider}"
    )


__all__ = ["TOOLS", "TOOLS_BY_NAME", "ToolSpec", "dispatch", "server_banner"]
