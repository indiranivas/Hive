"""Knowledge graph tests -- the memory provider's derivations and the wiring.

Neo4j itself needs a running server, so its provider is exercised only for
selection/config errors here; the Cypher paths mirror the memory semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.core.graph import MemoryGraph, _module_of, build_graph
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


def _edges(edges, kind):
    return [e for e in edges if e.kind == kind]


def test_org_chart_is_part_of_the_graph(db_session, team, person, second_person):
    team.manager_id = person.id
    db_session.flush()

    nodes, edges = build_graph(db_session, team_id=team.id)
    kinds = {node.kind for node in nodes}
    assert {"org", "team"} <= kinds
    # Both people belong to the team; only one manages it.
    assert len(_edges(edges, "MEMBER_OF")) == 2
    assert [e.source for e in _edges(edges, "MANAGES")] == [f"person:{person.id}"]
    assert len(_edges(edges, "PART_OF")) == 1


def test_artifacts_link_to_author_repo_topic_and_module(
    db_session, team, person, artifact_factory
):
    artifact_factory(
        "Rotate signing keys",
        "publish the new jwks entry before switching the signer",
        metadata={
            "repo": "identity-service",
            "sha": "abc12345",
            "files_changed": ["identity/keys.py", "tests/identity/test_keys.py"],
        },
    )

    nodes, edges = build_graph(db_session, team_id=team.id)
    assert {"artifact", "module"} <= {node.kind for node in nodes}
    assert len(_edges(edges, "AUTHORED")) == 1
    assert len(_edges(edges, "IN_REPO")) == 1
    # Topics come from the embedder's extraction, so assert presence not count.
    assert _edges(edges, "ABOUT")
    modules = {node.label for node in nodes if node.kind == "module"}
    assert modules == {"identity", "tests/identity"}


def test_pull_request_reviewers_become_reviewed_edges(
    db_session, team, person, second_person, artifact_factory
):
    artifact_factory(
        "PR #45: key rotation",
        "overlapping jwks publication",
        artifact_type="pull_request",
        metadata={
            "repo": "identity-service",
            "pr_id": 45,
            # The author reviewing their own PR is not a relationship.
            "reviewers": [second_person.email.upper(), person.email],
        },
    )

    _, edges = build_graph(db_session, team_id=team.id)
    reviewed = _edges(edges, "REVIEWED")
    assert [e.source for e in reviewed] == [f"person:{second_person.id}"]


def test_knowledge_request_routing_and_citations_are_edges(
    db_session, team, person, second_person, artifact_factory
):
    artifact = artifact_factory("Idempotency keys", "invoice retries created duplicates")
    kr = KnowledgeRequest(
        requester_id=person.id,
        question="Why did invoice retries duplicate?",
        status="routed",
        routed_to_id=second_person.id,
        tags=["idempotency"],
        related_artifacts=[str(artifact.id)],
    )
    db_session.add(kr)
    db_session.flush()

    _, edges = build_graph(db_session, team_id=team.id)
    assert [e.target for e in _edges(edges, "ROUTED_TO")] == [f"person:{second_person.id}"]
    assert [e.target for e in _edges(edges, "REFERENCES")] == [f"artifact:{artifact.id}"]


def test_collaborates_with_edge_matches_the_collaborators_query(
    db_session, team, person, second_person, artifact_factory
):
    """The materialised edge and the computed answer must not drift apart."""
    from ingestion.embedder import persist_artifact
    from ingestion.normalizer import WorkArtifact

    artifact_factory("commit one", "auth work")
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

    _, edges = build_graph(db_session, team_id=team.id)
    collaboration = _edges(edges, "COLLABORATES_WITH")
    assert len(collaboration) == 1

    computed = MemoryGraph().collaborators(db_session, person.id, team_id=team.id)
    assert collaboration[0].weight == computed[0].strength


def test_artifact_cap_bounds_nodes_without_shrinking_repo_history(
    db_session, team, person, artifact_factory, monkeypatch
):
    from api.core import config

    monkeypatch.setenv("GRAPH_MAX_ARTIFACTS", "2")
    config.get_settings.cache_clear()
    try:
        for index in range(5):
            artifact_factory(f"commit {index}", f"auth work {index}", days_ago=index + 1)

        nodes, edges = build_graph(db_session, team_id=team.id)
        assert len([n for n in nodes if n.kind == "artifact"]) == 2
        # WORKED_IN is an aggregate over every artifact, capped or not.
        worked_in = _edges(edges, "WORKED_IN")
        assert [e.weight for e in worked_in] == [5.0]
    finally:
        config.get_settings.cache_clear()


def test_module_folding_ignores_bare_filenames():
    assert _module_of("services/billing/invoices.py") == "services/billing"
    assert _module_of("src\\lib\\auth.ts") == "src/lib"
    assert _module_of("README.md") is None


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
