"""ChromaVectorStore integration tests.

Run only when chromadb is installed (`pip install -r requirements-ml.txt`);
skipped otherwise so the core suite stays dependency-free. They exercise the
two Chroma-specific hazards: the distance space (must be cosine so scores stay
comparable with the SQL store and RETRIEVAL_MIN_SCORE) and metadata values
Chroma rejects (None).
"""

from __future__ import annotations

import pytest

pytest.importorskip("chromadb")

from api.core import config  # noqa: E402
from api.core.vectorstore import (  # noqa: E402
    ARTIFACT_COLLECTION,
    ChromaVectorStore,
    VectorRecord,
    get_vector_store,
)


@pytest.fixture
def chroma_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    config.get_settings.cache_clear()
    get_vector_store.cache_clear()
    try:
        yield ChromaVectorStore()
    finally:
        config.get_settings.cache_clear()
        get_vector_store.cache_clear()


def test_scores_are_cosine_not_l2(chroma_store):
    """With the default L2 space an orthogonal hit scores -1; cosine gives 0."""
    chroma_store.upsert(
        None,
        ARTIFACT_COLLECTION,
        [
            VectorRecord("a_0", "a", "billing auth", [1.0, 0.0], {"team_id": "t1"}),
            VectorRecord("b_0", "b", "dashboard chart", [0.0, 1.0], {"team_id": "t2"}),
        ],
    )
    hits = chroma_store.query(None, ARTIFACT_COLLECTION, [1.0, 0.0], n_results=2)
    assert [hit.ref_id for hit in hits] == ["a", "b"]
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)
    assert hits[1].score == pytest.approx(0.0, abs=1e-5)


def test_where_filter_scopes_results(chroma_store):
    chroma_store.upsert(
        None,
        ARTIFACT_COLLECTION,
        [
            VectorRecord("a_0", "a", "one", [1.0, 0.0], {"team_id": "t1"}),
            VectorRecord("b_0", "b", "two", [0.9, 0.1], {"team_id": "t2"}),
        ],
    )
    hits = chroma_store.query(
        None, ARTIFACT_COLLECTION, [1.0, 0.0], n_results=5, where={"team_id": "t2"}
    )
    assert [hit.ref_id for hit in hits] == ["b"]


def test_none_metadata_is_dropped_not_fatal(chroma_store):
    """Ingestion passes None for unknown author/team; Chroma must not choke."""
    chroma_store.upsert(
        None,
        ARTIFACT_COLLECTION,
        [
            VectorRecord(
                "a_0", "a", "orphan commit", [1.0, 0.0],
                {"team_id": None, "author_name": None, "title": "kept"},
            ),
        ],
    )
    hits = chroma_store.query(None, ARTIFACT_COLLECTION, [1.0, 0.0], n_results=1)
    assert hits[0].metadata.get("title") == "kept"
    assert "team_id" not in hits[0].metadata


def test_upsert_replaces_and_delete_by_ref(chroma_store):
    chroma_store.upsert(
        None, ARTIFACT_COLLECTION,
        [VectorRecord("a_0", "a", "first", [1.0, 0.0], {})],
    )
    chroma_store.upsert(
        None, ARTIFACT_COLLECTION,
        [VectorRecord("a_0", "a", "second", [1.0, 0.0], {})],
    )
    assert chroma_store.count(None, ARTIFACT_COLLECTION) == 1
    assert chroma_store.query(None, ARTIFACT_COLLECTION, [1.0, 0.0])[0].document == "second"

    chroma_store.delete_by_ref(None, ARTIFACT_COLLECTION, "a")
    assert chroma_store.count(None, ARTIFACT_COLLECTION) == 0
