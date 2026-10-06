"""The MCP tool surface, exercised without the MCP SDK.

mcp_server/tools.py holds no `mcp` import, so everything Claude can actually ask
Hive is testable here. The transport itself is covered in test_mcp_transport.py,
which skips unless the SDK is installed.
"""

from __future__ import annotations

import inspect
import uuid

from sqlalchemy import select

from api.models.orm import KnowledgeRequest, Person, QueryLog
from mcp_server import tools


def _commit(db_session):
    """Tools open their own session, so fixture data has to be committed first."""
    db_session.commit()


# --- the surface itself ----------------------------------------------------------


def test_every_tool_is_named_described_and_callable():
    assert tools.TOOLS, "no tools registered"
    for spec in tools.TOOLS:
        assert spec.name.startswith("hive_"), spec.name
        assert callable(spec.handler)
        # The description is what makes Claude reach for the tool unprompted.
        assert len(spec.description) > 80, f"{spec.name} description is too thin"
    names = [spec.name for spec in tools.TOOLS]
    assert len(names) == len(set(names)), "duplicate tool name"


def test_handlers_publish_real_parameter_names():
    """Regression: a **kwargs wrapper made every tool take one arg called 'kwargs'.

    FastMCP builds each tool's input schema from the handler signature, so a
    wrapper that loses it produces tools no client can call.
    """
    for spec in tools.TOOLS:
        signature = inspect.signature(spec.handler)
        assert signature.parameters, f"{spec.name} takes no arguments"
        for parameter in signature.parameters.values():
            assert parameter.kind is not inspect.Parameter.VAR_KEYWORD, (
                f"{spec.name} publishes **{parameter.name} instead of named arguments"
            )


def test_a_failing_tool_returns_a_sentence_rather_than_raising():
    def explode(problem: str) -> str:
        raise RuntimeError("the database fell over")

    guarded = tools._safe(explode)
    reply = guarded(problem="anything")

    assert "RuntimeError" in reply
    assert "the database fell over" in reply
    assert "Nothing was changed" in reply
    # wraps() keeps the signature FastMCP needs.
    assert list(inspect.signature(guarded).parameters) == ["problem"]


def test_dispatch_rejects_an_unknown_tool():
    reply = tools.dispatch("hive_make_coffee")
    assert "Unknown tool" in reply
    assert "hive_prior_art" in reply


# --- scenario 1: has anyone hit this before? -------------------------------------


def test_prior_art_names_the_person_the_file_and_the_reference(
    db_session, person, artifact_factory
):
    artifact_factory(
        "Fix JWT refresh loop in billing auth",
        "The refresh token was re-issued on every 401 which stampeded the identity provider.",
        days_ago=3,
        metadata={
            "repo": "billing-service",
            "sha": "a1b2c3d4e5f6",
            "files_changed": ["services/billing/auth_middleware.py"],
        },
    )
    _commit(db_session)

    reply = tools.prior_art("jwt refresh loop")

    assert person.display_name in reply
    assert "services/billing/auth_middleware.py" in reply
    assert "billing-service@a1b2c3d4" in reply
    assert "3d ago" in reply
    # Never presented as a verified fix.
    assert "not a verified fix" in reply


def test_prior_art_admits_a_gap_instead_of_inventing_one(db_session, person, artifact_factory):
    artifact_factory("Unrelated work", "dashboard chart colours", days_ago=1)
    _commit(db_session)

    reply = tools.prior_art("kubernetes ingress certificate rotation")

    assert "No prior art" in reply
    assert "hive_raise_request" in reply


def test_prior_art_flags_when_two_people_took_different_approaches(
    db_session, team, person, artifact_factory
):
    from ingestion.embedder import persist_artifact
    from ingestion.normalizer import WorkArtifact

    other = Person(email="two@example.com", display_name="Dev Two", team_id=team.id)
    db_session.add(other)
    db_session.flush()

    artifact_factory(
        "Retry the connection on timeout",
        "connection pool timeout under load; added a retry",
        days_ago=2,
        metadata={"repo": "svc", "sha": "aaa11122"},
    )
    persist_artifact(
        db_session,
        WorkArtifact(
            source="git", source_id="bbb2", artifact_type="commit",
            title="Raise the pool size instead of retrying",
            content="connection pool timeout under load; raised the pool size",
            occurred_at=artifact_factory("seedling", "x", days_ago=9).occurred_at,
            author_id=other.id, author_name=other.display_name, team_id=team.id,
            metadata={"repo": "svc", "sha": "bbb22233"},
        ),
    )
    _commit(db_session)

    reply = tools.prior_art("connection pool timeout under load")

    assert "different people" in reply
    assert person.display_name in reply and "Dev Two" in reply


# --- scenario 2: what breaks if I change this? -----------------------------------


def test_blast_radius_reports_coupled_repos_with_their_evidence(
    db_session, team, person, artifact_factory
):
    # One person working in both repos, in the same week, is the coupling signal.
    artifact_factory("identity work", "rotate signing keys", days_ago=1,
                     metadata={"repo": "identity-service", "sha": "1111aaaa"})
    artifact_factory("billing work", "use the identity-service client", days_ago=2,
                     metadata={"repo": "billing-service", "sha": "2222bbbb"})
    _commit(db_session)

    reply = tools.blast_radius_of("identity-service")

    assert "Blast radius for identity-service" in reply
    assert "billing-service" in reply
    assert person.display_name in reply
    # The caveat is not optional: this is inference, not a parsed manifest.
    assert "no manifests" in reply and "not proof of a dependency" in reply


def test_blast_radius_resolves_a_file_path_to_its_repo(db_session, person, artifact_factory):
    artifact_factory("pipeline work", "partitioned the fact table", days_ago=1,
                     metadata={"repo": "data-pipeline", "sha": "3333cccc",
                               "files_changed": ["pipeline/facts.py"]})
    _commit(db_session)

    reply = tools.blast_radius_of("data-pipeline/pipeline/facts.py")
    assert "Blast radius for data-pipeline" in reply


def test_blast_radius_on_an_unknown_target_lists_what_it_does_know(
    db_session, person, artifact_factory
):
    artifact_factory("known work", "something", days_ago=1, metadata={"repo": "real-repo"})
    _commit(db_session)

    reply = tools.blast_radius_of("imaginary-service")
    assert "no ingested work" in reply.lower()
    assert "real-repo" in reply


# --- scenario 3: I have never worked here ----------------------------------------


def test_area_briefing_lists_contributors_and_answered_problems(
    db_session, team, person, artifact_factory
):
    artifact = artifact_factory(
        "Partition the fact table", "full scans were timing out", days_ago=4,
        metadata={"repo": "data-pipeline", "sha": "4444dddd",
                  "files_changed": ["pipeline/facts.py"]},
    )
    db_session.add(
        KnowledgeRequest(
            requester_id=person.id,
            question="Why did the nightly backfill stall?",
            status="indexed",
            answer="The retention sweep held a table lock; it is incremental now.",
            answered_by_id=person.id,
            related_artifacts=[str(artifact.id)],
        )
    )
    _commit(db_session)

    reply = tools.area_brief("data-pipeline")

    assert "matched as a repo" in reply
    assert person.display_name in reply
    assert "Why did the nightly backfill stall?" in reply
    assert "pipeline/facts.py" in reply


def test_area_briefing_says_so_when_nothing_is_written_down(
    db_session, person, artifact_factory
):
    artifact_factory("lonely commit", "nobody documented this", days_ago=1,
                     metadata={"repo": "quiet-repo"})
    _commit(db_session)

    reply = tools.area_brief("quiet-repo")
    assert "No answered Knowledge Requests touch this area" in reply


# --- the remaining tools ----------------------------------------------------------


def test_who_knows_reports_scored_evidence(db_session, person, artifact_factory):
    artifact_factory("billing auth work", "jwt refresh in the billing service", days_ago=1)
    _commit(db_session)

    reply = tools.who_knows("billing")
    assert person.display_name in reply or "Nobody has scored evidence" in reply


def test_ask_is_written_to_the_audit_log_as_the_mcp_surface(
    db_session, person, artifact_factory
):
    artifact_factory("Auth work", "jwt refresh loop fix", days_ago=1)
    _commit(db_session)

    tools.ask("who fixed the jwt refresh loop?")

    db_session.expire_all()
    logged = db_session.execute(select(QueryLog)).scalars().all()
    assert [entry.surface for entry in logged] == ["mcp"]


def test_raise_request_records_and_routes_the_gap(db_session, person):
    _commit(db_session)

    reply = tools.raise_request("How do we rotate the warehouse credentials?")

    assert "Knowledge Request recorded" in reply
    db_session.expire_all()
    krs = db_session.execute(select(KnowledgeRequest)).scalars().all()
    assert len(krs) == 1
    assert str(krs[0].id) in reply


def test_raise_request_refuses_an_empty_question(db_session, person):
    _commit(db_session)
    assert "needs an actual question" in tools.raise_request("  ")


# --- scoping ----------------------------------------------------------------------


def test_scope_follows_the_role_table_not_a_rule_of_its_own():
    member = Person(email="m@example.com", display_name="M", role="member",
                    team_id=uuid.uuid4())
    stranger = Person(email="s@example.com", display_name="S", role="nobody",
                      team_id=uuid.uuid4())

    # can_query_org is granted to member/manager/admin, so they reach org-wide;
    # an unknown role falls back to member, which also holds it.
    assert tools._scope(member) is None
    assert tools._scope_name(member) == "org"
    assert tools._scope(stranger) is None
