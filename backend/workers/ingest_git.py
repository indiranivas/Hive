"""Scheduled git ingestion task."""

from __future__ import annotations

import logging

from api.core.db import session_scope
from ingestion.runner import run_git_ingestion
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.ingest_git.ingest_git", bind=True, max_retries=3)
def ingest_git(self) -> dict:
    """Pull commits and PRs from every configured git provider."""
    try:
        with session_scope() as session:
            runs = run_git_ingestion(session)
            summary = {
                "connectors": len(runs),
                "created": sum(run.result.created for run in runs),
                "updated": sum(run.result.updated for run in runs),
                "skipped": sum(run.result.skipped for run in runs),
                "errors": [run.connector for run in runs if run.status == "error"],
            }
    except Exception as exc:  # noqa: BLE001 - retry transient infra failures
        logger.exception("git ingestion task failed")
        raise self.retry(exc=exc, countdown=60) from exc

    logger.info("git ingestion complete: %s", summary)
    return summary
