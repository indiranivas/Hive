"""Knowledge graph abstraction -- swap providers via GRAPH_PROVIDER.

`memory` (the default) derives the graph from the relational tables on every
call: no extra service, never stale, and right-sized for a single team's data.
`neo4j` mirrors the same graph into Neo4j Community Edition (open source) over
Bolt, where it can be queried with Cypher and shared by other tools; refresh it
with sync() (POST /api/graph/sync) after ingestion.

The graph model, derived entirely from existing tables:

    (Team)-[:PART_OF]->(Org)                       teams.org_id
    (Person)-[:MEMBER_OF]->(Team)                  people.team_id
    (Person)-[:MANAGES]->(Team)                    teams.manager_id
    (Person)-[:KNOWS {weight=score}]->(Topic)      expertise_scores
    (Person)-[:WORKED_IN {weight=count}]->(Repo)   work_artifacts metadata
    (Person)-[:AUTHORED]->(Artifact)               work_artifacts.author_id
    (Person)-[:REVIEWED]->(Artifact)               work_artifacts metadata.reviewers
    (Artifact)-[:IN_REPO]->(Repo)                  work_artifacts metadata.repo
    (Artifact)-[:ABOUT]->(Topic)                   work_artifacts metadata.topics
    (Artifact)-[:TOUCHED]->(Module)                metadata.files_changed, folded to dir
    (Person)-[:ASKED]->(KR)                        knowledge_requests
    (Person)-[:ANSWERED]->(KR)                     knowledge_requests
    (KR)-[:ROUTED_TO]->(Person)                    knowledge_requests.routed_to_id
    (KR)-[:TAGGED]->(Topic)                        knowledge_requests.tags
    (KR)-[:REFERENCES]->(Artifact)                 knowledge_requests.related_artifacts
    (Person)-[:COLLABORATES_WITH]->(Person)        derived: shared repos and topics
    (Repo)-[:COUPLED_WITH]->(Repo)                 derived: shared contributors, co-change

The last two are the only edges with no row behind them. COLLABORATES_WITH is
the shared-signal overlap `collaborators()` already computes, materialised so
Neo4j can traverse it in one hop instead of rediscovering it in every query.
COUPLED_WITH is *not* a dependency edge -- Hive parses no manifests, so it says
"these repos keep moving together", never "this one imports that one". The
evidence behind it lives in api/services/dependencies.py.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.models.orm import ExpertiseScore, KnowledgeRequest, Org, Person, Team, WorkArtifact

logger = logging.getLogger(__name__)

# A shared repo is direct collaboration; a shared topic is only shared knowledge.
REPO_AFFINITY = 2.0
TOPIC_AFFINITY = 1.0


@dataclass(slots=True)
class GraphNode:
    id: str
    label: str
    kind: str  # person | topic | repo | kr
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str  # KNOWS | WORKED_IN | ASKED | ANSWERED | TAGGED
    weight: float = 1.0


@dataclass(slots=True)
class Collaborator:
    person_id: str
    display_name: str
    email: str
    shared_topics: list[str]
    shared_repos: list[str]
    strength: float


@dataclass(slots=True)
class BusFactorTopic:
    topic: str
    expert_id: str
    expert_name: str
    score: float
    evidence_count: int


def _node_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _module_of(path: str) -> str | None:
    """Fold a changed file path to the module that owns it.

    `services/billing/auth_middleware.py` -> `services/billing`. One node per
    directory rather than per file: a file node per commit would swamp the graph
    and nobody asks "who touched line 40 of this file" of a knowledge graph.
    """
    directory, separator, _ = str(path).replace("\\", "/").rpartition("/")
    return directory.strip("/") if separator and directory.strip("/") else None


def _clean(meta: dict[str, Any]) -> dict[str, Any]:
    """Node properties must be primitives: Neo4j rejects nested maps in `SET n +=`."""
    return {
        key: value
        for key, value in meta.items()
        if value is not None and isinstance(value, (str, int, float, bool))
    }


def _shared_signals(
    edges: list[GraphEdge],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Per-person topic and repo sets, read back off the edges already built."""
    topics: dict[str, set[str]] = defaultdict(set)
    repos: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.kind == "KNOWS":
            topics[edge.source].add(edge.target)
        elif edge.kind == "WORKED_IN":
            repos[edge.source].add(edge.target)
    return topics, repos


def affinity(shared_repos: int, shared_topics: int) -> float:
    return shared_repos * REPO_AFFINITY + shared_topics * TOPIC_AFFINITY


def build_graph(
    session: Session, team_id: uuid.UUID | None = None
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Derive the whole team graph from the relational tables.

    Shared by both providers: `memory` serves queries straight off it and
    `neo4j` mirrors it into the database on sync().
    """
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def node(kind: str, key: str, label: str, **meta: Any) -> str:
        node_id = _node_id(kind, key)
        nodes.setdefault(
            node_id, GraphNode(id=node_id, label=label, kind=kind, meta=_clean(meta))
        )
        return node_id

    def link(source: str, target: str, kind: str, weight: float = 1.0) -> None:
        edges.append(GraphEdge(source=source, target=target, kind=kind, weight=weight))

    # --- people, and the org chart they hang off ---------------------------------
    people_query = select(Person)
    if team_id:
        people_query = people_query.where(Person.team_id == team_id)
    people = {person.id: person for person in session.execute(people_query).scalars()}
    person_node = {
        person.id: node(
            "person", str(person.id), person.display_name, email=person.email, role=person.role
        )
        for person in people.values()
    }
    by_email = {person.email.lower(): person.id for person in people.values()}

    team_ids = {person.team_id for person in people.values() if person.team_id}
    teams = (
        {
            team.id: team
            for team in session.execute(select(Team).where(Team.id.in_(team_ids))).scalars()
        }
        if team_ids
        else {}
    )
    org_ids = {team.org_id for team in teams.values() if team.org_id}
    orgs = (
        {org.id: org for org in session.execute(select(Org).where(Org.id.in_(org_ids))).scalars()}
        if org_ids
        else {}
    )
    for team in teams.values():
        team_node = node("team", str(team.id), team.name)
        if team.org_id in orgs:
            link(team_node, node("org", str(team.org_id), orgs[team.org_id].name), "PART_OF")
        if team.manager_id in person_node:
            link(person_node[team.manager_id], team_node, "MANAGES")
    for person in people.values():
        if person.team_id in teams:
            link(person_node[person.id], _node_id("team", str(person.team_id)), "MEMBER_OF")

    # --- expertise ---------------------------------------------------------------
    scores = session.execute(
        select(ExpertiseScore).where(ExpertiseScore.person_id.in_(people.keys()))
    ).scalars()
    for score in scores:
        topic_id = node("topic", score.topic, score.topic)
        link(person_node[score.person_id], topic_id, "KNOWS", round(score.score, 4))

    # --- artifacts, and everything they connect ----------------------------------
    # Only the columns the graph needs: `content` is the largest column in the
    # database and nothing here reads it.
    artifact_rows = session.execute(
        select(
            WorkArtifact.id,
            WorkArtifact.author_id,
            WorkArtifact.artifact_type,
            WorkArtifact.title,
            WorkArtifact.occurred_at,
            WorkArtifact.meta,
        )
        .where(WorkArtifact.author_id.in_(people.keys()))
        .order_by(WorkArtifact.occurred_at.desc())
    ).all()

    # WORKED_IN is an aggregate over *every* artifact, not just the ones that get
    # their own node -- the cap must not silently shrink someone's repo history.
    repo_counts: dict[tuple[uuid.UUID, str], int] = defaultdict(int)
    for row in artifact_rows:
        repo = (row.meta or {}).get("repo")
        if repo and row.author_id:
            repo_counts[(row.author_id, str(repo))] += 1
    for (author_id, repo), count in repo_counts.items():
        link(person_node[author_id], node("repo", repo, repo), "WORKED_IN", float(count))

    for row in artifact_rows[: get_settings().graph_max_artifacts]:
        meta = row.meta or {}
        occurred = row.occurred_at.date().isoformat() if row.occurred_at else None
        artifact_id = node(
            "artifact",
            str(row.id),
            row.title or f"{row.artifact_type} {str(row.id)[:8]}",
            type=row.artifact_type,
            date=occurred,
            reference=meta.get("sha") or meta.get("pr_id") or meta.get("work_item_id"),
            status=meta.get("status"),
        )
        if row.author_id in person_node:
            link(person_node[row.author_id], artifact_id, "AUTHORED")
        if meta.get("repo"):
            link(artifact_id, node("repo", str(meta["repo"]), str(meta["repo"])), "IN_REPO")
        for topic in meta.get("topics") or []:
            link(artifact_id, node("topic", str(topic), str(topic)), "ABOUT")
        for path in meta.get("files_changed") or []:
            module = _module_of(path)
            if module:
                link(artifact_id, node("module", module, module), "TOUCHED")
        for reviewer in meta.get("reviewers") or []:
            reviewer_id = by_email.get(str(reviewer).strip().lower())
            if reviewer_id and reviewer_id != row.author_id:
                link(person_node[reviewer_id], artifact_id, "REVIEWED")

    # --- knowledge requests ------------------------------------------------------
    # Anyone in scope who asked, was routed a question, or answered one: a request
    # routed to this team from elsewhere is still part of this team's graph.
    krs = session.execute(
        select(KnowledgeRequest).where(
            or_(
                KnowledgeRequest.requester_id.in_(people.keys()),
                KnowledgeRequest.routed_to_id.in_(people.keys()),
                KnowledgeRequest.answered_by_id.in_(people.keys()),
            )
        )
    ).scalars()
    for kr in krs:
        kr_id = node(
            "kr",
            str(kr.id),
            (kr.question[:80] + "…") if len(kr.question) > 80 else kr.question,
            status=kr.status,
        )
        if kr.requester_id in person_node:
            link(person_node[kr.requester_id], kr_id, "ASKED")
        if kr.routed_to_id in person_node:
            link(kr_id, person_node[kr.routed_to_id], "ROUTED_TO")
        if kr.answered_by_id in person_node:
            link(person_node[kr.answered_by_id], kr_id, "ANSWERED")
        for tag in kr.tags or []:
            link(kr_id, node("topic", tag, tag), "TAGGED")
        for artifact_ref in kr.related_artifacts or []:
            target = _node_id("artifact", str(artifact_ref))
            if target in nodes:
                link(kr_id, target, "REFERENCES")

    # --- derived: which repos move together --------------------------------------
    # Built from the rows already loaded above -- no second query, and no artifact
    # bodies, so the cross-reference signal is left to the blast-radius service.
    from api.services.dependencies import _iso_week, _Row, coupling_from_rows

    coupling_rows = [
        _Row(
            author_id=row.author_id,
            repo=str((row.meta or {}).get("repo")),
            week=_iso_week(row.occurred_at),
            text="",
        )
        for row in artifact_rows
        if (row.meta or {}).get("repo")
    ]
    person_names = {person.id: person.display_name for person in people.values()}
    for coupling in coupling_from_rows(coupling_rows, person_names):
        # One direction only: the relationship is symmetric without references.
        if coupling.repo < coupling.other:
            link(
                node("repo", coupling.repo, coupling.repo),
                node("repo", coupling.other, coupling.other),
                "COUPLED_WITH",
                coupling.strength,
            )

    # --- derived: who overlaps with whom -----------------------------------------
    topics_by_person, repos_by_person = _shared_signals(edges)
    for left, right in combinations(sorted(person_node.values()), 2):
        shared_repos = repos_by_person[left] & repos_by_person[right]
        shared_topics = topics_by_person[left] & topics_by_person[right]
        if not shared_repos and not shared_topics:
            continue
        link(
            left,
            right,
            "COLLABORATES_WITH",
            affinity(len(shared_repos), len(shared_topics)),
        )

    return list(nodes.values()), edges


class KnowledgeGraph(ABC):
    provider: str

    @abstractmethod
    def overview(
        self, session: Session, team_id: uuid.UUID | None = None
    ) -> tuple[list[GraphNode], list[GraphEdge]]: ...

    @abstractmethod
    def neighborhood(
        self, session: Session, node_id: str, team_id: uuid.UUID | None = None
    ) -> tuple[list[GraphNode], list[GraphEdge]]: ...

    @abstractmethod
    def collaborators(
        self, session: Session, person_id: uuid.UUID, team_id: uuid.UUID | None = None
    ) -> list[Collaborator]: ...

    @abstractmethod
    def bus_factor(
        self, session: Session, team_id: uuid.UUID | None = None
    ) -> list[BusFactorTopic]: ...

    @abstractmethod
    def sync(self, session: Session, team_id: uuid.UUID | None = None) -> dict[str, Any]: ...


class MemoryGraph(KnowledgeGraph):
    """Derived on demand from SQL. Always current, no infrastructure."""

    provider = "memory"

    def overview(self, session, team_id=None):
        return build_graph(session, team_id)

    def neighborhood(self, session, node_id, team_id=None):
        nodes, edges = build_graph(session, team_id)
        keep_edges = [e for e in edges if node_id in (e.source, e.target)]
        keep_ids = {node_id} | {e.source for e in keep_edges} | {e.target for e in keep_edges}
        return [n for n in nodes if n.id in keep_ids], keep_edges

    def collaborators(self, session, person_id, team_id=None):
        nodes, edges = build_graph(session, team_id)
        people = {n.id: n for n in nodes if n.kind == "person"}
        me = _node_id("person", str(person_id))

        # Same overlap the COLLABORATES_WITH edges are built from, so the two
        # views of "who works with whom" cannot drift apart.
        topics, repos = _shared_signals(edges)

        results: list[Collaborator] = []
        for other_id, node in people.items():
            if other_id == me:
                continue
            shared_topics = topics[me] & topics[other_id]
            shared_repos = repos[me] & repos[other_id]
            if not shared_topics and not shared_repos:
                continue
            results.append(
                Collaborator(
                    person_id=other_id.removeprefix("person:"),
                    display_name=node.label,
                    email=str(node.meta.get("email", "")),
                    shared_topics=sorted(t.removeprefix("topic:") for t in shared_topics),
                    shared_repos=sorted(r.removeprefix("repo:") for r in shared_repos),
                    strength=affinity(len(shared_repos), len(shared_topics)),
                )
            )
        results.sort(key=lambda c: c.strength, reverse=True)
        return results

    def bus_factor(self, session, team_id=None):
        nodes, edges = build_graph(session, team_id)
        people = {n.id: n for n in nodes if n.kind == "person"}
        knowers: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in edges:
            if edge.kind == "KNOWS":
                knowers[edge.target].append(edge)

        at_risk: list[BusFactorTopic] = []
        for topic_id, topic_edges in knowers.items():
            if len(topic_edges) != 1:
                continue
            edge = topic_edges[0]
            person = people.get(edge.source)
            if person is None:
                continue
            at_risk.append(
                BusFactorTopic(
                    topic=topic_id.removeprefix("topic:"),
                    expert_id=edge.source.removeprefix("person:"),
                    expert_name=person.label,
                    score=edge.weight,
                    evidence_count=1,
                )
            )
        at_risk.sort(key=lambda t: t.score, reverse=True)
        return at_risk

    def sync(self, session, team_id=None):
        nodes, edges = build_graph(session, team_id)
        return {"provider": self.provider, "nodes": len(nodes), "edges": len(edges)}


class Neo4jGraph(KnowledgeGraph):  # pragma: no cover - needs a running server
    """Neo4j (Community Edition or Aura) holding a mirror of the SQL-derived
    graph, readable with Cypher from Neo4j Browser/Bloom too.

    Two transports, chosen by the URI scheme:
      bolt:// or neo4j+s://  -> the official driver over Bolt (port 7687)
      https://               -> Aura's Query API over 443, for networks that
                                block Bolt (corporate firewalls commonly do)
    All queries return plain maps (Cypher map projections), so both transports
    yield identical row dicts.
    """

    provider = "neo4j"

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        if not password:
            raise RuntimeError("GRAPH_PROVIDER=neo4j requires NEO4J_PASSWORD")
        self._database = database
        self._http_base: str | None = None
        self._auth = (user, password)
        self._driver = None
        if uri.startswith(("http://", "https://")):
            self._http_base = uri.rstrip("/")
        else:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise RuntimeError("GRAPH_PROVIDER=neo4j requires `pip install neo4j`") from exc
            self._driver = GraphDatabase.driver(uri, auth=self._auth)

    def _run(self, query: str, **params) -> list[dict[str, Any]]:
        if self._http_base:
            import httpx

            response = httpx.post(
                f"{self._http_base}/db/{self._database}/query/v2",
                auth=self._auth,
                json={"statement": query, "parameters": params},
                timeout=60.0,
            )
            response.raise_for_status()
            body = response.json()
            if body.get("errors"):
                raise RuntimeError(f"Neo4j query failed: {body['errors']}")
            data = body.get("data") or {}
            fields = data.get("fields") or []
            return [dict(zip(fields, row, strict=False)) for row in data.get("values") or []]
        with self._driver.session(database=self._database) as session:
            return [record.data() for record in session.run(query, **params)]

    def sync(self, session, team_id=None):
        nodes, edges = build_graph(session, team_id)
        # The mirror is disposable (SQL is the source of truth): rebuild it whole.
        self._run("MATCH (n:Hive) DETACH DELETE n")
        self._run(
            """
            UNWIND $nodes AS node
            CREATE (n:Hive {id: node.id, label: node.label, kind: node.kind})
            SET n += node.meta
            """,
            nodes=[{"id": n.id, "label": n.label, "kind": n.kind, "meta": n.meta} for n in nodes],
        )
        # The index is an optimisation, not a requirement (some hosts restrict DDL).
        with contextlib.suppress(Exception):
            self._run("CREATE INDEX hive_id IF NOT EXISTS FOR (n:Hive) ON (n.id)")
        self._run(
            """
            UNWIND $edges AS edge
            MATCH (a:Hive {id: edge.source}), (b:Hive {id: edge.target})
            CREATE (a)-[r:REL {kind: edge.kind, weight: edge.weight}]->(b)
            """,
            edges=[
                {"source": e.source, "target": e.target, "kind": e.kind, "weight": e.weight}
                for e in edges
            ],
        )
        return {"provider": self.provider, "nodes": len(nodes), "edges": len(edges)}

    @staticmethod
    def _to_node(data: dict[str, Any]) -> GraphNode:
        return GraphNode(
            id=data["id"],
            label=data.get("label", ""),
            kind=data.get("kind", ""),
            meta={k: v for k, v in data.items() if k not in ("id", "label", "kind")},
        )

    def _records_to_graph(self, records) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        for record in records:
            for key in ("a", "b"):
                node = self._to_node(record[key])
                nodes.setdefault(node.id, node)
            edges.append(
                GraphEdge(
                    source=record["a"]["id"],
                    target=record["b"]["id"],
                    kind=record["r"]["kind"],
                    weight=float(record["r"].get("weight") or 1.0),
                )
            )
        return list(nodes.values()), edges

    # Map projections (a{.*}) return plain dicts on both transports.
    def overview(self, session, team_id=None):
        return self._records_to_graph(
            self._run(
                """
                MATCH (a:Hive)-[r:REL]->(b:Hive)
                RETURN a{.*} AS a, {kind: r.kind, weight: r.weight} AS r, b{.*} AS b
                """
            )
        )

    def neighborhood(self, session, node_id, team_id=None):
        return self._records_to_graph(
            self._run(
                """
                MATCH (a:Hive)-[r:REL]->(b:Hive)
                WHERE a.id = $node_id OR b.id = $node_id
                RETURN a{.*} AS a, {kind: r.kind, weight: r.weight} AS r, b{.*} AS b
                """,
                node_id=node_id,
            )
        )

    def collaborators(self, session, person_id, team_id=None):
        records = self._run(
            """
            MATCH (me:Hive {id: $me})-[:REL]->(shared:Hive)<-[:REL]-(other:Hive)
            WHERE other.kind = 'person' AND shared.kind IN ['topic', 'repo']
            WITH other,
                 collect(DISTINCT CASE WHEN shared.kind = 'topic' THEN shared.label END) AS topics,
                 collect(DISTINCT CASE WHEN shared.kind = 'repo' THEN shared.label END) AS repos
            RETURN other{.*} AS other,
                   [t IN topics WHERE t IS NOT NULL] AS topics,
                   [r IN repos WHERE r IS NOT NULL] AS repos
            """,
            me=_node_id("person", str(person_id)),
        )
        results = [
            Collaborator(
                person_id=record["other"]["id"].removeprefix("person:"),
                display_name=record["other"].get("label", ""),
                email=str(record["other"].get("email", "")),
                shared_topics=sorted(record["topics"]),
                shared_repos=sorted(record["repos"]),
                strength=affinity(len(record["repos"]), len(record["topics"])),
            )
            for record in records
        ]
        results.sort(key=lambda c: c.strength, reverse=True)
        return results

    def bus_factor(self, session, team_id=None):
        records = self._run(
            """
            MATCH (p:Hive {kind: 'person'})-[r:REL {kind: 'KNOWS'}]->(t:Hive {kind: 'topic'})
            WITH t, collect({person: p{.*}, weight: r.weight}) AS knowers
            WHERE size(knowers) = 1
            RETURN t.label AS topic, knowers[0].person AS person, knowers[0].weight AS weight
            ORDER BY weight DESC
            """
        )
        return [
            BusFactorTopic(
                topic=record["topic"],
                expert_id=record["person"]["id"].removeprefix("person:"),
                expert_name=record["person"].get("label", ""),
                score=float(record["weight"] or 0.0),
                evidence_count=1,
            )
            for record in records
        ]


class FallbackGraph(KnowledgeGraph):
    """Neo4j with the SQL-derived graph behind it.

    The Neo4j mirror is disposable (SQL is the source of truth), so an unreachable
    server -- a paused or deleted Aura instance, a firewall, DNS -- must not take
    the graph pages down. The first failure switches this process to MemoryGraph
    for good, so each request does not pay a connection timeout again.
    """

    def __init__(self, primary: KnowledgeGraph) -> None:
        self._primary: KnowledgeGraph | None = primary
        self._memory = MemoryGraph()

    @property
    def provider(self) -> str:  # type: ignore[override]
        return (self._primary or self._memory).provider

    def _call(self, method: str, *args, **kwargs):
        if self._primary is not None:
            try:
                return getattr(self._primary, method)(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - any transport failure degrades
                logger.warning("Neo4j unavailable (%s); using the in-memory graph", exc)
                self._primary = None
        return getattr(self._memory, method)(*args, **kwargs)

    def overview(self, session, team_id=None):
        return self._call("overview", session, team_id)

    def neighborhood(self, session, node_id, team_id=None):
        return self._call("neighborhood", session, node_id, team_id)

    def collaborators(self, session, person_id, team_id=None):
        return self._call("collaborators", session, person_id, team_id)

    def bus_factor(self, session, team_id=None):
        return self._call("bus_factor", session, team_id)

    def sync(self, session, team_id=None):
        return self._call("sync", session, team_id)


@lru_cache
def get_graph() -> KnowledgeGraph:
    settings = get_settings()
    if settings.graph_provider == "neo4j":
        try:
            neo4j = Neo4jGraph(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password or "",
                database=settings.neo4j_database,
            )
        except Exception as exc:  # noqa: BLE001 - missing driver or password
            logger.warning("Neo4j not configured (%s); using the in-memory graph", exc)
            return MemoryGraph()
        return FallbackGraph(neo4j)
    return MemoryGraph()
