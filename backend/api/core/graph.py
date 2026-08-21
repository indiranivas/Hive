"""Knowledge graph abstraction -- swap providers via GRAPH_PROVIDER.

`memory` (the default) derives the graph from the relational tables on every
call: no extra service, never stale, and right-sized for a single team's data.
`neo4j` mirrors the same graph into Neo4j Community Edition (open source) over
Bolt, where it can be queried with Cypher and shared by other tools; refresh it
with sync() (POST /api/graph/sync) after ingestion.

The graph model, derived entirely from existing tables:

    (Person)-[:KNOWS {weight=score}]->(Topic)      expertise_scores
    (Person)-[:WORKED_IN {weight=count}]->(Repo)   work_artifacts metadata
    (Person)-[:ASKED]->(KR)                        knowledge_requests
    (Person)-[:ANSWERED]->(KR)                     knowledge_requests
    (KR)-[:TAGGED]->(Topic)                        knowledge_requests.tags
"""

from __future__ import annotations

import contextlib
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.models.orm import ExpertiseScore, KnowledgeRequest, Person, WorkArtifact


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


def build_graph(
    session: Session, team_id: uuid.UUID | None = None
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Derive the whole team graph from the relational tables.

    Shared by both providers: `memory` serves queries straight off it and
    `neo4j` mirrors it into the database on sync().
    """
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    people_query = select(Person)
    if team_id:
        people_query = people_query.where(Person.team_id == team_id)
    people = {person.id: person for person in session.execute(people_query).scalars()}
    for person in people.values():
        nodes[_node_id("person", str(person.id))] = GraphNode(
            id=_node_id("person", str(person.id)),
            label=person.display_name,
            kind="person",
            meta={"email": person.email, "role": person.role},
        )

    scores = session.execute(
        select(ExpertiseScore).where(ExpertiseScore.person_id.in_(people.keys()))
    ).scalars()
    for score in scores:
        topic_id = _node_id("topic", score.topic)
        nodes.setdefault(topic_id, GraphNode(id=topic_id, label=score.topic, kind="topic"))
        edges.append(
            GraphEdge(
                source=_node_id("person", str(score.person_id)),
                target=topic_id,
                kind="KNOWS",
                weight=round(score.score, 4),
            )
        )

    artifacts = session.execute(
        select(WorkArtifact).where(WorkArtifact.author_id.in_(people.keys()))
    ).scalars()
    repo_counts: dict[tuple[str, str], int] = defaultdict(int)
    for artifact in artifacts:
        repo = (artifact.meta or {}).get("repo")
        if repo and artifact.author_id:
            repo_counts[(str(artifact.author_id), str(repo))] += 1
    for (person_id, repo), count in repo_counts.items():
        repo_id = _node_id("repo", repo)
        nodes.setdefault(repo_id, GraphNode(id=repo_id, label=repo, kind="repo"))
        edges.append(
            GraphEdge(
                source=_node_id("person", person_id),
                target=repo_id,
                kind="WORKED_IN",
                weight=float(count),
            )
        )

    krs = session.execute(
        select(KnowledgeRequest).where(KnowledgeRequest.requester_id.in_(people.keys()))
    ).scalars()
    for kr in krs:
        kr_id = _node_id("kr", str(kr.id))
        nodes[kr_id] = GraphNode(
            id=kr_id,
            label=(kr.question[:80] + "…") if len(kr.question) > 80 else kr.question,
            kind="kr",
            meta={"status": kr.status},
        )
        edges.append(
            GraphEdge(source=_node_id("person", str(kr.requester_id)), target=kr_id, kind="ASKED")
        )
        if kr.answered_by_id and kr.answered_by_id in people:
            edges.append(
                GraphEdge(
                    source=_node_id("person", str(kr.answered_by_id)),
                    target=kr_id,
                    kind="ANSWERED",
                )
            )
        for tag in kr.tags or []:
            topic_id = _node_id("topic", tag)
            nodes.setdefault(topic_id, GraphNode(id=topic_id, label=tag, kind="topic"))
            edges.append(GraphEdge(source=kr_id, target=topic_id, kind="TAGGED"))

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

        topics: dict[str, set[str]] = defaultdict(set)  # person node -> topics
        repos: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            if edge.kind == "KNOWS":
                topics[edge.source].add(edge.target)
            elif edge.kind == "WORKED_IN":
                repos[edge.source].add(edge.target)

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
                    # Repos indicate direct collaboration; topics shared knowledge.
                    strength=len(shared_repos) * 2.0 + len(shared_topics),
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
                strength=len(record["repos"]) * 2.0 + len(record["topics"]),
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


@lru_cache
def get_graph() -> KnowledgeGraph:
    settings = get_settings()
    if settings.graph_provider == "neo4j":
        return Neo4jGraph(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password or "",
            database=settings.neo4j_database,
        )
    return MemoryGraph()
