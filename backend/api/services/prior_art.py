"""Prior art: has anyone on this team already solved this?

The question an engineer asks mid-task is not "summarise our billing work" but
"I am staring at this error -- has someone seen it before, what did they do, and
where". That needs a different shape from the Q&A engine: grouped by *person*,
carrying the file that changed and the reference to point at, and explicit when
two people solved the same thing two different ways.

Retrieval is the existing hybrid pass, so prior art stays as good as the rest of
the search and inherits the relevance floor -- a near-miss commit presented as
"someone fixed this" is worse than saying nobody has.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.timeutil import to_utc
from api.models.orm import KnowledgeRequest, Person, WorkArtifact
from api.services.query_engine import _reference as artifact_reference
from api.services.query_engine import retrieve, retrieve_knowledge_repo

MAX_FILES_SHOWN = 6


@dataclass(slots=True)
class Occurrence:
    """One time somebody dealt with this, and what they left behind."""

    person: str | None
    person_email: str | None
    what: str
    detail: str
    repo: str | None
    files: list[str]
    reference: str | None
    date: str | None
    artifact_type: str
    relevance: float


@dataclass(slots=True)
class AnsweredQuestion:
    question: str
    answer: str
    answered_by: str | None
    relevance: float


@dataclass(slots=True)
class PriorArt:
    problem: str
    occurrences: list[Occurrence] = field(default_factory=list)
    answers: list[AnsweredQuestion] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.occurrences or self.answers)

    @property
    def people(self) -> list[str]:
        seen = {occurrence.person for occurrence in self.occurrences if occurrence.person}
        return sorted(seen)

    @property
    def divergent(self) -> bool:
        """Two or more people took a run at this -- their approaches may differ."""
        return len(self.people) > 1


@dataclass(slots=True)
class AreaBriefing:
    area: str
    resolved_as: str  # 'repo' | 'path' | 'topic'
    contributors: list[dict] = field(default_factory=list)
    recent_work: list[Occurrence] = field(default_factory=list)
    problems_solved: list[AnsweredQuestion] = field(default_factory=list)
    last_touched: str | None = None


def _files_of(meta: dict | None) -> list[str]:
    files = (meta or {}).get("files_changed") or []
    return [str(path) for path in files][:MAX_FILES_SHOWN]


def _occurrence(artifact: WorkArtifact, excerpt: str, relevance: float) -> Occurrence:
    meta = artifact.meta or {}
    return Occurrence(
        person=artifact.author.display_name if artifact.author else None,
        person_email=artifact.author.email if artifact.author else None,
        what=artifact.title or "(no title)",
        detail=excerpt.strip(),
        repo=str(meta.get("repo")) if meta.get("repo") else None,
        files=_files_of(meta),
        reference=artifact_reference(artifact),
        date=artifact.occurred_at.date().isoformat() if artifact.occurred_at else None,
        artifact_type=artifact.artifact_type,
        relevance=relevance,
    )


def find_prior_art(
    session: Session,
    problem: str,
    team_id: uuid.UUID | None = None,
    scope: str = "team",
    limit: int = 6,
) -> PriorArt:
    """Search the work trail and the knowledge repo for previous encounters."""
    problem = (problem or "").strip()
    if not problem:
        return PriorArt(problem="")

    candidates = retrieve(session, problem, team_id=team_id, scope=scope, top_k=limit * 2)
    answers = retrieve_knowledge_repo(session, problem)

    occurrences = [
        _occurrence(candidate.artifact, candidate.excerpt, candidate.score)
        for candidate in candidates
    ]
    # Newest first within the relevance set: the most recent fix is the one to try.
    occurrences.sort(key=lambda item: (item.date or "", item.relevance), reverse=True)

    return PriorArt(
        problem=problem,
        occurrences=occurrences[:limit],
        answers=[
            AnsweredQuestion(
                question=entry["question"],
                answer=entry["answer"],
                answered_by=entry["answered_by"] or None,
                relevance=entry["score"],
            )
            for entry in answers
        ],
    )


def _artifacts_in_area(
    session: Session, area: str, team_id: uuid.UUID | None
) -> tuple[list[WorkArtifact], str]:
    """Resolve an area to its artifacts. Repo name, path prefix, or free text."""
    stmt = select(WorkArtifact).order_by(WorkArtifact.occurred_at.desc())
    if team_id:
        stmt = stmt.where(WorkArtifact.team_id == team_id)
    everything = list(session.execute(stmt).scalars())

    needle = area.strip().replace("\\", "/")
    lowered = needle.lower()

    by_repo = [a for a in everything if str((a.meta or {}).get("repo") or "").lower() == lowered]
    if by_repo:
        return by_repo, "repo"

    if "/" in needle or "." in needle:
        by_path = [
            artifact
            for artifact in everything
            if any(
                str(path).replace("\\", "/").lower().startswith(lowered)
                for path in (artifact.meta or {}).get("files_changed") or []
            )
        ]
        if by_path:
            return by_path, "path"

    return [], "topic"


def area_briefing(
    session: Session,
    area: str,
    team_id: uuid.UUID | None = None,
    limit: int = 6,
) -> AreaBriefing:
    """Orient someone who has never worked in this part of the codebase."""
    artifacts, resolved_as = _artifacts_in_area(session, area, team_id)

    if resolved_as == "topic":
        # Not a repo or a path we know -- fall back to the search engine.
        prior = find_prior_art(session, area, team_id=team_id, limit=limit)
        contributors: dict[str, dict] = {}
        for occurrence in prior.occurrences:
            if not occurrence.person:
                continue
            entry = contributors.setdefault(
                occurrence.person, {"name": occurrence.person, "artifacts": 0, "last_seen": None}
            )
            entry["artifacts"] += 1
            if occurrence.date and (
                entry["last_seen"] is None or occurrence.date > entry["last_seen"]
            ):
                entry["last_seen"] = occurrence.date
        return AreaBriefing(
            area=area,
            resolved_as="topic",
            contributors=sorted(
                contributors.values(), key=lambda item: item["artifacts"], reverse=True
            ),
            recent_work=prior.occurrences,
            problems_solved=prior.answers,
            last_touched=max(
                (o.date for o in prior.occurrences if o.date), default=None
            ),
        )

    tally: dict[uuid.UUID, dict] = {}
    for artifact in artifacts:
        if artifact.author_id is None:
            continue
        entry = tally.setdefault(
            artifact.author_id,
            {
                "name": artifact.author.display_name if artifact.author else "unknown",
                "artifacts": 0,
                "last_seen": None,
            },
        )
        entry["artifacts"] += 1
        moment = to_utc(artifact.occurred_at)
        stamp = moment.date().isoformat() if moment else None
        if stamp and (entry["last_seen"] is None or stamp > entry["last_seen"]):
            entry["last_seen"] = stamp

    # Problems solved here: answered requests that cite one of these artifacts, or
    # carry a tag this area's artifacts were scored on.
    artifact_ids = {str(artifact.id) for artifact in artifacts}
    area_topics = {
        str(topic)
        for artifact in artifacts
        for topic in (artifact.meta or {}).get("topics") or []
    }
    problems: list[AnsweredQuestion] = []
    for kr in session.execute(
        select(KnowledgeRequest).where(KnowledgeRequest.status.in_(["answered", "indexed"]))
    ).scalars():
        cites = artifact_ids.intersection(str(ref) for ref in kr.related_artifacts or [])
        tagged = area_topics.intersection(kr.tags or [])
        if not cites and not tagged:
            continue
        answerer = session.get(Person, kr.answered_by_id) if kr.answered_by_id else None
        problems.append(
            AnsweredQuestion(
                question=kr.question,
                answer=kr.answer or "",
                answered_by=answerer.display_name if answerer else None,
                relevance=1.0 if cites else 0.5,
            )
        )
    problems.sort(key=lambda item: item.relevance, reverse=True)

    recent = [
        _occurrence(artifact, (artifact.content or "")[:240], 1.0) for artifact in artifacts[:limit]
    ]
    return AreaBriefing(
        area=area,
        resolved_as=resolved_as,
        contributors=sorted(tally.values(), key=lambda item: item["artifacts"], reverse=True),
        recent_work=recent,
        problems_solved=problems[:limit],
        last_touched=max((entry["last_seen"] for entry in tally.values() if entry["last_seen"]),
                         default=None),
    )


def days_since(stamp: str | None) -> int | None:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (datetime.now(UTC) - moment).days
