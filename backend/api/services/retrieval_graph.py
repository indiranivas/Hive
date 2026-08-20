"""Graded retrieval as a LangGraph state machine.

    retrieve -> grade -> sufficient ---------------> done
                      -> weak -> rewrite -> retrieve  (up to RETRIEVAL_MAX_REWRITES)
                      -> weak & exhausted ----------> done (caller reports the gap)

LangGraph is used as the control-flow runtime *only*. Every node calls Hive's own
retrieval and LLM providers, so the offline stub behaves identically to Azure
OpenAI inside the graph and the tests stay deterministic. No LangChain model
abstraction is introduced.

If langgraph is not installed the same steps run through a plain loop, so a
minimal install keeps working -- the graph is the orchestration, not the logic.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, TypedDict

from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.core.embeddings import words
from api.core.llm import get_llm
from api.core.prompts import GRADE_SYSTEM_PROMPT, REWRITE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# A retrieval is "sufficient" when its best hit clears the relevance floor by
# this multiple. Just above the floor means "technically matched, probably noise".
SUFFICIENT_SCORE_MULTIPLE = 2.0
FILLER = words(
    "what which who whom whose when where why how",
    "is are was were do does did can could should would will",
    "our your their the a an of for on in to from about with",
    "please tell me us know anything something explain",
    "you we they them it this that these those there here",
)


class GraphState(TypedDict, total=False):
    question: str
    original: str
    attempts: int
    rewrites: list[str]
    candidates: list[Any]
    knowledge: list[dict]
    verdict: str


@dataclass(slots=True)
class GradedRetrieval:
    """What the graph settled on, plus how it got there."""

    candidates: list[Any] = field(default_factory=list)
    knowledge: list[dict] = field(default_factory=list)
    attempts: int = 1
    rewrites: list[str] = field(default_factory=list)
    verdict: str = "sufficient"


def _best_score(state: GraphState) -> float:
    candidate_best = max((item.score for item in state.get("candidates") or []), default=0.0)
    knowledge_best = max(
        (float(item.get("score") or 0.0) for item in state.get("knowledge") or []), default=0.0
    )
    return max(candidate_best, knowledge_best)


def grade_heuristically(state: GraphState) -> str:
    """Deterministic grade used with the stub LLM (and as the fallback).

    Purely score-based, so it never depends on a model being configured.
    """
    settings = get_settings()
    if not state.get("candidates") and not state.get("knowledge"):
        return "weak"
    if _best_score(state) >= settings.retrieval_min_score * SUFFICIENT_SCORE_MULTIPLE:
        return "sufficient"
    return "weak"


def grade_with_llm(state: GraphState) -> str:
    """Ask the model whether the retrieved evidence can answer the question."""
    candidates = state.get("candidates") or []
    knowledge = state.get("knowledge") or []
    if not candidates and not knowledge:
        return "weak"

    summary = "\n".join(
        f"- [{item.artifact.artifact_type}] {item.artifact.title}: {item.excerpt[:200]}"
        for item in candidates[:8]
    )
    summary += "\n".join(
        f"- [answered question] {item['question']}: {item['answer'][:200]}"
        for item in knowledge[:3]
    )
    try:
        response = get_llm().chat(
            system=GRADE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Question: {state['original']}\n\nRetrieved evidence:\n{summary}",
                }
            ],
        )
    except Exception:  # noqa: BLE001 - grading must never break a query
        logger.warning("grading call failed; falling back to score heuristic", exc_info=True)
        return grade_heuristically(state)

    verdict = response.text.strip().lower()
    if verdict.startswith("sufficient") or verdict.startswith("yes"):
        return "sufficient"
    if verdict.startswith("weak") or verdict.startswith("no"):
        return "weak"
    logger.debug("unparseable grade %r; using score heuristic", verdict[:60])
    return grade_heuristically(state)


def rewrite_heuristically(question: str) -> str:
    """Strip interrogative filler down to the salient terms.

    "who fixed the billing auth bug?" -> "fixed billing auth bug". Deterministic,
    so the offline path is reproducible in tests.
    """
    tokens = re.findall(r"[\w@#./-]+", question.lower())
    kept = [token for token in tokens if token not in FILLER and len(token) > 2]
    return " ".join(dict.fromkeys(kept)) or question


def rewrite_with_llm(question: str) -> str:
    try:
        response = get_llm().chat(
            system=REWRITE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": question}],
        )
    except Exception:  # noqa: BLE001
        logger.warning("rewrite call failed; using heuristic", exc_info=True)
        return rewrite_heuristically(question)
    rewritten = response.text.strip().strip('"').splitlines()[0]
    return rewritten or rewrite_heuristically(question)


def _using_real_llm() -> bool:
    return get_settings().llm_provider != "stub"


def _build_nodes(session: Session, team_id: uuid.UUID | None, scope: str):
    """Node closures over the request context. Imported lazily to avoid a cycle:
    query_engine imports this module."""
    from api.services.query_engine import retrieve, retrieve_knowledge_repo

    def node_retrieve(state: GraphState) -> GraphState:
        question = state["question"]
        return {
            "candidates": retrieve(session, question, team_id=team_id, scope=scope),
            "knowledge": retrieve_knowledge_repo(session, question),
        }

    def node_grade(state: GraphState) -> GraphState:
        verdict = grade_with_llm(state) if _using_real_llm() else grade_heuristically(state)
        return {"verdict": verdict}

    def node_rewrite(state: GraphState) -> GraphState:
        previous = state["question"]
        rewritten = (
            rewrite_with_llm(state["original"])
            if _using_real_llm()
            else rewrite_heuristically(previous)
        )
        if rewritten.strip().lower() == previous.strip().lower():
            # No new query to try: stop rather than burn another identical pass.
            return {"attempts": state.get("attempts", 1) + 99}
        return {
            "question": rewritten,
            "attempts": state.get("attempts", 1) + 1,
            "rewrites": [*(state.get("rewrites") or []), rewritten],
        }

    return node_retrieve, node_grade, node_rewrite


def _decide(state: GraphState) -> str:
    if state.get("verdict") == "sufficient":
        return "done"
    if state.get("attempts", 1) > get_settings().retrieval_max_rewrites:
        return "done"
    return "rewrite"


@lru_cache
def _langgraph_available() -> bool:
    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        logger.info("langgraph not installed; graded retrieval runs as a plain loop")
        return False
    return True


def graded_retrieve(session: Session, query: str, team_id: uuid.UUID | None = None,
                    scope: str = "team") -> GradedRetrieval:
    node_retrieve, node_grade, node_rewrite = _build_nodes(session, team_id, scope)
    initial: GraphState = {
        "question": query,
        "original": query,
        "attempts": 1,
        "rewrites": [],
        "candidates": [],
        "knowledge": [],
    }

    if _langgraph_available():
        final = _compiled_graph(node_retrieve, node_grade, node_rewrite).invoke(initial)
    else:
        final = _plain_loop(initial, node_retrieve, node_grade, node_rewrite)

    return GradedRetrieval(
        candidates=list(final.get("candidates") or []),
        knowledge=list(final.get("knowledge") or []),
        attempts=min(final.get("attempts", 1), get_settings().retrieval_max_rewrites + 1),
        rewrites=list(final.get("rewrites") or []),
        verdict=final.get("verdict", "sufficient"),
    )


def _compiled_graph(node_retrieve, node_grade, node_rewrite):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(GraphState)
    builder.add_node("retrieve", node_retrieve)
    builder.add_node("grade", node_grade)
    builder.add_node("rewrite", node_rewrite)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges("grade", _decide, {"done": END, "rewrite": "rewrite"})
    builder.add_edge("rewrite", "retrieve")
    return builder.compile()


def _plain_loop(state: GraphState, node_retrieve, node_grade, node_rewrite) -> GraphState:
    """Same state machine without the runtime, for minimal installs."""
    while True:
        state = {**state, **node_retrieve(state)}
        state = {**state, **node_grade(state)}
        if _decide(state) == "done":
            return state
        state = {**state, **node_rewrite(state)}
