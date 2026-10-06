"""Auto-generated weekly status (blueprint section 7.2).

With a real LLM configured the summary comes from STATUS_SYSTEM_PROMPT. With the
stub it is assembled deterministically from the artifacts themselves -- facts
only, every bullet carrying its reference. Either way the evidence list is the
same, so a manager can always drill from a claim to the artifact behind it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.core.llm import get_llm
from api.core.prompts import STATUS_SYSTEM_PROMPT
from api.core.timeutil import to_utc
from api.models.orm import Person, StatusReport, WorkArtifact

MAX_EVIDENCE = 20
MAX_ARTIFACTS_IN_PROMPT = 40
STALE_TASK_DAYS = 5


@dataclass(slots=True)
class StatusResult:
    person_id: str
    person_name: str
    role: str
    period_start: str
    period_end: str
    summary: str
    evidence: list[dict[str, Any]]
    activity_level: str
    generated_at: str
    model: str


def week_bounds(reference: date | None = None) -> tuple[date, date]:
    """Monday-to-Sunday window containing `reference` (default: this week)."""
    day = reference or datetime.now(UTC).date()
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def _reference(artifact: WorkArtifact) -> str:
    meta = artifact.meta or {}
    if artifact.artifact_type == "commit" and meta.get("sha"):
        return f"{meta.get('repo', 'repo')}@{str(meta['sha'])[:8]}"
    if artifact.artifact_type == "pull_request" and meta.get("pr_id"):
        return f"{meta.get('repo', 'repo')} PR #{meta['pr_id']}"
    if artifact.artifact_type == "work_item" and meta.get("work_item_id"):
        return f"work item #{meta['work_item_id']}"
    return str(meta.get("repo") or artifact.artifact_type)


def _fetch_artifacts(session: Session, person_id: uuid.UUID, period_start: date,
                     period_end: date) -> list[WorkArtifact]:
    start = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(period_end, datetime.max.time(), tzinfo=UTC)
    return list(
        session.execute(
            select(WorkArtifact)
            .where(
                WorkArtifact.author_id == person_id,
                WorkArtifact.occurred_at >= start,
                WorkArtifact.occurred_at <= end,
            )
            .order_by(WorkArtifact.occurred_at.desc())
        ).scalars()
    )


def _group(artifacts: list[WorkArtifact]) -> dict[str, list[WorkArtifact]]:
    grouped: dict[str, list[WorkArtifact]] = {}
    for artifact in artifacts:
        grouped.setdefault(artifact.artifact_type, []).append(artifact)
    return grouped


def _is_open_pr(artifact: WorkArtifact) -> bool:
    status = str((artifact.meta or {}).get("status") or "").lower()
    return artifact.artifact_type == "pull_request" and status not in (
        "completed", "merged", "closed",
    )


def _extractive_summary(person: Person, artifacts: list[WorkArtifact]) -> str:
    """Deterministic status when no LLM is configured. Facts, no prose."""
    grouped = _group(artifacts)
    merged = [a for a in grouped.get("pull_request", []) if not _is_open_pr(a)]
    open_prs = [a for a in grouped.get("pull_request", []) if _is_open_pr(a)]
    commits = grouped.get("commit", [])
    tickets = grouped.get("work_item", [])

    lines: list[str] = []
    if merged:
        lines.append(f"COMPLETED: {len(merged)} PR(s) merged - " + "; ".join(
            f"{a.title} ({_reference(a)})" for a in merged[:3]
        ))
    if commits:
        repos = sorted({str((a.meta or {}).get("repo") or "?") for a in commits})
        lines.append(
            f"COMMITS: {len(commits)} across {', '.join(repos[:3])} - "
            f"latest \"{commits[0].title}\" ({_reference(commits[0])})"
        )
    if open_prs:
        lines.append(f"IN PROGRESS: {len(open_prs)} PR(s) open - " + "; ".join(
            f"{a.title} ({_reference(a)})" for a in open_prs[:3]
        ))
    if tickets:
        lines.append(f"TICKETS: {len(tickets)} touched - " + "; ".join(
            f"{a.title} ({_reference(a)})" for a in tickets[:3]
        ))

    cutoff = datetime.now(UTC) - timedelta(days=STALE_TASK_DAYS)
    stale = [a for a in open_prs if (to_utc(a.occurred_at) or datetime.now(UTC)) < cutoff]
    if stale:
        lines.append(
            f"BLOCKERS: {len(stale)} PR(s) open over {STALE_TASK_DAYS} days - "
            + "; ".join(f"{a.title} ({_reference(a)})" for a in stale[:3])
        )

    if not lines:
        return "No tracked activity in this period."
    lines.append(
        "(Assembled from artifacts -- no LLM configured. Set LLM_PROVIDER for a written summary.)"
    )
    return "\n".join(lines)


def _format_for_prompt(artifacts: list[WorkArtifact]) -> str:
    return "\n".join(
        f"- [{artifact.artifact_type}] {artifact.title} ({_reference(artifact)}, "
        f"{artifact.occurred_at.date().isoformat() if artifact.occurred_at else 'undated'})"
        f"{' STATUS=open' if _is_open_pr(artifact) else ''}"
        for artifact in artifacts[:MAX_ARTIFACTS_IN_PROMPT]
    )


def _llm_summary(person: Person, artifacts: list[WorkArtifact], period_start: date,
                 period_end: date) -> tuple[str, str]:
    llm = get_llm()
    if llm.model == "stub-extractive":
        return _extractive_summary(person, artifacts), llm.model

    grouped = _group(artifacts)
    counts = ", ".join(f"{key}={len(value)}" for key, value in sorted(grouped.items()))
    prompt = (
        f"Generate the weekly status for {person.display_name}.\n"
        f"Week: {period_start.isoformat()} to {period_end.isoformat()}\n"
        f"Artifact counts: {counts or 'none'}\n\n"
        f"Artifacts:\n{_format_for_prompt(artifacts)}"
    )
    try:
        response = llm.chat(
            system=STATUS_SYSTEM_PROMPT, messages=[{"role": "user", "content": prompt}]
        )
    except Exception:  # noqa: BLE001 - never fail a dashboard render on the LLM
        return _extractive_summary(person, artifacts), "llm-error-fallback"
    return response.text.strip() or _extractive_summary(person, artifacts), response.model


def build_evidence(artifacts: list[WorkArtifact]) -> list[dict[str, Any]]:
    return [
        {
            "artifact_id": str(artifact.id),
            "type": artifact.artifact_type,
            "title": artifact.title or "(no title)",
            "reference": _reference(artifact),
            "date": artifact.occurred_at.date().isoformat() if artifact.occurred_at else None,
            "excerpt": (artifact.content or "")[:240],
        }
        for artifact in artifacts[:MAX_EVIDENCE]
    ]


def activity_level(artifact_count: int) -> str:
    if artifact_count == 0:
        return "quiet"
    if artifact_count >= 8:
        return "high"
    if artifact_count <= 2:
        return "low"
    return "normal"


def generate_status(session: Session, person_id: uuid.UUID, team_id: uuid.UUID | None = None,
                    period_start: date | None = None, period_end: date | None = None,
                    force: bool = False) -> StatusResult:
    """Generate (or reuse) one person's status for a week."""
    person = session.get(Person, person_id)
    if person is None:
        raise ValueError(f"unknown person {person_id}")
    if period_start is None or period_end is None:
        period_start, period_end = week_bounds(period_start)

    existing = session.execute(
        select(StatusReport).where(
            StatusReport.person_id == person_id,
            StatusReport.period_start == period_start,
            StatusReport.period_end == period_end,
        )
    ).scalar_one_or_none()

    artifacts = _fetch_artifacts(session, person_id, period_start, period_end)

    if existing and not force:
        evidence = existing.evidence or {}
        return StatusResult(
            person_id=str(person_id),
            person_name=person.display_name,
            role=person.role,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            summary=existing.summary,
            evidence=list(evidence.get("items", [])),
            activity_level=str(evidence.get("activity_level") or activity_level(len(artifacts))),
            generated_at=(to_utc(existing.generated_at) or datetime.now(UTC)).isoformat(),
            model=str(evidence.get("model") or "cached"),
        )

    summary, model = _llm_summary(person, artifacts, period_start, period_end)
    evidence_items = build_evidence(artifacts)
    level = activity_level(len(artifacts))
    payload = {
        "items": evidence_items,
        "artifact_count": len(artifacts),
        "activity_level": level,
        "model": model,
    }

    if existing:
        existing.summary = summary
        existing.evidence = payload
        existing.team_id = team_id or person.team_id
        report = existing
        session.flush()
    else:
        report = StatusReport(
            person_id=person_id,
            team_id=team_id or person.team_id,
            period_start=period_start,
            period_end=period_end,
            summary=summary,
            evidence=payload,
        )
        # A concurrent request for the same week may insert first (the dashboard
        # can fetch twice). The savepoint keeps the outer transaction usable;
        # then the freshly generated summary overwrites the row that won.
        try:
            with session.begin_nested():
                session.add(report)
        except IntegrityError:
            winner = session.execute(
                select(StatusReport).where(
                    StatusReport.person_id == person_id,
                    StatusReport.period_start == period_start,
                    StatusReport.period_end == period_end,
                )
            ).scalar_one()
            winner.summary = summary
            winner.evidence = payload
            winner.team_id = team_id or person.team_id
            session.flush()

    return StatusResult(
        person_id=str(person_id),
        person_name=person.display_name,
        role=person.role,
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        summary=summary,
        evidence=evidence_items,
        activity_level=level,
        generated_at=datetime.now(UTC).isoformat(),
        model=model,
    )


def generate_team_statuses(session: Session, team_id: uuid.UUID | None = None,
                           period_start: date | None = None,
                           force: bool = False) -> list[StatusResult]:
    start, end = week_bounds(period_start)
    stmt = select(Person).order_by(Person.display_name)
    if team_id:
        stmt = stmt.where(Person.team_id == team_id)

    results = [
        generate_status(session, person.id, team_id, start, end, force=force)
        for person in session.execute(stmt).scalars()
    ]
    # Busiest first: a manager scanning the page wants the active work up top.
    results.sort(key=lambda item: len(item.evidence), reverse=True)
    return results
