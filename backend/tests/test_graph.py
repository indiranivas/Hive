"""Knowledge graph tests -- the memory provider's derivations and the wiring.

Neo4j itself needs a running server, so its provider is exercised only for
selection/config errors here; the Cypher paths mirror the memory semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.core.graph import MemoryGraph, build_graph
from api.models.orm import ExpertiseScore, KnowledgeRequest


@pytest.fixture
def second_person(db_session, team):
    from api.models.orm import Person

    person = Person(email="dev.two@example.com", display_name="Dev Two", team_id=team.id)
    db_session.add(person)
    db_session.flush()
    return person


def _score(db_session, person, topic, score=0.5):
    db_session.add(
        ExpertiseScore(
            person_id=person.id, topic=topic, score=score, evidence_count=2,
            last_seen=datetime.now(UTC),
        )
    )
    db_session.flush()


def test_build_graph_derives_nodes_and_edges(db_session, team, person, artifact_factory):
    artifact_factory("Fix auth", "jwt refresh loop fix")
    _score(db_session, person, "billing-auth")

    nodes, edges = build_graph(db_session, team_id=team.id)
    kinds = {node.kind for node in nodes}
    assert {"person", "topic", "repo"} <= kinds
    assert any(e.kind == "KNOWS" for e in edges)
    assert any(e.kind == "WORKED_IN" for e in edges)


def test_collaborators_found_via_shared_repo_and_topic(
    db_session, team, person, second_person, artifact_factory
):
    artifact_factory("commit one", "auth work")  # person -> test-repo
    from ingestion.embedder import persist_artifact
    from ingestion.normalizer import WorkArtifact

    persist_artifact(
        db_session,
        WorkArtifact(
            source="git", source_id="x2", artifact_type="commit", title="commit two",
            content="more auth work", occurred_at=datetime.now(UTC),
            author_id=second_person.id, author_name=second_person.display_name,
            team_id=team.id, metadata={"repo": "test-repo"},
        ),
    )
    _score(db_session, person, "billing-auth")
    _score(db_session, second_person, "billing-auth")

    result = MemoryGraph().collaborators(db_session, person.id, team_id=team.id)
    assert len(result) == 1
    collaborator = result[0]
    assert collaborator.display_name == "Dev Two"
    # Ingestion also auto-extracts topics from content, so assert containment.
    assert "test-repo" in collaborator.shared_repos
    assert "billing-auth" in collaborator.shared_topics
    # A shared repo counts double a shared topic.
    assert collaborator.strength >= 3.0


def test_bus_factor_flags_single_expert_topics(db_session, team, person, second_person):
    _score(db_session, person, "solo-topic", score=0.9)
    _score(db_session, person, "shared-topic")
    _score(db_session, second_person, "shared-topic")

    at_risk = MemoryGraph().bus_factor(db_session, team_id=team.id)
    assert [t.topic for t in at_risk] == ["solo-topic"]
    assert at_risk[0].expert_name == person.display_name


def test_neighborhood_filters_to_one_hop(db_session, team, person, second_person):
    _score(db_session, person, "topic-a")
    _score(db_session, second_person, "topic-b")

    nodes, edges = MemoryGraph().neighborhood(
        db_session, "topic:topic-a", team_id=team.id
    )
    node_ids = {node.id for node in nodes}
    assert "topic:topic-a" in node_ids
    assert f"person:{person.id}" in node_ids
    assert "topic:topic-b" not in node_ids
    assert all("topic:topic-a" in (e.source, e.target) for e in edges)


def test_knowledge_requests_link_people_and_topics(db_session, team, person, second_person):
    kr = KnowledgeRequest(
        requester_id=person.id, question="How do we rotate the PAT?", status="answered",
        answered_by_id=second_person.id, tags=["ado-pat"],
    )
    db_session.add(kr)
    db_session.flush()

    nodes, edges = build_graph(db_session, team_id=team.id)
    kinds = {(e.kind) for e in edges}
    assert {"ASKED", "ANSWERED", "TAGGED"} <= kinds
    assert any(n.kind == "kr" for n in nodes)


def test_memory_sync_reports_counts(db_session, team, person):
    _score(db_session, person, "topic-a")
    stats = MemoryGraph().sync(db_session, team_id=team.id)
    assert stats["provider"] == "memory"
    assert stats["nodes"] >= 2
    assert stats["edges"] >= 1


def test_settings_select_graph_provider(monkeypatch):
    from api.core import config, graph

    monkeypatch.setenv("GRAPH_PROVIDER", "memory")
    for cached in (config.get_settings, graph.get_graph):
        cached.cache_clear()
    try:
        assert isinstance(graph.get_graph(), MemoryGraph)
    finally:
        for cached in (config.get_settings, graph.get_graph):
            cached.cache_clear()


def test_neo4j_provider_requires_password(monkeypatch):
    pytest.importorskip("neo4j")
    from api.core import config, graph

    monkeypatch.setenv("GRAPH_PROVIDER", "neo4j")
    # Empty env var wins over any password a developer's .env supplies.
    monkeypatch.setenv("NEO4J_PASSWORD", "")
    for cached in (config.get_settings, graph.get_graph):
        cached.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="NEO4J_PASSWORD"):
            graph.get_graph()
    finally:
        for cached in (config.get_settings, graph.get_graph):
            cached.cache_clear()
