from __future__ import annotations

from datetime import UTC

from sqlalchemy import select

from api.models.orm import QueryLog
from api.services.query_engine import answer_query, build_context, retrieve


def _seed(artifact_factory):
    artifact_factory(
        "Fix JWT refresh loop in billing auth middleware",
        "The refresh token was reissued on every 401 which stampeded the identity provider.",
        days_ago=2,
        metadata={"repo": "billing-service", "sha": "a1b2c3d4e5"},
    )
    artifact_factory(
        "Add force graph to expertise map",
        "D3 force layout linking topics to people, sized by expertise score.",
        days_ago=9,
        metadata={"repo": "web-dashboard", "sha": "ffeeddccbb"},
    )


def test_answer_query_returns_sourced_answer(db_session, artifact_factory, person, team):
    _seed(artifact_factory)
    result = answer_query(
        db_session, "jwt refresh in billing auth", user_id=person.id, team_id=team.id
    )
    assert result.sources
    assert "billing auth" in result.sources[0].title.lower()
    assert result.sources[0].reference == "billing-service@a1b2c3d4"
    assert result.has_gap is False
    assert result.latency_ms >= 0


def test_answer_query_reports_gap_when_nothing_matches(db_session, artifact_factory, person, team):
    _seed(artifact_factory)
    result = answer_query(
        db_session,
        "what is our kubernetes cluster autoscaling policy",
        user_id=person.id,
        team_id=team.id,
    )
    assert result.has_gap is True
    assert "Knowledge Request" in result.answer


def test_answer_query_is_logged_for_audit(db_session, artifact_factory, person, team):
    _seed(artifact_factory)
    answer_query(db_session, "billing auth", user_id=person.id, team_id=team.id, surface="teams")
    logs = db_session.execute(select(QueryLog)).scalars().all()
    assert len(logs) == 1
    assert logs[0].surface == "teams"
    assert logs[0].user_id == person.id
    assert logs[0].latency_ms is not None


def test_empty_query_short_circuits(db_session, person, team):
    result = answer_query(db_session, "   ", user_id=person.id, team_id=team.id)
    assert result.sources == []
    assert db_session.execute(select(QueryLog)).scalars().first() is None


def test_retrieval_is_scoped_to_the_team(db_session, artifact_factory, team):
    from api.models.orm import Org, Team

    _seed(artifact_factory)
    other_org = Org(name="Other")
    db_session.add(other_org)
    db_session.flush()
    other_team = Team(name="OtherTeam", org_id=other_org.id)
    db_session.add(other_team)
    db_session.flush()

    assert retrieve(db_session, "billing auth", team_id=team.id, scope="team")
    assert retrieve(db_session, "billing auth", team_id=other_team.id, scope="team") == []


def test_keyword_pass_finds_exact_identifier_vectors_would_miss(
    db_session, artifact_factory, team
):
    artifact_factory(
        "Bump dependency",
        "Routine dependency bump touching pyproject and lockfile for zzqqxx-service.",
        days_ago=1,
        metadata={"repo": "infra", "sha": "0011223344"},
    )
    hits = retrieve(db_session, "zzqqxx-service", team_id=team.id)
    assert any("zzqqxx" in hit.artifact.content for hit in hits)


def test_build_context_respects_char_budget(db_session, artifact_factory, team):
    _seed(artifact_factory)
    candidates = retrieve(db_session, "billing auth", team_id=team.id)
    assert build_context(candidates, [], budget=10) == ""
    full = build_context(candidates, [])
    assert "[1]" in full
    assert "Title:" in full


def test_knowledge_repo_answers_are_retrievable(db_session, person, team):
    from datetime import datetime

    from api.models.orm import KnowledgeRequest
    from api.services.knowledge_repo import index_knowledge_request
    from api.services.query_engine import retrieve_knowledge_repo

    kr = KnowledgeRequest(
        requester_id=person.id,
        question="Which Azure DevOps PAT scopes does the task connector need?",
        answer="Read-only: Work Items (Read), Code (Read), Project and Team (Read).",
        answered_by_id=person.id,
        answered_at=datetime.now(UTC),
        status="answered",
        tags=["azure-devops-api"],
    )
    db_session.add(kr)
    db_session.flush()
    assert index_knowledge_request(db_session, kr) is True
    assert kr.status == "indexed"

    hits = retrieve_knowledge_repo(db_session, "azure devops pat scopes")
    assert hits
    assert "Read-only" in hits[0]["answer"]


def test_knowledge_repo_answer_is_a_source_not_a_gap(db_session, person, team):
    """An answered KR must satisfy the question: reporting a gap while showing the
    repo's answer is the bug this locks down."""
    from datetime import UTC, datetime

    from api.models.orm import KnowledgeRequest
    from api.services.knowledge_repo import index_knowledge_request

    kr = KnowledgeRequest(
        requester_id=person.id,
        question="What is our Kubernetes autoscaling policy?",
        answer="We do not run Kubernetes. Scaling is Azure Container Apps replicas.",
        answered_by_id=person.id,
        answered_at=datetime.now(UTC),
        status="answered",
        tags=["kubernetes"],
    )
    db_session.add(kr)
    db_session.flush()
    index_knowledge_request(db_session, kr)

    result = answer_query(
        db_session, "kubernetes autoscaling policy", user_id=person.id, team_id=team.id
    )
    assert result.sources, "the knowledge repo hit should be reported as a source"
    assert result.sources[0].type == "knowledge_repo"
    assert result.sources[0].reference == "knowledge repo"
    assert result.has_gap is False
