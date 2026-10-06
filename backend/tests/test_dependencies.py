"""Repo coupling and ownership -- the evidence behind blast radius.

The thing under test is as much the *honesty* of the signal as the arithmetic:
coupling must never appear without evidence to justify it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api.models.orm import Person
from api.services.dependencies import (
    Coupling,
    _Row,
    blast_radius,
    coupling_from_rows,
    known_repos,
    repo_coupling,
    repo_owners,
)


def _commit(artifact_factory, repo, title, body, days_ago, sha):
    return artifact_factory(
        title, body, days_ago=days_ago, metadata={"repo": repo, "sha": sha}
    )


def test_no_coupling_without_a_shared_signal(db_session, person, artifact_factory):
    """Two repos one person never touches together are not coupled."""
    other = Person(email="two@example.com", display_name="Dev Two", team_id=person.team_id)
    db_session.add(other)
    db_session.flush()

    _commit(artifact_factory, "alpha", "alpha work", "one", 2, "aaa1")
    from ingestion.embedder import persist_artifact
    from ingestion.normalizer import WorkArtifact

    persist_artifact(
        db_session,
        WorkArtifact(
            source="git", source_id="b1", artifact_type="commit", title="beta work",
            content="two", occurred_at=datetime.now(UTC) - timedelta(days=200),
            author_id=other.id, author_name=other.display_name,
            team_id=person.team_id, metadata={"repo": "beta"},
        ),
    )
    db_session.flush()

    couplings = repo_coupling(db_session, since_days=30)
    assert couplings == []


def test_shared_contributor_and_co_change_are_scored_separately(
    db_session, person, artifact_factory
):
    # Contributor overlap is calendar-independent, so it can go through the DB.
    _commit(artifact_factory, "alpha", "alpha work", "one", 1, "aaa2")
    _commit(artifact_factory, "beta", "beta work", "two", 2, "bbb2")
    db_session.flush()

    couplings = {c.other: c for c in repo_coupling(db_session) if c.repo == "alpha"}
    assert "beta" in couplings
    assert couplings["beta"].shared_contributors == [person.display_name]

    # Co-change is per ISO week, so pin the weeks rather than trusting "1 and 2
    # days ago" to land inside one -- across a Sunday/Monday boundary they do
    # not, and this asserted the calendar instead of the code.
    rows = [
        _Row(author_id=person.id, repo="alpha", week="2026-W12", text=""),
        _Row(author_id=person.id, repo="beta", week="2026-W12", text=""),
        _Row(author_id=person.id, repo="beta", week="2026-W13", text=""),
    ]
    coupling = next(
        c
        for c in coupling_from_rows(rows, {person.id: person.display_name})
        if c.repo == "alpha" and c.other == "beta"
    )
    assert coupling.co_changed_weeks == 1  # only W12 has both
    assert coupling.shared_contributors == [person.display_name]
    assert "changed together" in coupling.why()
    assert "shared contributors" in coupling.why()


def test_co_change_needs_the_same_person_in_the_same_week(person):
    """Different weeks, or different people, is not co-change."""
    names = {person.id: person.display_name}

    straddling = [
        _Row(author_id=person.id, repo="alpha", week="2026-W12", text=""),
        _Row(author_id=person.id, repo="beta", week="2026-W13", text=""),
    ]
    coupling = next(
        c for c in coupling_from_rows(straddling, names) if c.repo == "alpha"
    )
    # Still a shared contributor, but nothing moved together.
    assert coupling.co_changed_weeks == 0
    assert coupling.shared_contributors == [person.display_name]


def test_cross_references_are_the_strongest_signal_and_are_opt_in(
    db_session, person, artifact_factory
):
    _commit(artifact_factory, "billing", "use the identity client",
            "point billing at identity for tokens", 1, "ccc1")
    _commit(artifact_factory, "identity", "issue tokens", "nothing else named here", 2, "ddd1")
    db_session.flush()

    with_refs = {(c.repo, c.other): c for c in repo_coupling(db_session)}
    without = {
        (c.repo, c.other): c
        for c in repo_coupling(db_session, include_references=False)
    }

    assert with_refs[("billing", "identity")].cross_references >= 1
    assert without[("billing", "identity")].cross_references == 0
    # The reference makes the relationship directional and stronger.
    assert with_refs[("billing", "identity")].strength > without[
        ("billing", "identity")
    ].strength


def test_a_repo_name_is_matched_on_word_boundaries(db_session, person, artifact_factory):
    """`billing` must not fire on `rebilling`."""
    _commit(artifact_factory, "alpha", "rebilling adjustments", "rebilling only", 1, "eee1")
    _commit(artifact_factory, "billing", "invoices", "unrelated", 2, "fff1")
    db_session.flush()

    coupling = next(
        c for c in repo_coupling(db_session) if c.repo == "alpha" and c.other == "billing"
    )
    assert coupling.cross_references == 0


def test_strength_orders_the_signals():
    assert Coupling("a", "b", cross_references=1).strength > Coupling(
        "a", "b", co_changed_weeks=1
    ).strength
    assert Coupling("a", "b", co_changed_weeks=1).strength > Coupling(
        "a", "b", shared_contributors=["x"]
    ).strength


def test_owners_are_ranked_by_volume_in_the_window(db_session, team, person, artifact_factory):
    from ingestion.embedder import persist_artifact
    from ingestion.normalizer import WorkArtifact

    quiet = Person(email="quiet@example.com", display_name="Quiet One", team_id=team.id)
    db_session.add(quiet)
    db_session.flush()

    for index in range(3):
        _commit(artifact_factory, "svc", f"change {index}", "body", index + 1, f"s{index}")
    persist_artifact(
        db_session,
        WorkArtifact(
            source="git", source_id="q1", artifact_type="commit", title="one change",
            content="body", occurred_at=datetime.now(UTC) - timedelta(days=2),
            author_id=quiet.id, author_name=quiet.display_name, team_id=team.id,
            metadata={"repo": "svc"},
        ),
    )
    db_session.flush()

    owners = repo_owners(db_session, "svc")
    assert [owner.name for owner in owners] == [person.display_name, "Quiet One"]
    assert owners[0].artifacts == 3
    assert owners[0].last_seen is not None


def test_known_repos_and_path_resolution(db_session, person, artifact_factory):
    artifact_factory("work", "body", days_ago=1,
                     metadata={"repo": "data-pipeline", "files_changed": ["pipeline/facts.py"]})
    db_session.flush()

    assert known_repos(db_session) == ["data-pipeline"]

    radius = blast_radius(db_session, "data-pipeline/pipeline/facts.py")
    assert radius.target == "data-pipeline"
    assert radius.kind == "module"

    direct = blast_radius(db_session, "data-pipeline")
    assert direct.kind == "repo"


def test_blast_radius_carries_the_owners_of_each_coupled_repo(
    db_session, person, artifact_factory
):
    _commit(artifact_factory, "alpha", "alpha work", "same week", 1, "g1")
    _commit(artifact_factory, "beta", "beta work", "same week", 2, "g2")
    db_session.flush()

    radius = blast_radius(db_session, "alpha")
    assert [c.other for c in radius.coupled] == ["beta"]
    assert radius.owners_by_repo["beta"][0].name == person.display_name
