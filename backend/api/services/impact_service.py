"""Leadership overview: what Hive has captured and what it has saved.

Every figure is counted from rows Hive already holds. The one derived number,
hours saved, is a product of counts and per-event minutes, and the minutes are
returned alongside it so a reader can challenge the assumption instead of
trusting a total. An estimate that hides its inputs is a claim, not a metric.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.timeutil import to_utc
from api.models.orm import (
    ExpertiseScore,
    KnowledgeRequest,
    Person,
    QueryLog,
    StatusReport,
    Team,
    WorkArtifact,
)
from api.services.dashboard_service import SOURCES

ANSWERED_STATUSES = ("answered", "indexed")
# Same threshold the gap analytics use, so the two pages never disagree.
EXPERT_MIN_SCORE = 0.2
# One person holding this share of a repo's work makes it a single point of failure.
CONCENTRATION_RISK_SHARE = 0.6

# Minutes a person would otherwise spend per event. Deliberately conservative.
MINUTES_PER_ANSWERED_QUESTION = 20  # searching repos and chat, or interrupting a colleague
MINUTES_PER_STATUS_REPORT = 15  # a manager compiling one person's weekly update
MINUTES_PER_KNOWLEDGE_ANSWER = 30  # the same question asked again and re-explained


def _questions(session: Session, since: datetime) -> dict[str, Any]:
    logs = list(session.execute(select(QueryLog)).scalars())
    answered = [log for log in logs if (log.sources_used or {}).get("sources")]
    latencies = [log.latency_ms for log in logs if log.latency_ms]
    surfaces: dict[str, int] = defaultdict(int)
    for log in logs:
        surfaces[log.surface] += 1
    recent = [log for log in logs if (to_utc(log.created_at) or since) >= since]
    return {
        "total": len(logs),
        "last_30d": len(recent),
        "answered_with_evidence": len(answered),
        "answer_rate": round(len(answered) / len(logs), 3) if logs else None,
        "median_latency_ms": int(median(latencies)) if latencies else None,
        "by_surface": dict(surfaces),
    }


def _knowledge(session: Session) -> dict[str, Any]:
    requests = list(session.execute(select(KnowledgeRequest)).scalars())
    answered = [kr for kr in requests if kr.status in ANSWERED_STATUSES]
    durations = []
    for kr in answered:
        created, answered_at = to_utc(kr.created_at), to_utc(kr.answered_at)
        if created and answered_at and answered_at >= created:
            durations.append((answered_at - created).total_seconds() / 3600)
    return {
        "answered": len(answered),
        "open": sum(1 for kr in requests if kr.status in ("open", "routed")),
        "median_hours_to_answer": round(median(durations), 1) if durations else None,
    }


def _expertise(session: Session) -> dict[str, Any]:
    topics = session.execute(
        select(func.count(func.distinct(ExpertiseScore.topic))).where(
            ExpertiseScore.score > EXPERT_MIN_SCORE
        )
    ).scalar_one()

    # Concentration is measured per repo, not per topic: extracted topics are
    # fine-grained enough that nearly every one has a single author, which would
    # flag everything and so inform nothing. A repo is a unit a leader can act on.
    names = dict(session.execute(select(Person.id, Person.display_name)).all())
    work: dict[str, dict[uuid.UUID, int]] = defaultdict(lambda: defaultdict(int))
    for meta, author_id in session.execute(select(WorkArtifact.meta, WorkArtifact.author_id)):
        repo = (meta or {}).get("repo")
        if repo and author_id:
            work[repo][author_id] += 1

    areas = []
    for repo, authors in work.items():
        total = sum(authors.values())
        owner, owned = max(authors.items(), key=lambda item: item[1])
        share = owned / total
        areas.append(
            {
                "repo": repo,
                "contributors": len(authors),
                "artifacts": total,
                "top_person": names.get(owner, "unknown"),
                "top_share": round(share, 2),
                "at_risk": share >= CONCENTRATION_RISK_SHARE,
            }
        )
    areas.sort(key=lambda row: row["top_share"], reverse=True)
    return {
        "topics_mapped": topics,
        "areas": areas,
        "areas_at_risk": sum(1 for row in areas if row["at_risk"]),
    }


def _trail(session: Session) -> dict[str, Any]:
    artifacts = session.execute(
        select(
            func.count(WorkArtifact.id),
            func.min(WorkArtifact.occurred_at),
            func.max(WorkArtifact.occurred_at),
        )
    ).one()
    repos = {
        (meta or {}).get("repo")
        for meta in session.execute(select(WorkArtifact.meta)).scalars()
    }
    present = set(session.execute(select(WorkArtifact.source).distinct()).scalars())
    first, last = to_utc(artifacts[1]), to_utc(artifacts[2])
    return {
        "artifacts": int(artifacts[0] or 0),
        "people": session.execute(select(func.count(Person.id))).scalar_one(),
        "teams": session.execute(select(func.count(Team.id))).scalar_one(),
        "repos": len(repos - {None}),
        "sources": {source: source in present for source in SOURCES},
        "first_seen": first.isoformat() if first else None,
        "last_seen": last.isoformat() if last else None,
    }


def leadership_overview(session: Session) -> dict[str, Any]:
    now = datetime.now(UTC)
    questions = _questions(session, now - timedelta(days=30))
    knowledge = _knowledge(session)
    status_reports = session.execute(select(func.count(StatusReport.id))).scalar_one()

    breakdown = [
        {
            "label": "Questions answered with cited evidence",
            "count": questions["answered_with_evidence"],
            "minutes_each": MINUTES_PER_ANSWERED_QUESTION,
        },
        {
            "label": "Weekly status reports drafted",
            "count": status_reports,
            "minutes_each": MINUTES_PER_STATUS_REPORT,
        },
        {
            "label": "Knowledge answers captured for reuse",
            "count": knowledge["answered"],
            "minutes_each": MINUTES_PER_KNOWLEDGE_ANSWER,
        },
    ]
    for row in breakdown:
        row["hours"] = round(row["count"] * row["minutes_each"] / 60, 1)

    return {
        "generated_at": now.isoformat(),
        "trail": _trail(session),
        "questions": questions,
        "knowledge": knowledge,
        "expertise": _expertise(session),
        "status_reports": status_reports,
        "time_saved": {
            "hours": round(sum(row["hours"] for row in breakdown), 1),
            "breakdown": breakdown,
        },
    }
