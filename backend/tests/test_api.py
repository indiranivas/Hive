"""API-level tests, including the scope-enforcement rules from blueprint section 11."""

from __future__ import annotations

from datetime import UTC

import pytest
from fastapi.testclient import TestClient

from api.core.security import has_permission


@pytest.fixture
def client(db_session, monkeypatch):
    from api.core import db as db_module
    from api.main import app

    # Reuse the test session so requests see fixture data.
    def override_get_db():
        yield db_session

    app.dependency_overrides[db_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_reports_active_providers(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "stub"
    assert body["database"] == "sqlite"


def test_query_endpoint_returns_sources(client, artifact_factory):
    artifact_factory(
        "Fix JWT refresh loop in billing auth middleware",
        "Cache the refreshed token for its full TTL and retry once.",
        metadata={"repo": "billing-service", "sha": "a1b2c3d4e5"},
    )
    response = client.post("/api/query", json={"query": "billing auth jwt refresh"})
    assert response.status_code == 200
    body = response.json()
    assert body["sources"]
    assert body["sources"][0]["reference"] == "billing-service@a1b2c3d4"


def test_query_endpoint_rejects_empty_query(client):
    assert client.post("/api/query", json={"query": ""}).status_code == 422


def test_expertise_search_endpoint(client, db_session, person):
    from datetime import datetime

    from api.services.expertise_mapper import update_expertise

    update_expertise(db_session, person.id, ["billing-service"], datetime.now(UTC))
    body = client.get("/api/expertise/search", params={"topic": "billing"}).json()
    assert body["topic"] == "billing"
    assert body["experts"][0]["email"] == person.email


def test_ingestion_status_endpoint(client, artifact_factory):
    artifact_factory("A commit", "Some content about the ingestion pipeline.")
    body = client.get("/api/admin/ingestion-status").json()
    assert body["artifact_count"] == 1
    assert body["chunk_count"] >= 1


def test_audit_log_endpoint_lists_queries(client, artifact_factory):
    artifact_factory("A commit", "Content about billing.")
    client.post("/api/query", json={"query": "billing"})
    entries = client.get("/api/admin/audit-log").json()
    assert entries
    assert entries[0]["query_text"] == "billing"


def test_role_permissions_match_the_blueprint_matrix():
    assert has_permission("member", "can_query") is True
    assert has_permission("member", "can_view_dashboard") is False
    assert has_permission("member", "can_view_team_status") is False
    assert has_permission("manager", "can_view_team_status") is True
    assert has_permission("manager", "can_manage_connectors") is False
    assert has_permission("admin", "can_view_audit_log") is True
    assert has_permission("nonsense-role", "can_query") is True


def test_member_cannot_reach_admin_endpoints(client, db_session):
    from api.core.security import resolve_dev_user

    user = resolve_dev_user(db_session)
    user.role = "member"
    db_session.flush()

    assert client.get("/api/admin/ingestion-status").status_code == 403
    assert client.get("/api/admin/audit-log").status_code == 403
    assert client.post("/api/query", json={"query": "anything"}).status_code == 200


def test_member_cannot_query_another_teams_artifacts(client, db_session, artifact_factory, team):
    """A member passing someone else's team_id is silently scoped back to their own."""
    from api.core.security import resolve_dev_user
    from api.models.orm import Org, Team

    artifact_factory("Team A commit", "Billing auth work for team A.")

    other_org = Org(name="Other")
    db_session.add(other_org)
    db_session.flush()
    other_team = Team(name="OtherTeam", org_id=other_org.id)
    db_session.add(other_team)
    db_session.flush()

    user = resolve_dev_user(db_session)
    user.role = "member"
    user.team_id = other_team.id
    db_session.flush()

    body = client.post(
        "/api/query", json={"query": "billing auth", "team_id": str(team.id)}
    ).json()
    assert body["sources"] == []
    assert body["has_gap"] is True
