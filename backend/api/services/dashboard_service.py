"""Team pulse and activity aggregation (blueprint section 10).

A dashboard that invents numbers is worse than one that admits a gap, so every
metric here reports what the ingested sources can actually support:
`data_coverage` says which of the four streams have landed, and metrics that
need a stream we do not have yet come back as null with an alert explaining why.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.timeutil import to_utc
from api.models.orm import (
    ExpertiseScore,
    IngestionState,
    KnowledgeRequest,
    Person,
    WorkArtifact,
)

# A pull request open this long without merging is worth surfacing.
STALE_PR_DAYS = 5
# No connector run in this long means ingestion is probably broken.
INGESTION_SILENCE_HOURS = 24
KR_UNANSWERED_DAYS = 3

ACTIVITY_TYPES = {
    "commits": "commit",
    "prs": "pull_request",
    "tickets": "work_item",
    "emails": "email_thread",
    "meetings": "meeting_transcript",
}
SOURCES = ("git", "task", "email", "call")


@dataclass(slots=True)
class Alert:
    severity: str  # 'info' | 'warn' | 'error'
    title: str
    detail: str


@dataclass(slots=True)
class Contributor:
    person_id: str
    name: str
    email: str
    role: str
    commits: int
    prs: int
    total: int
    level: str  # 'high' | 'normal' | 'low' | 'quiet'
    last_seen: str | None


@dataclass(slots=True)
class Highlight:
    title: str
    author: str | None
    date: str | None
    type: str
    reference: str | None


@dataclass(slots=True)
class TeamPulse:
    window_days: int
    generated_at: str
    weekly_activity: dict[str, int]
    totals: dict[str, int]
    on_track_percent: float | None
    blocked_count: int | None
    stale_count: int
    open_prs: int
    merged_prs: int
    contributors: list[Contributor]
    highlights: list[Highlight]
    alerts: list[Alert]
    data_coverage: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


def _window_start(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _scoped(stmt, team_id: uuid.UUID | None):
    return stmt.where(WorkArtifact.team_id == team_id) if team_id else stmt


def _reference(artifact: WorkArtifact) -> str | None:
    meta = artifact.meta or {}
    if artifact.artifact_type == "commit" and meta.get("sha"):
        return f"{meta.get('repo', 'repo')}@{str(meta['sha'])[:8]}"
    if artifact.artifact_type == "pull_request" and meta.get("pr_id"):
        return f"{meta.get('repo', 'repo')} PR #{meta['pr_id']}"
    return meta.get("repo")


def data_coverage(session: Session, team_id: uuid.UUID | None = None) -> dict[str, bool]:
    rows = session.execute(
        _scoped(select(WorkArtifact.source).distinct(), team_id)
    ).scalars()
    present = set(rows)
    return {source: source in present for source in SOURCES}


def activity_counts(session: Session, team_id: uuid.UUID | None, since: datetime) -> dict[str, int]:
    rows = session.execute(
        _scoped(
            select(WorkArtifact.artifact_type, func.count(WorkArtifact.id)).where(
                WorkArtifact.occurred_at >= since
            ),
            team_id,
        ).group_by(WorkArtifact.artifact_type)
    ).all()
    by_type = dict(rows)
    return {key: int(by_type.get(value, 0)) for key, value in ACTIVITY_TYPES.items()}


def _pr_state(session: Session, team_id: uuid.UUID | None) -> tuple[int, int, int]:
    """(open, merged, stale) across all ingested pull requests."""
    prs = session.execute(
        _scoped(
            select(WorkArtifact).where(WorkArtifact.artifact_type == "pull_request"), team_id
        )
    ).scalars()
    cutoff = _window_start(STALE_PR_DAYS)
    open_count = merged_count = stale_count = 0
    for pr in prs:
        status = str((pr.meta or {}).get("status") or "").lower()
        if status in ("completed", "merged", "closed"):
            merged_count += 1
            continue
        open_count += 1
        occurred = to_utc(pr.occurred_at)
        if occurred and occurred < cutoff:
            stale_count += 1
    return open_count, merged_count, stale_count


def _contributors(session: Session, team_id: uuid.UUID | None,
                  since: datetime) -> list[Contributor]:
    rows = session.execute(
        _scoped(
            select(
                Person.id,
                Person.display_name,
                Person.email,
                Person.role,
                WorkArtifact.artifact_type,
                func.count(WorkArtifact.id),
                func.max(WorkArtifact.occurred_at),
            )
            .join(Person, Person.id == WorkArtifact.author_id)
            .where(WorkArtifact.occurred_at >= since),
            team_id,
        ).group_by(Person.id, Person.display_name, Person.email, Person.role,
                   WorkArtifact.artifact_type)
    ).all()

    merged: dict[uuid.UUID, dict[str, Any]] = {}
    for person_id, name, email, role, artifact_type, count, last_seen in rows:
        entry = merged.setdefault(
            person_id,
            {"name": name, "email": email, "role": role, "commits": 0, "prs": 0,
             "total": 0, "last_seen": None},
        )
        if artifact_type == "commit":
            entry["commits"] += count
        elif artifact_type == "pull_request":
            entry["prs"] += count
        entry["total"] += count
        last_seen = to_utc(last_seen)
        if last_seen and (entry["last_seen"] is None or last_seen > entry["last_seen"]):
            entry["last_seen"] = last_seen

    if not merged:
        return []

    totals = sorted(entry["total"] for entry in merged.values())
    median = totals[len(totals) // 2]

    contributors = [
        Contributor(
            person_id=str(person_id),
            name=entry["name"],
            email=entry["email"],
            role=entry["role"],
            commits=entry["commits"],
            prs=entry["prs"],
            total=entry["total"],
            level=_activity_level(entry["total"], median),
            last_seen=entry["last_seen"].date().isoformat() if entry["last_seen"] else None,
        )
        for person_id, entry in merged.items()
    ]
    contributors.sort(key=lambda item: item.total, reverse=True)
    return contributors


def _activity_level(total: int, median: int) -> str:
    """Relative volume only -- never a productivity judgement."""
    if total == 0:
        return "quiet"
    if median and total >= median * 2:
        return "high"
    if median and total <= max(1, median // 2):
        return "low"
    return "normal"


def _highlights(session: Session, team_id: uuid.UUID | None, since: datetime,
                limit: int = 5) -> list[Highlight]:
    artifacts = session.execute(
        _scoped(
            select(WorkArtifact)
            .where(WorkArtifact.occurred_at >= since)
            .order_by(WorkArtifact.occurred_at.desc())
            .limit(limit),
            team_id,
        )
    ).scalars()
    return [
        Highlight(
            title=artifact.title or "(no title)",
            author=artifact.author.display_name if artifact.author else None,
            date=artifact.occurred_at.date().isoformat() if artifact.occurred_at else None,
            type=artifact.artifact_type,
            reference=_reference(artifact),
        )
        for artifact in artifacts
    ]


def _alerts(session: Session, team_id: uuid.UUID | None, coverage: dict[str, bool],
            stale_prs: int) -> list[Alert]:
    alerts: list[Alert] = []

    for state in session.execute(select(IngestionState)).scalars():
        if state.last_status == "error":
            alerts.append(
                Alert("error", f"Connector failing: {state.connector}",
                      (state.last_error or "no detail")[:200])
            )
            continue
        last_run = to_utc(state.last_run_at)
        if last_run and last_run < datetime.now(UTC) - timedelta(
            hours=INGESTION_SILENCE_HOURS
        ):
            alerts.append(
                Alert("warn", f"No ingestion for {state.connector}",
                      f"Last run {last_run.date().isoformat()}.")
            )

    if stale_prs:
        alerts.append(
            Alert("warn", f"{stale_prs} pull request(s) open over {STALE_PR_DAYS} days",
                  "Open PRs with no merge. Check whether they are waiting on review.")
        )

    stale_krs = session.execute(
        select(func.count(KnowledgeRequest.id)).where(
            KnowledgeRequest.status.in_(["open", "routed"]),
            KnowledgeRequest.created_at < datetime.now(UTC)
            - timedelta(days=KR_UNANSWERED_DAYS),
        )
    ).scalar_one()
    if stale_krs:
        alerts.append(
            Alert("warn", f"{stale_krs} Knowledge Request(s) unanswered",
                  f"Open longer than {KR_UNANSWERED_DAYS} days.")
        )

    missing = [source for source, present in coverage.items() if not present]
    if missing:
        alerts.append(
            Alert(
                "info",
                f"{len(missing)} data stream(s) not connected",
                "Missing: " + ", ".join(missing)
                + ". Task-level metrics stay unavailable until Azure DevOps is connected.",
            )
        )
    return alerts


def team_pulse(session: Session, team_id: uuid.UUID | None = None,
               window_days: int = 7) -> TeamPulse:
    since = _window_start(window_days)
    coverage = data_coverage(session, team_id)
    open_prs, merged_prs, stale_prs = _pr_state(session, team_id)

    total_artifacts = session.execute(
        _scoped(select(func.count(WorkArtifact.id)), team_id)
    ).scalar_one()
    people_stmt = select(func.count(Person.id))
    if team_id:
        people_stmt = people_stmt.where(Person.team_id == team_id)

    # Task state is the only honest source for "on track" -- without the Azure
    # DevOps connector there is nothing to divide, so report null, not a guess.
    on_track: float | None = None
    blocked: int | None = None
    if coverage.get("task"):
        states = session.execute(
            _scoped(
                select(WorkArtifact.meta).where(WorkArtifact.artifact_type == "work_item"),
                team_id,
            )
        ).scalars()
        counts: Counter[str] = Counter()
        for meta in states:
            counts[str((meta or {}).get("state") or "unknown").lower()] += 1
        total_tasks = sum(counts.values())
        blocked = counts.get("blocked", 0)
        if total_tasks:
            done = counts.get("closed", 0) + counts.get("done", 0) + counts.get("resolved", 0)
            on_track = round(100.0 * done / total_tasks, 1)

    return TeamPulse(
        window_days=window_days,
        generated_at=datetime.now(UTC).isoformat(),
        weekly_activity=activity_counts(session, team_id, since),
        totals={
            "artifacts": int(total_artifacts),
            "people": int(session.execute(people_stmt).scalar_one()),
            "open_knowledge_requests": int(
                session.execute(
                    select(func.count(KnowledgeRequest.id)).where(
                        KnowledgeRequest.status.in_(["open", "routed"])
                    )
                ).scalar_one()
            ),
        },
        on_track_percent=on_track,
        blocked_count=blocked,
        stale_count=stale_prs,
        open_prs=open_prs,
        merged_prs=merged_prs,
        contributors=_contributors(session, team_id, since),
        highlights=_highlights(session, team_id, since),
        alerts=_alerts(session, team_id, coverage, stale_prs),
        data_coverage=coverage,
    )


def activity_breakdown(session: Session, team_id: uuid.UUID | None = None,
                       weeks: int = 8) -> list[dict[str, Any]]:
    """Per-ISO-week counts per stream. Bucketed in Python so it works on both
    SQLite and Postgres without dialect-specific date truncation."""
    since = _window_start(weeks * 7)
    rows = session.execute(
        _scoped(
            select(WorkArtifact.artifact_type, WorkArtifact.occurred_at).where(
                WorkArtifact.occurred_at >= since
            ),
            team_id,
        )
    ).all()

    buckets: dict[date, Counter[str]] = defaultdict(Counter)
    for artifact_type, occurred_at in rows:
        occurred = to_utc(occurred_at)
        if not occurred:
            continue
        day = occurred.date()
        week_start = day - timedelta(days=day.weekday())
        buckets[week_start][artifact_type] += 1

    today = datetime.now(UTC).date()
    current_week = today - timedelta(days=today.weekday())
    series: list[dict[str, Any]] = []
    for index in range(weeks - 1, -1, -1):
        week_start = current_week - timedelta(weeks=index)
        counts = buckets.get(week_start, Counter())
        series.append(
            {
                "week": week_start.isoformat(),
                **{
                    key: int(counts.get(artifact_type, 0))
                    for key, artifact_type in ACTIVITY_TYPES.items()
                },
                "total": int(sum(counts.values())),
            }
        )
    return series


def expertise_map(session: Session, team_id: uuid.UUID | None = None,
                  min_score: float = 0.1, limit: int = 120) -> dict[str, Any]:
    """Topic -> people graph for the expertise view."""
    stmt = (
        select(ExpertiseScore, Person)
        .join(Person, Person.id == ExpertiseScore.person_id)
        .where(ExpertiseScore.score >= min_score)
        .order_by(ExpertiseScore.score.desc())
        .limit(limit)
    )
    if team_id:
        stmt = stmt.where(Person.team_id == team_id)

    people: dict[str, dict[str, Any]] = {}
    topics: Counter[str] = Counter()
    links: list[dict[str, Any]] = []
    topic_owners: dict[str, set[str]] = defaultdict(set)

    for score_row, person in session.execute(stmt).all():
        person_key = str(person.id)
        people.setdefault(
            person_key,
            {"id": person_key, "name": person.display_name, "email": person.email,
             "role": person.role, "topics": 0},
        )
        people[person_key]["topics"] += 1
        topics[score_row.topic] += 1
        topic_owners[score_row.topic].add(person_key)
        links.append(
            {
                "person_id": person_key,
                "person": person.display_name,
                "topic": score_row.topic,
                "score": round(score_row.score, 3),
                "evidence_count": score_row.evidence_count,
                "last_seen": score_row.last_seen.date().isoformat()
                if score_row.last_seen
                else None,
            }
        )

    return {
        "people": sorted(people.values(), key=lambda item: item["topics"], reverse=True),
        "topics": [
            {"topic": topic, "people": len(topic_owners[topic]), "links": count}
            for topic, count in topics.most_common()
        ],
        "links": links,
        "solo_topics": sorted(
            topic for topic, owners in topic_owners.items() if len(owners) == 1
        ),
    }
