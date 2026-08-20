"""Connector orchestration: watermark -> fetch -> normalize -> persist -> watermark."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.timeutil import to_utc
from api.models.orm import IngestionState, Team
from ingestion.embedder import IngestResult, persist_artifacts
from ingestion.git_connector import (
    GitProvider,
    build_git_providers,
    default_since,
    resolve_authors,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectorRun:
    connector: str
    status: str
    fetched: int = 0
    result: IngestResult = field(default_factory=IngestResult)
    error: str | None = None


def default_team_id(session: Session) -> uuid.UUID | None:
    """Phase 1 is single-team: artifacts land on the first configured team."""
    return session.execute(select(Team.id).order_by(Team.created_at)).scalars().first()


def get_state(session: Session, connector: str) -> IngestionState:
    state = session.get(IngestionState, connector)
    if state is None:
        state = IngestionState(connector=connector)
        session.add(state)
        session.flush()
    return state


def run_provider(session: Session, provider: GitProvider, team_id: uuid.UUID | None,
                 since: datetime | None = None) -> ConnectorRun:
    state = get_state(session, provider.name)
    window_start = to_utc(since) or to_utc(state.cursor_at) or default_since()
    run = ConnectorRun(connector=provider.name, status="ok")
    started_at = datetime.now(UTC)

    try:
        artifacts = provider.fetch(window_start)
        run.fetched = len(artifacts)
        resolve_authors(session, artifacts, team_id)
        run.result = persist_artifacts(session, artifacts)
        newest = max((artifact.occurred_at for artifact in artifacts), default=None)
        state.cursor_at = newest or window_start
        state.last_status = "ok"
        state.last_error = None
        state.artifacts_ingested += run.result.created
    except Exception as exc:  # noqa: BLE001 - a broken connector must not stop the others
        logger.exception("connector %s failed", provider.name)
        run.status = "error"
        run.error = str(exc)
        state.last_status = "error"
        state.last_error = str(exc)[:2000]
    finally:
        state.last_run_at = started_at
        session.flush()

    return run


def run_git_ingestion(session: Session, team_id: uuid.UUID | None = None,
                      since: datetime | None = None) -> list[ConnectorRun]:
    providers = build_git_providers()
    if not providers:
        logger.warning("no git providers configured (set GIT_LOCAL_REPOS, ADO_* or GITHUB_*)")
        return []
    resolved_team = team_id or default_team_id(session)
    return [run_provider(session, provider, resolved_team, since) for provider in providers]
