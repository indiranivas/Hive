"""Test fixtures: an isolated SQLite database per test, offline providers only."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

os.environ.update(
    {
        "ENVIRONMENT": "dev",
        "AUTH_MODE": "dev",
        "LLM_PROVIDER": "stub",
        "EMBEDDING_PROVIDER": "hashing",
        "VECTOR_PROVIDER": "sql",
        "GRAPH_PROVIDER": "memory",
        "NEO4J_PASSWORD": "",
        "GIT_LOCAL_REPOS": "",
        "ADO_ORG": "",
        "GITHUB_REPOS": "",
    }
)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    from api.core import config, db, embeddings, llm, vectorstore

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    for cached in (
        config.get_settings,
        embeddings.get_embedder,
        llm.get_llm,
        vectorstore.get_vector_store,
    ):
        cached.cache_clear()
    db.reset_engine()
    db.init_db()

    session = db.get_session_factory()()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        db.reset_engine()
        config.get_settings.cache_clear()


@pytest.fixture
def team(db_session):
    from api.models.orm import Org, Team

    org = Org(name="TestOrg")
    db_session.add(org)
    db_session.flush()
    team = Team(name="TestTeam", org_id=org.id)
    db_session.add(team)
    db_session.flush()
    return team


@pytest.fixture
def person(db_session, team):
    from api.models.orm import Person

    person = Person(email="dev.one@example.com", display_name="Dev One", team_id=team.id)
    db_session.add(person)
    db_session.flush()
    return person


@pytest.fixture
def artifact_factory(db_session, team, person):
    from ingestion.embedder import persist_artifact
    from ingestion.normalizer import WorkArtifact

    def make(title: str, content: str, days_ago: int = 1, artifact_type: str = "commit",
             metadata: dict | None = None, source_id: str | None = None):
        artifact = WorkArtifact(
            source="git",
            source_id=source_id or uuid.uuid4().hex,
            artifact_type=artifact_type,
            title=title,
            content=content,
            occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
            author_id=person.id,
            author_name=person.display_name,
            team_id=team.id,
            metadata=metadata or {"repo": "test-repo", "sha": "abc12345"},
        )
        persist_artifact(db_session, artifact)
        db_session.flush()
        return artifact

    return make
