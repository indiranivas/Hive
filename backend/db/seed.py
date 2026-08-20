"""Dev seed data: a plausible team work trail so the pipeline is queryable
immediately, with no connector credentials.

Fictional people and repos -- nothing here is real LevelShift data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update

from api.core.config import get_settings
from api.models.orm import Base, KnowledgeRequest, Org, Person, Team
from api.services.knowledge_repo import index_knowledge_request
from ingestion.embedder import persist_artifacts
from ingestion.normalizer import WorkArtifact as ArtifactDTO

NOW = datetime.now(UTC)

PEOPLE = [
    ("nivas.s@levelshift.com", "Nivas S", "manager"),
    ("deepa.v@levelshift.com", "Deepa V", "member"),
    ("arun.k@levelshift.com", "Arun K", "member"),
    ("priya.r@levelshift.com", "Priya R", "member"),
]

# (author_email, days_ago, repo, sha, title, body, files)
COMMITS = [
    (
        "deepa.v@levelshift.com", 2, "billing-service", "a1b2c3d4e5f60718",
        "Fix JWT refresh loop in billing auth middleware",
        "The refresh token was re-issued on every 401 which stampeded the identity\n"
        "provider. Cache the refreshed token for its full TTL and retry once.",
        ["services/billing/auth_middleware.py", "tests/test_auth_middleware.py"],
    ),
    (
        "deepa.v@levelshift.com", 5, "billing-service", "b2c3d4e5f6071829",
        "Add idempotency keys to invoice creation endpoint",
        "Duplicate invoices appeared when the client retried a timed-out POST.\n"
        "Invoice creation now requires an idempotency key stored in Redis.",
        ["services/billing/invoices.py", "services/billing/redis_client.py"],
    ),
    (
        "deepa.v@levelshift.com", 12, "billing-service", "c3d4e5f607182930",
        "Migrate invoice tables to Alembic revision 0007",
        "Adds the invoice_line_items table and backfills currency codes.",
        ["db/migrations/versions/0007_invoice_line_items.py"],
    ),
    (
        "arun.k@levelshift.com", 1, "hive-api", "d4e5f60718293041",
        "Add Azure DevOps work item connector skeleton",
        "Pulls work items via WIQL and normalizes them into WorkArtifact.\n"
        "Webhook handling comes next.",
        ["ingestion/task_connector.py", "tests/test_task_connector.py"],
    ),
    (
        "arun.k@levelshift.com", 4, "hive-api", "e5f6071829304152",
        "Chunk transcripts by speaker turn before embedding",
        "Whole-meeting embeddings washed out topic signal. Chunk on speaker turns\n"
        "with 20 percent overlap.",
        ["ingestion/normalizer.py", "ingestion/embedder.py"],
    ),
    (
        "arun.k@levelshift.com", 9, "hive-api", "f607182930415263",
        "Cache Microsoft Graph tokens in Redis",
        "Graph token requests were rate limited during backfill. Cache per tenant.",
        ["ingestion/graph_auth.py"],
    ),
    (
        "priya.r@levelshift.com", 3, "web-dashboard", "0718293041526374",
        "Build team pulse activity bars with Recharts",
        "Weekly commit, PR and ticket counts per person, with a stale-task flag.",
        ["src/components/ActivityBars.tsx", "src/app/page.tsx"],
    ),
    (
        "priya.r@levelshift.com", 7, "web-dashboard", "1829304152637485",
        "Wire MSAL login and protect dashboard routes",
        "Azure AD sign-in with silent token refresh; managers only past /status.",
        ["src/lib/auth.ts", "src/middleware.ts"],
    ),
    (
        "priya.r@levelshift.com", 15, "web-dashboard", "2930415263748596",
        "Add expertise map force graph",
        "D3 force layout linking topics to people, sized by expertise score.",
        ["src/components/ExpertiseGraph.tsx"],
    ),
    (
        "nivas.s@levelshift.com", 6, "hive-api", "3041526374859607",
        "Tighten scope enforcement on query endpoint",
        "Members can no longer pass an arbitrary team_id. Scope falls back to\n"
        "their own team unless they hold can_query_org.",
        ["api/routes/query.py", "api/core/security.py"],
    ),
    (
        "nivas.s@levelshift.com", 18, "hive-api", "4152637485960718",
        "Add query audit log with latency tracking",
        "Every question is logged with user, sources used, surface and latency.",
        ["api/services/query_engine.py", "db/migrations/versions/0003_query_log.py"],
    ),
]

# (author_email, days_ago, repo, pr_id, title, description, status, branch)
PULL_REQUESTS = [
    (
        "deepa.v@levelshift.com", 2, "billing-service", 312,
        "Billing auth layer hardening",
        "Fixes the JWT refresh loop, adds idempotency keys, and raises auth test\n"
        "coverage on the invoice path. Reviewers: Nivas S, Arun K.",
        "completed", "feature/billing-auth",
    ),
    (
        "arun.k@levelshift.com", 1, "hive-api", 118,
        "Work item connector + transcript chunking",
        "Azure DevOps WIQL pull plus speaker-turn transcript chunking. Still open:\n"
        "webhook signature verification.",
        "active", "feature/ado-connector",
    ),
    (
        "priya.r@levelshift.com", 3, "web-dashboard", 74,
        "Team pulse page",
        "Activity bars, blocker count and highlights. Blocked on the pulse API\n"
        "endpoint returning stale task counts.",
        "active", "feature/team-pulse",
    ),
]

KNOWLEDGE = [
    (
        "arun.k@levelshift.com",
        "nivas.s@levelshift.com",
        "Which Azure DevOps PAT scopes does the Hive task connector need?",
        "Read-only is enough: Work Items (Read), Code (Read) and Project and Team "
        "(Read). Do not grant write scopes -- Hive is read-only by design. Create the "
        "PAT on the service account, not a personal account, and set a 90 day expiry "
        "with a calendar reminder to rotate it.",
        ["azure-devops-api", "personal-access-token", "ingestion"],
    ),
]


def _commit_artifacts(team_id, people):
    artifacts = []
    for email, days_ago, repo, sha, title, body, files in COMMITS:
        person = people[email]
        artifacts.append(
            ArtifactDTO(
                source="git",
                source_id=sha,
                artifact_type="commit",
                title=title,
                content=f"{title}\n\n{body}",
                occurred_at=NOW - timedelta(days=days_ago),
                author_id=person.id,
                author_name=person.display_name,
                team_id=team_id,
                metadata={
                    "repo": repo,
                    "provider": "seed",
                    "sha": sha,
                    "author_email": email,
                    "files_changed": files,
                    "file_count": len(files),
                },
            )
        )
    return artifacts


def _pr_artifacts(team_id, people):
    artifacts = []
    for email, days_ago, repo, pr_id, title, description, status, branch in PULL_REQUESTS:
        person = people[email]
        artifacts.append(
            ArtifactDTO(
                source="git",
                source_id=f"pr-{repo}-{pr_id}",
                artifact_type="pull_request",
                title=f"PR #{pr_id}: {title}",
                content=f"{title}\n{description}\nStatus: {status}",
                occurred_at=NOW - timedelta(days=days_ago),
                author_id=person.id,
                author_name=person.display_name,
                team_id=team_id,
                metadata={
                    "repo": repo,
                    "provider": "seed",
                    "pr_id": pr_id,
                    "status": status,
                    "source_branch": branch,
                    "target_branch": "main",
                    "author_email": email,
                },
            )
        )
    return artifacts


# Only the org chart survives a reset; everything else is derived data.
KEPT_TABLES = {"orgs", "teams", "people"}


def reset_data(session) -> None:
    """Clear derived data, then the seeded people.

    Tables are emptied in reverse dependency order taken from the metadata rather
    than a hand-written list -- a new table that references people (the
    notification outbox did) would otherwise break this with a foreign key error.
    """
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in KEPT_TABLES:
            session.execute(table.delete())

    # teams.manager_id still points at a seeded person -- clear it before the delete.
    session.execute(update(Team).values(manager_id=None))
    session.execute(delete(Person).where(Person.email.in_([email for email, _, _ in PEOPLE])))
    session.flush()


def seed_demo_data(session, reset: bool = False) -> dict[str, int]:
    if reset:
        reset_data(session)

    org = session.execute(select(Org).where(Org.name == "LevelShift")).scalar_one_or_none()
    if org is None:
        org = Org(name="LevelShift")
        session.add(org)
        session.flush()

    team = session.execute(select(Team).where(Team.name == "Platform")).scalar_one_or_none()
    if team is None:
        team = Team(name="Platform", org_id=org.id)
        session.add(team)
        session.flush()

    people: dict[str, Person] = {}
    for email, display_name, role in PEOPLE:
        person = session.execute(
            select(Person).where(Person.email == email)
        ).scalar_one_or_none()
        if person is None:
            person = Person(email=email, display_name=display_name, role=role, team_id=team.id)
            session.add(person)
            session.flush()
        else:
            person.team_id = person.team_id or team.id
        people[email] = person

    team.manager_id = people["nivas.s@levelshift.com"].id

    # Put the local dev user on the demo team so the dashboard has a scope that
    # actually contains data.
    dev_email = get_settings().dev_user_email.lower()
    dev_user = session.execute(
        select(Person).where(func.lower(Person.email) == dev_email)
    ).scalar_one_or_none()
    if dev_user is None:
        dev_user = Person(email=dev_email, display_name="Hive Dev User", role="admin")
        session.add(dev_user)
    dev_user.team_id = team.id
    dev_user.role = "admin"
    session.flush()

    artifacts = _commit_artifacts(team.id, people) + _pr_artifacts(team.id, people)
    result = persist_artifacts(session, artifacts)

    knowledge_indexed = 0
    for requester_email, answerer_email, question, answer, tags in KNOWLEDGE:
        existing = session.execute(
            select(KnowledgeRequest).where(KnowledgeRequest.question == question)
        ).scalar_one_or_none()
        if existing:
            continue
        kr = KnowledgeRequest(
            requester_id=people[requester_email].id,
            question=question,
            context="Setting up the Azure DevOps connector for Hive ingestion.",
            status="answered",
            routed_to_id=people[answerer_email].id,
            answer=answer,
            answered_by_id=people[answerer_email].id,
            # Asked 10 days ago, answered 2 days later -- resolution time is a
            # real number the gap analytics can average.
            created_at=NOW - timedelta(days=10),
            answered_at=NOW - timedelta(days=8),
            tags=tags,
        )
        session.add(kr)
        session.flush()
        if index_knowledge_request(session, kr):
            knowledge_indexed += 1

    return {
        "people": len(people),
        "artifacts": result.created + result.updated,
        "chunks": result.chunks,
        "knowledge": knowledge_indexed,
    }
