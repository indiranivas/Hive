from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from api.models.orm import IngestionState, VectorChunk, WorkArtifact
from ingestion.embedder import persist_artifact, persist_artifacts
from ingestion.git_connector import LocalGitProvider
from ingestion.normalizer import WorkArtifact as ArtifactDTO
from ingestion.runner import run_provider


def _dto(source_id: str, title: str, content: str, person=None, team=None, days_ago: int = 1):
    return ArtifactDTO(
        source="git",
        source_id=source_id,
        artifact_type="commit",
        title=title,
        content=content,
        occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
        author_id=person.id if person else None,
        author_name=person.display_name if person else None,
        team_id=team.id if team else None,
        metadata={"repo": "test-repo", "sha": source_id},
    )


def test_persist_artifact_creates_rows_chunks_and_expertise(db_session, person, team):
    result = persist_artifact(
        db_session,
        _dto("sha1", "Add celery beat schedule", "Schedules the git connector every 10 minutes.",
             person, team),
    )
    assert result.created == 1
    assert result.chunks >= 1

    artifact = db_session.execute(select(WorkArtifact)).scalars().one()
    assert artifact.source_id == "sha1"
    assert artifact.meta.get("topics")
    assert db_session.execute(select(VectorChunk)).scalars().all()


def test_persist_artifact_is_idempotent_on_source_id(db_session, person, team):
    first = persist_artifact(db_session, _dto("sha2", "Title", "Body text here.", person, team))
    second = persist_artifact(db_session, _dto("sha2", "Title", "Body text here.", person, team))
    assert first.created == 1
    assert second.skipped == 1
    assert len(db_session.execute(select(WorkArtifact)).scalars().all()) == 1


def test_persist_artifact_updates_and_replaces_chunks(db_session, person, team):
    persist_artifact(db_session, _dto("sha3", "Original", "First body.", person, team))
    original_chunks = len(db_session.execute(select(VectorChunk)).scalars().all())

    updated = persist_artifact(
        db_session,
        _dto("sha3", "Amended", "Rewritten body with more detail about billing.", person, team),
    )
    assert updated.updated == 1
    artifact = db_session.execute(select(WorkArtifact)).scalars().one()
    assert artifact.title == "Amended"
    chunks = db_session.execute(select(VectorChunk)).scalars().all()
    assert len(chunks) == original_chunks
    assert all("Rewritten" in chunk.document or "billing" in chunk.document for chunk in chunks)


def test_persist_artifact_skips_empty_content(db_session, person, team):
    assert persist_artifact(db_session, _dto("sha4", "Empty", "   ", person, team)).skipped == 1
    assert db_session.execute(select(WorkArtifact)).scalars().all() == []


def test_persist_artifacts_isolates_a_bad_payload(db_session, person, team):
    good = _dto("sha5", "Good", "A perfectly fine commit message.", person, team)
    bad = _dto("sha6", "Bad", "Also fine, but the source_id is far too long." , person, team)
    bad.source_id = "x" * 600  # exceeds the 512-char column on strict backends

    result = persist_artifacts(db_session, [good, bad])
    assert result.created >= 1
    assert db_session.execute(
        select(WorkArtifact).where(WorkArtifact.source_id == "sha5")
    ).scalars().one()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_local_git_provider_reads_a_real_repo(tmp_path, db_session, team):
    repo = tmp_path / "sample-repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "dev.one@example.com")
    git("config", "user.name", "Dev One")
    (repo / "auth.py").write_text("def refresh_token():\n    return None\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Add token refresh helper to auth module")
    (repo / "billing.py").write_text("TAX = 0.2\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Add billing tax constant\n\nNeeded for invoice totals.")

    provider = LocalGitProvider(repo)
    artifacts = provider.fetch(datetime.now(UTC) - timedelta(days=1))

    assert len(artifacts) == 2
    titles = {artifact.title for artifact in artifacts}
    assert "Add token refresh helper to auth module" in titles
    multiline = next(a for a in artifacts if a.title == "Add billing tax constant")
    assert "invoice totals" in multiline.content
    assert multiline.metadata["files_changed"] == ["billing.py"]
    assert multiline.metadata["author_email"] == "dev.one@example.com"

    run = run_provider(db_session, provider, team.id)
    assert run.status == "ok"
    assert run.result.created == 2

    state = db_session.get(IngestionState, provider.name)
    assert state is not None
    assert state.last_status == "ok"
    assert state.cursor_at is not None

    # Second run over the same window is a no-op: the watermark advanced.
    rerun = run_provider(db_session, provider, team.id)
    assert rerun.result.created == 0


def test_run_provider_records_connector_failure(db_session, team, tmp_path):
    provider = LocalGitProvider(tmp_path / "does-not-exist")
    run = run_provider(db_session, provider, team.id)
    assert run.status == "error"
    state = db_session.get(IngestionState, provider.name)
    assert state.last_status == "error"
    assert state.last_error
