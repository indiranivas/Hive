from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api.models.orm import ExpertiseScore, Person
from api.services.expertise_mapper import find_experts, recency_weight, update_expertise
from api.services.topics import extract_topics_heuristic, slugify


def test_slugify_normalizes_separators():
    assert slugify("Azure DevOps API") == "azure-devops-api"
    assert slugify("  JWT_Token.Refresh ") == "jwt-token-refresh"


def test_heuristic_topics_prefer_specific_terms():
    topics = extract_topics_heuristic(
        "Fix JWT refresh loop in billing auth middleware. Touches "
        "services/billing/auth_middleware.py and the redis client.",
        {"repo": "billing-service"},
    )
    assert "billing-service" in topics
    assert any("jwt" in topic or "auth" in topic for topic in topics)
    assert "fix" not in topics
    assert "code" not in topics


def test_heuristic_topics_pick_up_file_extensions():
    topics = extract_topics_heuristic("Update src/components/ActivityBars.tsx layout")
    assert "react" in topics


def test_heuristic_topics_use_changed_files_from_metadata():
    """Commit messages rarely name the module; the changed files always do."""
    topics = extract_topics_heuristic(
        "Tidy up after review",
        {"files_changed": ["src/components/ActivityBars.tsx", "src/lib/auth.ts"]},
    )
    assert "react" in topics
    assert "activitybars" in topics


def test_heuristic_topics_use_metadata_tags():
    topics = extract_topics_heuristic("Routine change", {"tags": ["salesforce-rest-api"]})
    assert "salesforce-rest-api" in topics


def test_heuristic_topics_returns_nothing_for_generic_text():
    assert extract_topics_heuristic("fix stuff") == []


def test_recency_weight_decays_with_age():
    now = datetime.now(UTC)
    assert recency_weight(now) == 1.0
    assert recency_weight(now - timedelta(days=90)) < recency_weight(now - timedelta(days=30))
    assert recency_weight(None) == 0.0


def test_update_expertise_accumulates_evidence(db_session, person):
    occurred = datetime.now(UTC)
    update_expertise(db_session, person.id, ["billing-service"], occurred)
    update_expertise(db_session, person.id, ["billing-service"], occurred)

    score = db_session.query(ExpertiseScore).filter_by(person_id=person.id).one()
    assert score.evidence_count == 2
    assert score.score > 0
    assert score.last_seen is not None


def test_update_expertise_deduplicates_topics_within_one_artifact(db_session, person):
    update_expertise(
        db_session, person.id, ["react", "react", "react"], datetime.now(UTC)
    )
    score = db_session.query(ExpertiseScore).filter_by(topic="react").one()
    assert score.evidence_count == 1


def test_update_expertise_is_a_noop_without_author_or_topics(db_session, person):
    update_expertise(db_session, None, ["react"], datetime.now(UTC))
    update_expertise(db_session, person.id, [], datetime.now(UTC))
    assert db_session.query(ExpertiseScore).count() == 0


def test_find_experts_ranks_recent_evidence_first(db_session, team, person):
    veteran = Person(email="old.hand@example.com", display_name="Old Hand", team_id=team.id)
    db_session.add(veteran)
    db_session.flush()

    now = datetime.now(UTC)
    update_expertise(db_session, person.id, ["billing-service"], now)
    update_expertise(db_session, veteran.id, ["billing-service"], now - timedelta(days=400))

    experts = find_experts(db_session, "billing-service", team_id=team.id)
    assert [expert.display_name for expert in experts][0] == "Dev One"


def test_find_experts_matches_partial_topics(db_session, person, team):
    update_expertise(db_session, person.id, ["azure-devops-api"], datetime.now(UTC))
    assert find_experts(db_session, "devops", team_id=team.id)
    assert find_experts(db_session, "Azure DevOps API", team_id=team.id)


def test_find_experts_empty_topic_and_unknown_topic(db_session, team):
    assert find_experts(db_session, "   ", team_id=team.id) == []
    assert find_experts(db_session, "quantum-teleportation", team_id=team.id) == []


def test_find_experts_respects_team_scope(db_session, team, person):
    from api.models.orm import Org, Team

    other_org = Org(name="Other")
    db_session.add(other_org)
    db_session.flush()
    other_team = Team(name="Other", org_id=other_org.id)
    db_session.add(other_team)
    db_session.flush()

    update_expertise(db_session, person.id, ["billing-service"], datetime.now(UTC))
    assert find_experts(db_session, "billing-service", team_id=other_team.id) == []
