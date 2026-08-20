from __future__ import annotations

import math

from api.core.embeddings import HashingEmbedder, cosine, tokenize
from api.core.vectorstore import ARTIFACT_COLLECTION, SqlVectorStore, VectorRecord


def test_hashing_embedder_is_deterministic_and_normalized():
    embedder = HashingEmbedder(dim=64)
    first = embedder.encode_one("billing service jwt refresh")
    second = embedder.encode_one("billing service jwt refresh")
    assert first == second
    assert len(first) == 64
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0, rel_tol=1e-9)


def test_hashing_embedder_ranks_related_text_higher():
    embedder = HashingEmbedder(dim=512)
    query = embedder.encode_one("jwt refresh token in billing auth")
    related = embedder.encode_one("Fix JWT refresh loop in billing auth middleware")
    unrelated = embedder.encode_one("Add force graph layout to the expertise map")
    assert cosine(query, related) > cosine(query, unrelated)


def test_hashing_embedder_handles_empty_text():
    embedder = HashingEmbedder(dim=32)
    assert embedder.encode_one("") == [0.0] * 32


def test_tokenize_drops_stopwords_and_single_chars():
    assert tokenize("The billing API is a service") == ["billing", "api", "service"]


def test_cosine_guards_mismatched_and_empty_vectors():
    assert cosine([], [1.0]) == 0.0
    assert cosine([1.0, 0.0], [1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert math.isclose(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)


def test_sql_vector_store_roundtrip_and_filtering(db_session):
    store = SqlVectorStore()
    store.upsert(
        db_session,
        ARTIFACT_COLLECTION,
        [
            VectorRecord("a_0", "a", "billing auth", [1.0, 0.0], {"team_id": "t1"}),
            VectorRecord("b_0", "b", "dashboard chart", [0.0, 1.0], {"team_id": "t2"}),
        ],
    )
    assert store.count(db_session, ARTIFACT_COLLECTION) == 2

    hits = store.query(db_session, ARTIFACT_COLLECTION, [1.0, 0.0], n_results=2)
    assert hits[0].ref_id == "a"
    assert hits[0].score > hits[1].score

    scoped = store.query(
        db_session, ARTIFACT_COLLECTION, [1.0, 0.0], n_results=5, where={"team_id": "t2"}
    )
    assert [hit.ref_id for hit in scoped] == ["b"]


def test_sql_vector_store_upsert_replaces_same_id(db_session):
    store = SqlVectorStore()
    store.upsert(
        db_session, ARTIFACT_COLLECTION, [VectorRecord("a_0", "a", "first", [1.0, 0.0], {})]
    )
    store.upsert(
        db_session, ARTIFACT_COLLECTION, [VectorRecord("a_0", "a", "second", [1.0, 0.0], {})]
    )
    assert store.count(db_session, ARTIFACT_COLLECTION) == 1
    assert store.query(db_session, ARTIFACT_COLLECTION, [1.0, 0.0])[0].document == "second"


def test_sql_vector_store_delete_by_ref(db_session):
    store = SqlVectorStore()
    store.upsert(
        db_session,
        ARTIFACT_COLLECTION,
        [
            VectorRecord("a_0", "a", "chunk one", [1.0, 0.0], {}),
            VectorRecord("a_1", "a", "chunk two", [0.9, 0.1], {}),
            VectorRecord("b_0", "b", "other", [0.0, 1.0], {}),
        ],
    )
    store.delete_by_ref(db_session, ARTIFACT_COLLECTION, "a")
    assert store.count(db_session, ARTIFACT_COLLECTION) == 1
