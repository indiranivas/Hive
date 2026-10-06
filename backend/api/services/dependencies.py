"""Repo coupling: what else moves when this moves, and who owns it.

Hive has no manifest parser, so it cannot state that billing *imports*
identity-service. What it can state -- from the work trail alone -- is that the
two repos keep moving together, that four people work in both, and that eleven
commits in one name the other. That is coupling evidence, not a dependency
declaration, and every caller is expected to say so: a graph that guesses at an
import edge is worse than one that shows its working.

Three independent signals, weakest to strongest:

  shared contributors  the same people change both repos at all
  co-change            the same person changes both inside one ISO week
  cross-references     an artifact in one repo names the other in its text

Cross-references need artifact bodies, so they are opt-in: `build_graph` derives
COUPLED_WITH without them and the MCP blast-radius tool asks for them.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.timeutil import to_utc
from api.models.orm import Person, WorkArtifact

# Weights are ordered by how much each signal actually implies a dependency.
CONTRIBUTOR_WEIGHT = 1.0
CO_CHANGE_WEIGHT = 2.0
REFERENCE_WEIGHT = 3.0

DEFAULT_WINDOW_DAYS = 180


@dataclass(slots=True)
class Coupling:
    """One repo's relationship to another, with the evidence behind it."""

    repo: str
    other: str
    shared_contributors: list[str] = field(default_factory=list)
    co_changed_weeks: int = 0
    cross_references: int = 0

    @property
    def strength(self) -> float:
        return round(
            len(self.shared_contributors) * CONTRIBUTOR_WEIGHT
            + self.co_changed_weeks * CO_CHANGE_WEIGHT
            + self.cross_references * REFERENCE_WEIGHT,
            2,
        )

    def why(self) -> str:
        """Plain-language evidence, so a caller never has to infer what it means."""
        parts: list[str] = []
        if self.cross_references:
            parts.append(f"{self.cross_references} commit(s)/PR(s) here name it")
        if self.co_changed_weeks:
            parts.append(f"changed together in {self.co_changed_weeks} week(s)")
        if self.shared_contributors:
            names = ", ".join(self.shared_contributors[:3])
            extra = len(self.shared_contributors) - 3
            parts.append(f"shared contributors: {names}{f' +{extra}' if extra > 0 else ''}")
        return "; ".join(parts) or "no shared signal"


@dataclass(slots=True)
class Owner:
    person_id: str
    name: str
    email: str
    artifacts: int
    last_seen: str | None


@dataclass(slots=True)
class BlastRadius:
    target: str
    kind: str  # 'repo' | 'module'
    window_days: int
    owners: list[Owner] = field(default_factory=list)
    coupled: list[Coupling] = field(default_factory=list)
    owners_by_repo: dict[str, list[Owner]] = field(default_factory=dict)


@dataclass(slots=True)
class _Row:
    """The slice of an artifact this module reasons over."""

    author_id: uuid.UUID | None
    repo: str
    week: str
    text: str


def _iso_week(moment: datetime | None) -> str:
    reference = to_utc(moment) or datetime.now(UTC)
    year, week, _ = reference.isocalendar()
    return f"{year}-W{week:02d}"


def _load_rows(
    session: Session,
    team_id: uuid.UUID | None,
    since: datetime,
    with_text: bool,
) -> list[_Row]:
    columns = [
        WorkArtifact.author_id,
        WorkArtifact.occurred_at,
        WorkArtifact.meta,
        WorkArtifact.title,
    ]
    if with_text:
        # `content` is the largest column in the table; only the reference scan needs it.
        columns.append(WorkArtifact.content)

    stmt = select(*columns).where(WorkArtifact.occurred_at >= since)
    if team_id:
        stmt = stmt.where(WorkArtifact.team_id == team_id)

    rows: list[_Row] = []
    for row in session.execute(stmt).all():
        repo = (row.meta or {}).get("repo")
        if not repo:
            continue
        text = f"{row.title or ''}\n{row.content}" if with_text else ""
        rows.append(
            _Row(
                author_id=row.author_id,
                repo=str(repo),
                week=_iso_week(row.occurred_at),
                text=text.lower(),
            )
        )
    return rows


def coupling_from_rows(rows: list[_Row], names: dict[uuid.UUID, str]) -> list[Coupling]:
    """Contributor and co-change coupling. No artifact bodies required."""
    contributors: dict[str, set[uuid.UUID]] = defaultdict(set)
    weeks: dict[tuple[uuid.UUID, str], set[str]] = defaultdict(set)
    for row in rows:
        if row.author_id is None:
            continue
        contributors[row.repo].add(row.author_id)
        weeks[(row.author_id, row.week)].add(row.repo)

    # A person touching two repos in one week is the co-change signal.
    co_change: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (_, week), touched in weeks.items():
        for left in touched:
            for right in touched:
                if left != right:
                    co_change[(left, right)].add(week)

    couplings: list[Coupling] = []
    for repo, people in contributors.items():
        for other, other_people in contributors.items():
            if repo == other:
                continue
            shared = people & other_people
            overlap_weeks = len(co_change.get((repo, other), ()))
            if not shared and not overlap_weeks:
                continue
            couplings.append(
                Coupling(
                    repo=repo,
                    other=other,
                    shared_contributors=sorted(
                        names.get(person_id, str(person_id)) for person_id in shared
                    ),
                    co_changed_weeks=overlap_weeks,
                )
            )
    return couplings


def _count_references(rows: list[_Row], repos: set[str]) -> dict[tuple[str, str], int]:
    """Artifacts in one repo that name another repo in their text."""
    # Word-boundary match on the repo name, so `billing` does not fire on `rebilling`.
    patterns = {
        repo: re.compile(rf"(?<![\w-]){re.escape(repo.lower())}(?![\w-])") for repo in repos
    }
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        if not row.text:
            continue
        for other, pattern in patterns.items():
            if other != row.repo and pattern.search(row.text):
                counts[(row.repo, other)] += 1
    return counts


def repo_coupling(
    session: Session,
    team_id: uuid.UUID | None = None,
    since_days: int = DEFAULT_WINDOW_DAYS,
    include_references: bool = True,
) -> list[Coupling]:
    """Every coupled repo pair in the window, strongest first."""
    since = datetime.now(UTC) - timedelta(days=since_days)
    rows = _load_rows(session, team_id, since, with_text=include_references)
    names = dict(session.execute(select(Person.id, Person.display_name)).all())

    couplings = coupling_from_rows(rows, names)
    if include_references:
        references = _count_references(rows, {row.repo for row in rows})
        indexed = {(c.repo, c.other): c for c in couplings}
        for (repo, other), count in references.items():
            coupling = indexed.get((repo, other))
            if coupling is None:
                coupling = Coupling(repo=repo, other=other)
                indexed[(repo, other)] = coupling
                couplings.append(coupling)
            coupling.cross_references = count

    couplings.sort(key=lambda c: c.strength, reverse=True)
    return couplings


def repo_owners(
    session: Session,
    repo: str,
    team_id: uuid.UUID | None = None,
    since_days: int = DEFAULT_WINDOW_DAYS,
    limit: int = 3,
) -> list[Owner]:
    """Who actually works in this repo, by volume in the window.

    Deliberately "who has been changing it", not a declared CODEOWNER: Hive only
    knows what the work trail shows.
    """
    since = datetime.now(UTC) - timedelta(days=since_days)
    stmt = (
        select(
            Person.id,
            Person.display_name,
            Person.email,
            WorkArtifact.occurred_at,
            WorkArtifact.meta,
        )
        .join(Person, Person.id == WorkArtifact.author_id)
        .where(WorkArtifact.occurred_at >= since)
    )
    if team_id:
        stmt = stmt.where(WorkArtifact.team_id == team_id)

    tally: dict[uuid.UUID, dict] = {}
    for person_id, name, email, occurred_at, meta in session.execute(stmt).all():
        if str((meta or {}).get("repo") or "") != repo:
            continue
        entry = tally.setdefault(
            person_id, {"name": name, "email": email, "count": 0, "last": None}
        )
        entry["count"] += 1
        moment = to_utc(occurred_at)
        if moment and (entry["last"] is None or moment > entry["last"]):
            entry["last"] = moment

    owners = [
        Owner(
            person_id=str(person_id),
            name=entry["name"],
            email=entry["email"],
            artifacts=entry["count"],
            last_seen=entry["last"].date().isoformat() if entry["last"] else None,
        )
        for person_id, entry in tally.items()
    ]
    owners.sort(key=lambda owner: owner.artifacts, reverse=True)
    return owners[:limit]


def known_repos(session: Session, team_id: uuid.UUID | None = None) -> list[str]:
    stmt = select(WorkArtifact.meta)
    if team_id:
        stmt = stmt.where(WorkArtifact.team_id == team_id)
    repos = {
        str((meta or {}).get("repo"))
        for meta in session.execute(stmt).scalars()
        if (meta or {}).get("repo")
    }
    return sorted(repos)


def blast_radius(
    session: Session,
    target: str,
    team_id: uuid.UUID | None = None,
    since_days: int = DEFAULT_WINDOW_DAYS,
) -> BlastRadius:
    """What else is likely to move when `target` changes, and who to tell."""
    target = target.strip()
    repos = set(known_repos(session, team_id))

    # A file path resolves to the repo that owns it, so callers can pass either.
    kind = "repo"
    if target not in repos:
        head = target.replace("\\", "/").split("/")[0]
        if head in repos:
            target, kind = head, "module"

    couplings = [c for c in repo_coupling(session, team_id, since_days) if c.repo == target]
    return BlastRadius(
        target=target,
        kind=kind,
        window_days=since_days,
        owners=repo_owners(session, target, team_id, since_days),
        coupled=couplings,
        owners_by_repo={
            coupling.other: repo_owners(session, coupling.other, team_id, since_days, limit=2)
            for coupling in couplings
        },
    )
