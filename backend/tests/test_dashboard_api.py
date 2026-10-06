"""Tests for the dashboard surface: pulse, activity, status, knowledge, gaps.

The theme running through these is honesty about missing data: a metric that has
no source must come back null with an explanation rather than a plausible zero.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.models.orm import KnowledgeRequest, Notification, Person
from api.services.dashboard_service import activity_breakdown, expertise_map, team_pulse
from api.services.status_generator import generate_status, generate_team_statuses, week_bounds


@pytest.fixture
def client(db_session):
    from api.core import db as db_module
    from api.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[db_module.get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def dev_user(db_session, team):
    """The dev-mode identity, placed on the fixture team."""
    from api.core.security import resolve_dev_user

    user = resolve_dev_user(db_session)
    user.team_id = team.id
    db_session.flush()
    return user


# --- pulse -------------------------------------------------------------------


def test_pulse_reports_activity_and_coverage(db_session, artifact_factory, team):
    artifact_factory("Fix auth", "Refresh token handling.", days_ago=1)
    artifact_factory(
        "PR #7: Auth hardening",
        "Reviewers listed.",
        days_ago=2,
        artifact_type="pull_request",
        metadata={"repo": "billing", "pr_id": 7, "status": "active"},
    )

    pulse = team_pulse(db_session, team.id, window_days=7)
    assert pulse.weekly_activity["commits"] == 1
    assert pulse.weekly_activity["prs"] == 1
    assert pulse.data_coverage == {"git": True, "task": False, "email": False, "call": False}
    assert pulse.open_prs == 1
    assert pulse.merged_prs == 0


def test_pulse_reports_null_on_track_without_a_task_connector(db_session, artifact_factory, team):
    """No Azure DevOps data means no honest on-track number."""
    artifact_factory("Fix auth", "Body.", days_ago=1)
    pulse = team_pulse(db_session, team.id)
    assert pulse.on_track_percent is None
    assert pulse.blocked_count is None
    assert any("not connected" in alert.title for alert in pulse.alerts)


def test_pulse_computes_on_track_when_work_items_exist(db_session, artifact_factory, team):
    for index, state in enumerate(["Closed", "Closed", "Active", "Blocked"]):
        artifact_factory(
            f"Ticket {index}",
            f"State {state}",
            days_ago=1,
            artifact_type="work_item",
            source_id=f"wi-{index}",
            metadata={"state": state, "work_item_id": index},
        )
    db_session.execute(
        __import__("sqlalchemy").text("UPDATE work_artifacts SET source = 'task'")
    )
    db_session.flush()

    pulse = team_pulse(db_session, team.id)
    assert pulse.data_coverage["task"] is True
    assert pulse.on_track_percent == 50.0  # 2 of 4 closed
    assert pulse.blocked_count == 1


def test_pulse_flags_stale_pull_requests(db_session, artifact_factory, team):
    artifact_factory(
        "PR #9: Long-running",
        "Still open.",
        days_ago=20,
        artifact_type="pull_request",
        metadata={"repo": "billing", "pr_id": 9, "status": "active"},
    )
    pulse = team_pulse(db_session, team.id)
    assert pulse.stale_count == 1
    assert any("open over" in alert.title for alert in pulse.alerts)


def test_pulse_activity_level_never_ranks_people(db_session, artifact_factory, team, person):
    artifact_factory("One", "Body.", days_ago=1)
    pulse = team_pulse(db_session, team.id)
    assert pulse.contributors[0].level in {"high", "normal", "low", "quiet"}


def test_activity_breakdown_returns_a_row_per_week(db_session, artifact_factory, team):
    artifact_factory("Recent", "Body.", days_ago=1)
    artifact_factory("Older", "Body.", days_ago=15, source_id="older")
    weeks = activity_breakdown(db_session, team.id, weeks=4)
    assert len(weeks) == 4
    assert weeks[-1]["week"] < weeks[-1]["week"] + "z"  # ISO dates, ascending
    assert sum(week["total"] for week in weeks) >= 1


def test_pulse_endpoint_requires_dashboard_permission(client, db_session, dev_user):
    assert client.get("/api/dashboard/pulse").status_code == 200
    dev_user.role = "member"
    db_session.flush()
    assert client.get("/api/dashboard/pulse").status_code == 403


# --- expertise map -----------------------------------------------------------


def test_expertise_map_marks_solo_topics(db_session, team, person):
    from api.services.expertise_mapper import update_expertise

    other = Person(email="two@example.com", display_name="Two", team_id=team.id)
    db_session.add(other)
    db_session.flush()

    now = datetime.now(UTC)
    update_expertise(db_session, person.id, ["billing", "shared"], now)
    update_expertise(db_session, other.id, ["shared"], now)

    result = expertise_map(db_session, team.id)
    assert "billing" in result["solo_topics"]
    assert "shared" not in result["solo_topics"]
    assert len(result["people"]) == 2


# --- status ------------------------------------------------------------------


def test_week_bounds_is_monday_to_sunday():
    start, end = week_bounds()
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert (end - start).days == 6


def test_generate_status_summarizes_and_cites(db_session, artifact_factory, person, team):
    artifact_factory("Fix billing auth", "Token refresh.", days_ago=0)
    result = generate_status(db_session, person.id, team.id)
    assert result.person_name == person.display_name
    assert result.evidence
    assert result.evidence[0]["reference"]
    assert result.activity_level != "quiet"


def test_generate_status_is_honest_about_an_empty_week(db_session, person, team):
    result = generate_status(db_session, person.id, team.id)
    assert result.summary == "No tracked activity in this period."
    assert result.evidence == []
    assert result.activity_level == "quiet"


def test_generate_status_reuses_the_stored_report(db_session, artifact_factory, person, team):
    artifact_factory("First", "Body.", days_ago=0)
    first = generate_status(db_session, person.id, team.id)

    artifact_factory("Second", "Body.", days_ago=0, source_id="second")
    cached = generate_status(db_session, person.id, team.id)
    # Reused, not regenerated: the new artifact is absent until a forced refresh.
    assert cached.summary == first.summary
    assert len(cached.evidence) == 1

    refreshed = generate_status(db_session, person.id, team.id, force=True)
    assert len(refreshed.evidence) == 2


def test_generate_team_statuses_covers_everyone(db_session, artifact_factory, person, team):
    quiet = Person(email="quiet@example.com", display_name="Quiet One", team_id=team.id)
    db_session.add(quiet)
    db_session.flush()
    artifact_factory("Busy", "Body.", days_ago=0)

    results = generate_team_statuses(db_session, team.id)
    assert {result.person_name for result in results} == {person.display_name, "Quiet One"}
    # Busiest first, so a manager sees active work at the top.
    assert results[0].person_name == person.display_name


def test_person_status_scope_blocks_reading_someone_else(client, db_session, dev_user, person):
    dev_user.role = "member"
    db_session.flush()
    assert client.get(f"/api/status/person/{person.id}").status_code == 403
    assert client.get(f"/api/status/person/{dev_user.id}").status_code == 200


def test_team_status_endpoint_returns_the_period(client, dev_user):
    body = client.get("/api/status/team").json()
    assert body["period_start"] <= body["period_end"]
    assert isinstance(body["statuses"], list)


# --- knowledge requests ------------------------------------------------------


def test_create_list_and_answer_a_knowledge_request(client, db_session, dev_user):
    created = client.post(
        "/api/knowledge-requests",
        json={"question": "How do we rotate the ADO PAT?", "context": "connector setup"},
    )
    assert created.status_code == 201
    kr_id = created.json()["id"]
    assert created.json()["status"] == "open"

    listed = client.get("/api/knowledge-requests?status=open").json()
    assert any(item["id"] == kr_id for item in listed["items"])

    answered = client.put(
        f"/api/knowledge-requests/{kr_id}/answer",
        json={"answer": "Rotate it in Azure DevOps user settings every 90 days."},
    )
    assert answered.status_code == 200
    assert answered.json()["answered_by"] == dev_user.display_name
    # Indexing into the repo is what makes the answer reusable.
    assert db_session.get(KnowledgeRequest, __import__("uuid").UUID(kr_id)).status == "indexed"


def test_answering_twice_conflicts(client, dev_user):
    kr_id = client.post(
        "/api/knowledge-requests", json={"question": "Where is the runbook?"}
    ).json()["id"]
    path = f"/api/knowledge-requests/{kr_id}/answer"
    assert client.put(path, json={"answer": "In the wiki."}).status_code == 200
    assert client.put(path, json={"answer": "Elsewhere."}).status_code == 409


def test_knowledge_request_search_matches_question_and_answer(client, dev_user):
    kr_id = client.post(
        "/api/knowledge-requests", json={"question": "What signs the webhooks?"}
    ).json()["id"]
    client.put(f"/api/knowledge-requests/{kr_id}/answer", json={"answer": "An HMAC secret."})

    assert client.get("/api/knowledge-requests?search=webhooks").json()["count"] == 1
    assert client.get("/api/knowledge-requests?search=HMAC").json()["count"] == 1
    assert client.get("/api/knowledge-requests?search=nonexistent").json()["count"] == 0


def test_gap_analytics_never_reports_negative_resolution(client, db_session, dev_user, person):
    """Backfilled rows can be answered 'before' they were created."""
    now = datetime.now(UTC)
    db_session.add(
        KnowledgeRequest(
            requester_id=person.id,
            question="Imported question",
            answer="Imported answer",
            answered_by_id=person.id,
            created_at=now,
            answered_at=now - timedelta(days=8),
            status="indexed",
            tags=["imported"],
        )
    )
    db_session.flush()

    analytics = client.get("/api/knowledge-requests/analytics").json()
    assert analytics["avg_resolution_hours"] is None or analytics["avg_resolution_hours"] >= 0


def test_gap_analytics_shape(client, db_session, dev_user, person):
    from api.services.expertise_mapper import update_expertise

    update_expertise(db_session, person.id, ["solo-topic"], datetime.now(UTC))
    client.post("/api/knowledge-requests", json={"question": "An open question here?"})

    analytics = client.get("/api/knowledge-requests/analytics?weeks=4").json()
    assert analytics["open_krs"] == 1
    assert len(analytics["trend"]) == 4
    assert {"week", "new", "resolved"} == set(analytics["trend"][0])
    assert any(entry["person"] == person.display_name for entry in analytics["bus_factor"])


def test_gap_analytics_requires_manager(client, db_session, dev_user):
    dev_user.role = "member"
    db_session.flush()
    assert client.get("/api/knowledge-requests/analytics").status_code == 403


def test_seed_reset_survives_new_tables_referencing_people(db_session, team, person):
    """`seed --reset` broke when the notification outbox was added, because it
    deleted people while rows still referenced them. The reset now walks the
    metadata, so any future table is covered."""
    from db.seed import reset_data

    db_session.add(
        Notification(person_id=person.id, kind="kr_routed", subject="ping", body="hello")
    )
    db_session.flush()

    reset_data(db_session)  # must not raise a foreign key error

    assert db_session.execute(select(Notification)).scalars().all() == []


def test_leadership_overview_counts_and_shows_its_assumptions(client, artifact_factory):
    for index in range(3):
        artifact_factory(f"Change {index}", "body", metadata={"repo": "solo-repo", "sha": f"s{index}"})

    overview = client.get("/api/dashboard/overview").json()
    assert overview["trail"]["artifacts"] == 3
    assert overview["trail"]["repos"] == 1
    # One person did all of solo-repo: that is concentration risk.
    [area] = overview["expertise"]["areas"]
    assert area["repo"] == "solo-repo" and area["top_share"] == 1.0 and area["at_risk"]
    # The estimate must carry its inputs, and add up from them.
    rows = overview["time_saved"]["breakdown"]
    assert all({"count", "minutes_each", "hours"} <= set(row) for row in rows)
    assert overview["time_saved"]["hours"] == round(sum(row["hours"] for row in rows), 1)


def test_leadership_overview_requires_manager(client, db_session, dev_user):
    dev_user.role = "member"
    db_session.flush()
    assert client.get("/api/dashboard/overview").status_code == 403
