"""LangGraph orchestration tests: graded retrieval and Knowledge Request routing.

Both graphs are exercised through their public entry points, so the assertions
hold whether langgraph is installed (compiled graph) or not (plain-loop
fallback). The node-level helpers are tested directly where the decision logic
matters.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from api.models.orm import KnowledgeRequest, Notification, Person
from api.services.expertise_mapper import update_expertise
from api.services.kr_manager import create_knowledge_request
from api.services.kr_routing_graph import (
    answer_knowledge_request,
    pending_notifications,
    route_knowledge_request,
    routing_score,
)
from api.services.query_engine import answer_query
from api.services.retrieval_graph import (
    GradedRetrieval,
    grade_heuristically,
    graded_retrieve,
    rewrite_heuristically,
)


def _seed_billing(artifact_factory):
    artifact_factory(
        "Fix JWT refresh loop in billing auth middleware",
        "The refresh token was reissued on every 401 which stampeded the identity provider.",
        days_ago=2,
        metadata={"repo": "billing-service", "sha": "a1b2c3d4e5"},
    )


# --- graded retrieval --------------------------------------------------------


def test_langgraph_is_actually_installed():
    """The graphs fall back to a plain loop without it -- assert the real path runs."""
    import langgraph.graph  # noqa: F401

    from api.services.retrieval_graph import _langgraph_available

    _langgraph_available.cache_clear()
    assert _langgraph_available() is True


def test_grade_heuristic_calls_empty_retrieval_weak():
    assert grade_heuristically({"candidates": [], "knowledge": []}) == "weak"


def test_grade_heuristic_needs_more_than_a_floor_scrape(db_session):
    class Stub:
        def __init__(self, score):
            self.score = score

    # The floor is 0.15 and sufficiency needs 2x that.
    assert grade_heuristically({"candidates": [Stub(0.16)]}) == "weak"
    assert grade_heuristically({"candidates": [Stub(0.40)]}) == "sufficient"


def test_grade_heuristic_accepts_a_strong_knowledge_repo_hit():
    assert grade_heuristically({"knowledge": [{"score": 0.8}]}) == "sufficient"


def test_rewrite_strips_interrogative_filler():
    assert rewrite_heuristically("Who fixed the billing auth bug?") == "fixed billing auth bug"
    assert rewrite_heuristically("What is our kubernetes autoscaling policy?") == (
        "kubernetes autoscaling policy"
    )


def test_rewrite_deduplicates_and_never_returns_empty():
    assert rewrite_heuristically("the the a an of") == "the the a an of"
    assert rewrite_heuristically("billing billing service") == "billing service"


def test_graded_retrieve_stops_on_a_good_first_pass(db_session, artifact_factory, team):
    _seed_billing(artifact_factory)
    result = graded_retrieve(db_session, "jwt refresh loop in billing auth", team_id=team.id)
    assert isinstance(result, GradedRetrieval)
    assert result.verdict == "sufficient"
    assert result.attempts == 1
    assert result.rewrites == []
    assert result.candidates


def test_graded_retrieve_retries_with_a_rewrite_then_gives_up(db_session, artifact_factory, team):
    """A question with no evidence should burn its retry and report weak."""
    _seed_billing(artifact_factory)
    result = graded_retrieve(
        db_session, "What is our kubernetes autoscaling policy?", team_id=team.id
    )
    assert result.verdict == "weak"
    assert result.attempts == 2  # one rewrite, capped by RETRIEVAL_MAX_REWRITES
    assert result.rewrites == ["kubernetes autoscaling policy"]
    assert result.candidates == []


def test_graded_retrieve_recovers_when_the_rewrite_finds_evidence(
    db_session, artifact_factory, team
):
    """The whole point of the loop: filler-heavy phrasing scores badly, the
    rewritten keyword query finds the artifact."""
    artifact_factory(
        "Cache Microsoft Graph tokens in Redis",
        "Graph token requests were rate limited during backfill, so cache per tenant.",
        days_ago=1,
        metadata={"repo": "hive-api", "sha": "f60718293"},
    )
    verbose = "Could you please tell me anything about how we do the graph token caching?"

    from api.services.query_engine import retrieve

    first_pass = retrieve(db_session, verbose, team_id=team.id)
    graded = graded_retrieve(db_session, verbose, team_id=team.id)

    assert graded.rewrites, "the weak first pass should have triggered a rewrite"
    best_first = max((item.score for item in first_pass), default=0.0)
    best_graded = max((item.score for item in graded.candidates), default=0.0)
    assert best_graded > best_first


def test_linear_mode_skips_the_graph(db_session, artifact_factory, person, team, monkeypatch):
    from api.core import config

    _seed_billing(artifact_factory)
    monkeypatch.setenv("RETRIEVAL_MODE", "linear")
    config.get_settings.cache_clear()
    try:
        result = answer_query(
            db_session, "who fixed the billing auth?", user_id=person.id, team_id=team.id
        )
        assert result.attempts == 1
        assert result.rewrites == []
    finally:
        config.get_settings.cache_clear()


def test_answer_query_reports_the_graph_trace(db_session, artifact_factory, person, team):
    _seed_billing(artifact_factory)
    result = answer_query(
        db_session,
        "Could you tell me anything about the kubernetes autoscaling policy?",
        user_id=person.id,
        team_id=team.id,
    )
    assert result.has_gap is True
    assert result.attempts == 2
    assert result.rewrites
    assert "rewrites" in result.to_dict()


# --- KR routing --------------------------------------------------------------


def test_routing_score_matches_the_blueprint_formula():
    now = datetime.now(UTC)
    # score*0.5 + recency*0.3 - load*0.2; recency is 1.0 for today.
    assert routing_score(2.0, now, 0) == pytest.approx(2.0 * 0.5 + 0.3)
    assert routing_score(2.0, now, 2) == pytest.approx(2.0 * 0.5 + 0.3 - 0.4)


def test_routing_prefers_the_expert_with_evidence(db_session, team, person):
    expert = Person(email="expert@example.com", display_name="Expert One", team_id=team.id)
    db_session.add(expert)
    db_session.flush()
    update_expertise(db_session, expert.id, ["billing-service"], datetime.now(UTC))

    kr = create_knowledge_request(db_session, person.id, "How does billing-service auth work?")

    assert kr.status == "routed"
    assert kr.routed_to_id == expert.id
    result = route_knowledge_request(db_session, kr)
    assert result.routed_to_name == "Expert One"
    assert "billing-service" in result.reason


def test_routing_never_returns_the_question_to_its_asker(db_session, team, person):
    update_expertise(db_session, person.id, ["billing-service"], datetime.now(UTC))
    kr = create_knowledge_request(db_session, person.id, "How does billing-service auth work?")
    assert kr.routed_to_id is None
    assert kr.status == "open"


def test_routing_load_balances_between_equal_experts(db_session, team, person):
    busy = Person(email="busy@example.com", display_name="Busy", team_id=team.id)
    idle = Person(email="idle@example.com", display_name="Idle", team_id=team.id)
    db_session.add_all([busy, idle])
    db_session.flush()

    now = datetime.now(UTC)
    update_expertise(db_session, busy.id, ["billing-service"], now)
    update_expertise(db_session, idle.id, ["billing-service"], now)

    # Give `busy` two open routed requests so the load penalty decides it.
    for index in range(2):
        db_session.add(
            KnowledgeRequest(
                requester_id=person.id,
                question=f"Existing load {index}",
                status="routed",
                routed_to_id=busy.id,
                tags=["billing-service"],
            )
        )
    db_session.flush()

    kr = create_knowledge_request(db_session, person.id, "Another billing-service question?")
    assert kr.routed_to_id == idle.id


def test_routing_queues_a_notification_for_the_expert(db_session, team, person):
    expert = Person(email="expert@example.com", display_name="Expert One", team_id=team.id)
    db_session.add(expert)
    db_session.flush()
    update_expertise(db_session, expert.id, ["billing-service"], datetime.now(UTC))

    create_knowledge_request(db_session, person.id, "How does billing-service auth work?")

    notification = db_session.execute(select(Notification)).scalars().one()
    assert notification.kind == "kr_routed"
    assert notification.person_id == expert.id
    assert notification.status == "pending"
    assert pending_notifications(db_session)


def test_rerouting_to_the_same_expert_does_not_ping_them_twice(db_session, team, person):
    expert = Person(email="expert@example.com", display_name="Expert One", team_id=team.id)
    db_session.add(expert)
    db_session.flush()
    update_expertise(db_session, expert.id, ["billing-service"], datetime.now(UTC))

    kr = create_knowledge_request(db_session, person.id, "How does billing-service auth work?")
    route_knowledge_request(db_session, kr)
    route_knowledge_request(db_session, kr)

    routed = db_session.execute(
        select(Notification).where(Notification.kind == "kr_routed")
    ).scalars().all()
    assert len(routed) == 1


def test_unroutable_request_notifies_the_team_instead(db_session, team, person):
    create_knowledge_request(db_session, person.id, "Which coffee supplier do we use?")
    notification = db_session.execute(select(Notification)).scalars().one()
    assert notification.kind == "kr_unrouted"
    assert notification.person_id is None


def test_answering_indexes_credits_and_notifies(db_session, team, person):
    expert = Person(email="expert@example.com", display_name="Expert One", team_id=team.id)
    db_session.add(expert)
    db_session.flush()
    update_expertise(db_session, expert.id, ["billing-service"], datetime.now(UTC))

    kr = create_knowledge_request(db_session, person.id, "How does billing-service auth work?")
    answer_knowledge_request(db_session, kr, expert, "It uses a cached JWT with a 401 retry.")

    assert kr.status == "indexed"
    assert kr.answered_by_id == expert.id

    kinds = {
        notification.kind
        for notification in db_session.execute(select(Notification)).scalars()
    }
    assert kinds == {"kr_routed", "kr_answered"}

    answered_notice = db_session.execute(
        select(Notification).where(Notification.kind == "kr_answered")
    ).scalars().one()
    assert answered_notice.person_id == person.id

    # The answer is now retrievable, so the next asker gets it instead of a gap.
    result = answer_query(
        db_session, "billing-service auth", user_id=person.id, team_id=team.id
    )
    assert any(source.type == "knowledge_repo" for source in result.sources)


def test_routing_an_answered_request_is_a_noop(db_session, team, person):
    kr = create_knowledge_request(db_session, person.id, "Some question here?", route=False)
    kr.status = "indexed"
    db_session.flush()
    result = route_knowledge_request(db_session, kr)
    assert result.reason == "already answered"


def test_duplicate_creation_does_not_double_route(db_session, team, person):
    first = create_knowledge_request(db_session, person.id, "Repeated question?")
    second = create_knowledge_request(db_session, person.id, "Repeated question?")
    assert first.id == second.id
    assert len(db_session.execute(select(Notification)).scalars().all()) == 1


def test_expertise_shifts_change_where_a_reroute_lands(db_session, team, person):
    """Re-running routing must follow the evidence, not a cached decision."""
    first = Person(email="first@example.com", display_name="First", team_id=team.id)
    second = Person(email="second@example.com", display_name="Second", team_id=team.id)
    db_session.add_all([first, second])
    db_session.flush()

    old = datetime.now(UTC) - timedelta(days=200)
    update_expertise(db_session, first.id, ["billing-service"], old)
    kr = create_knowledge_request(db_session, person.id, "A billing-service question?")
    assert kr.routed_to_id == first.id

    for _ in range(6):
        update_expertise(db_session, second.id, ["billing-service"], datetime.now(UTC))
    result = route_knowledge_request(db_session, kr)
    assert result.routed_to == str(second.id)
