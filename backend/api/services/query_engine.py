"""Q&A pipeline (blueprint section 7.1): embed -> retrieve -> scope -> LLM -> cite.

Retrieval is hybrid. Vector search alone misses exact identifiers (a commit SHA,
`PR #312`, a service name) especially under lexical embeddings, so a keyword pass
over titles and content runs alongside it and the two are score-merged.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.core.embeddings import get_embedder, tokenize
from api.core.llm import get_llm
from api.core.prompts import QUERY_SYSTEM_PROMPT
from api.core.vectorstore import (
    ARTIFACT_COLLECTION,
    KNOWLEDGE_COLLECTION,
    get_vector_store,
)
from api.models.orm import KnowledgeRequest, Person, QueryLog, WorkArtifact

VECTOR_WEIGHT = 0.75
KEYWORD_WEIGHT = 0.25
GAP_MARKERS = ("knowledge request", "could not find", "don't have", "do not have", "no evidence")


@dataclass(slots=True)
class Source:
    artifact_id: str
    type: str
    title: str
    author: str | None
    date: str | None
    relevance: float
    excerpt: str
    reference: str | None = None


@dataclass(slots=True)
class QueryResponse:
    answer: str
    sources: list[Source] = field(default_factory=list)
    has_gap: bool = False
    latency_ms: int = 0
    model: str = ""
    # How the graded-retrieval graph got here: how many passes, and what it tried.
    attempts: int = 1
    rewrites: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "sources": [asdict(source) for source in self.sources],
            "has_gap": self.has_gap,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "attempts": self.attempts,
            "rewrites": list(self.rewrites),
        }


@dataclass(slots=True)
class Candidate:
    artifact: WorkArtifact
    score: float
    excerpt: str


def _reference(artifact: WorkArtifact) -> str | None:
    meta = artifact.meta or {}
    if artifact.artifact_type == "commit" and meta.get("sha"):
        return f"{meta.get('repo', 'repo')}@{str(meta['sha'])[:8]}"
    if artifact.artifact_type == "pull_request" and meta.get("pr_id"):
        return f"{meta.get('repo', 'repo')} PR #{meta['pr_id']}"
    if artifact.artifact_type == "work_item" and meta.get("work_item_id"):
        return f"work item #{meta['work_item_id']}"
    if artifact.artifact_type == "email_thread":
        return f"email: {artifact.title}" if artifact.title else "email"
    if artifact.artifact_type == "meeting_transcript" and artifact.occurred_at:
        return f"meeting {artifact.occurred_at.date().isoformat()}"
    return meta.get("repo")


def _keyword_candidates(session: Session, query: str, team_id: uuid.UUID | None,
                        limit: int) -> dict[uuid.UUID, float]:
    terms = [term for term in tokenize(query) if len(term) > 2][:8]
    if not terms:
        return {}
    stmt = select(WorkArtifact).where(
        or_(*[WorkArtifact.content.ilike(f"%{term}%") for term in terms],
            *[WorkArtifact.title.ilike(f"%{term}%") for term in terms])
    )
    if team_id:
        stmt = stmt.where(WorkArtifact.team_id == team_id)
    stmt = stmt.order_by(WorkArtifact.occurred_at.desc()).limit(limit * 4)

    scores: dict[uuid.UUID, float] = {}
    for artifact in session.execute(stmt).scalars():
        haystack = f"{artifact.title or ''}\n{artifact.content}".lower()
        hits = sum(1 for term in terms if term in haystack)
        if hits:
            scores[artifact.id] = hits / len(terms)
    return scores


def _without_title(excerpt: str, title: str | None) -> str:
    """Drop a leading repeat of the title.

    Commit bodies conventionally open with the subject line, so an excerpt shown
    directly beneath the title would otherwise say the same thing twice.
    """
    title = (title or "").strip()
    if not title:
        return excerpt
    stripped = excerpt.lstrip(". ")
    if stripped.lower().startswith(title.lower()):
        remainder = stripped[len(title) :].lstrip(" .:-\n")
        return remainder or excerpt
    return excerpt


def _excerpt(text: str, query: str, width: int = 280) -> str:
    terms = [term for term in tokenize(query) if len(term) > 2]
    lowered = text.lower()
    position = next((lowered.find(term) for term in terms if lowered.find(term) != -1), -1)
    if position == -1:
        return text[:width].strip()
    start = max(0, position - width // 3)
    snippet = text[start : start + width].strip()
    return f"...{snippet}" if start else snippet


def retrieve(session: Session, query: str, team_id: uuid.UUID | None = None,
             scope: str = "team", top_k: int | None = None) -> list[Candidate]:
    settings = get_settings()
    limit = top_k or settings.retrieval_top_k
    embedding = get_embedder().encode_one(query)

    where = {"team_id": str(team_id)} if (scope == "team" and team_id) else None
    hits = get_vector_store().query(
        session, ARTIFACT_COLLECTION, embedding, n_results=limit * 2, where=where
    )

    scored: dict[uuid.UUID, tuple[float, str]] = {}
    for hit in hits:
        if hit.score < settings.retrieval_min_score:
            continue
        try:
            artifact_id = uuid.UUID(hit.ref_id)
        except ValueError:
            continue
        weighted = hit.score * VECTOR_WEIGHT
        current = scored.get(artifact_id)
        if current is None or weighted > current[0]:
            scored[artifact_id] = (weighted, hit.document)

    for artifact_id, keyword_score in _keyword_candidates(session, query, team_id, limit).items():
        boost = keyword_score * KEYWORD_WEIGHT
        current = scored.get(artifact_id)
        scored[artifact_id] = (
            (current[0] + boost, current[1]) if current else (boost, "")
        )

    if not scored:
        return []

    artifacts = {
        artifact.id: artifact
        for artifact in session.execute(
            select(WorkArtifact).where(WorkArtifact.id.in_(list(scored)))
        ).scalars()
    }

    # Apply the floor to the merged score too: the keyword pass adds candidates
    # that never went through the vector threshold, and near-noise matches are
    # worse than an honest "no evidence" -- that answer offers a Knowledge Request.
    candidates = [
        Candidate(
            artifact=artifacts[artifact_id],
            score=round(score, 4),
            excerpt=_excerpt(document or artifacts[artifact_id].content, query),
        )
        for artifact_id, (score, document) in scored.items()
        if artifact_id in artifacts and score >= settings.retrieval_min_score
    ]
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[:limit]


def retrieve_knowledge_repo(session: Session, query: str, limit: int | None = None) -> list[dict]:
    settings = get_settings()
    embedding = get_embedder().encode_one(query)
    hits = get_vector_store().query(
        session, KNOWLEDGE_COLLECTION, embedding, n_results=limit or settings.retrieval_kr_top_k
    )
    answers: list[dict] = []
    for hit in hits:
        if hit.score < settings.retrieval_min_score:
            continue
        answers.append(
            {
                "question": hit.metadata.get("question", ""),
                "answer": hit.metadata.get("answer", ""),
                "answered_by": hit.metadata.get("answered_by_name")
                or hit.metadata.get("answered_by", ""),
                "score": round(hit.score, 4),
                "kr_id": hit.ref_id,
            }
        )
    return answers


def _format_date(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


def build_context(candidates: list[Candidate], knowledge: list[dict],
                 budget: int | None = None) -> str:
    settings = get_settings()
    remaining = budget or settings.retrieval_context_char_budget
    blocks: list[str] = []

    for index, candidate in enumerate(candidates, start=1):
        artifact = candidate.artifact
        author = artifact.author.display_name if artifact.author else "unknown author"
        header = " | ".join(
            part
            for part in (
                artifact.artifact_type,
                author,
                _format_date(artifact.occurred_at),
                _reference(artifact),
            )
            if part
        )
        block = (
            f"[{index}] {header}\n"
            f"Title: {artifact.title or '(no title)'}\n"
            f"Excerpt: {candidate.excerpt}"
        )
        if len(block) > remaining:
            break
        blocks.append(block)
        remaining -= len(block)

    for index, entry in enumerate(knowledge, start=len(blocks) + 1):
        block = (
            f"[{index}] knowledge_repo | answered by {entry['answered_by'] or 'unknown'}\n"
            f"Title: {entry['question']}\n"
            f"Excerpt: {entry['answer'][:600]}"
        )
        if len(block) > remaining:
            break
        blocks.append(block)
        remaining -= len(block)

    return "\n\n".join(blocks)


def answer_query(session: Session, query: str, user_id: uuid.UUID | None = None,
                 team_id: uuid.UUID | None = None, scope: str = "team",
                 surface: str = "teams") -> QueryResponse:
    started = time.perf_counter()
    query = (query or "").strip()
    if not query:
        return QueryResponse(answer="Ask me a question about your team's work.", latency_ms=0)

    if get_settings().retrieval_mode == "graded":
        from api.services.retrieval_graph import graded_retrieve

        graded = graded_retrieve(session, query, team_id=team_id, scope=scope)
        candidates, knowledge = graded.candidates, graded.knowledge
        attempts, rewrites = graded.attempts, graded.rewrites
    else:
        candidates = retrieve(session, query, team_id=team_id, scope=scope)
        knowledge = retrieve_knowledge_repo(session, query)
        attempts, rewrites = 1, []
    context = build_context(candidates, knowledge)

    llm = get_llm()
    if context:
        response = llm.chat(
            system=QUERY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Question: {query}\n\nContext:\n{context}"}],
        )
        answer = response.text.strip()
        model = response.model
    else:
        answer = (
            "I could not find anything in the team's work trail that answers this. "
            "I can raise a Knowledge Request and route it to the most likely expert."
        )
        model = "none"

    sources = [
        Source(
            artifact_id=str(candidate.artifact.id),
            type=candidate.artifact.artifact_type,
            title=candidate.artifact.title or "(no title)",
            author=candidate.artifact.author.display_name if candidate.artifact.author else None,
            date=_format_date(candidate.artifact.occurred_at),
            relevance=candidate.score,
            excerpt=_without_title(candidate.excerpt, candidate.artifact.title),
            reference=_reference(candidate.artifact),
        )
        for candidate in candidates
    ]

    sources.extend(
        Source(
            artifact_id=entry["kr_id"],
            type="knowledge_repo",
            title=entry["question"],
            author=entry["answered_by"] or None,
            date=None,
            relevance=entry["score"],
            excerpt=entry["answer"][:280],
            reference="knowledge repo",
        )
        for entry in knowledge
    )
    sources.sort(key=lambda item: item.relevance, reverse=True)

    lowered = answer.lower()
    result = QueryResponse(
        answer=answer,
        sources=sources,
        has_gap=not sources or any(marker in lowered for marker in GAP_MARKERS),
        latency_ms=int((time.perf_counter() - started) * 1000),
        model=model,
        attempts=attempts,
        rewrites=rewrites,
    )

    session.add(
        QueryLog(
            user_id=user_id,
            query_text=query,
            response_text=result.answer,
            sources_used={"sources": [asdict(source) for source in sources[:10]]},
            surface=surface,
            latency_ms=result.latency_ms,
        )
    )
    session.flush()
    return result


def team_of(session: Session, user_id: uuid.UUID | None) -> uuid.UUID | None:
    if not user_id:
        return None
    person = session.get(Person, user_id)
    return person.team_id if person else None


def open_gap_count(session: Session) -> int:
    return len(
        session.execute(
            select(KnowledgeRequest.id).where(KnowledgeRequest.status.in_(["open", "routed"]))
        ).all()
    )
