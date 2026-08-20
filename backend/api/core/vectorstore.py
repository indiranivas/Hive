"""Vector store abstraction: collections `hive_artifacts` and `hive_knowledge_repo`.

`sql` provider keeps embeddings in the relational DB and scans them in Python --
fine for a single team's artifact volume and it means zero extra services in
dev. `chroma` is the drop-in for real deployments (Qdrant lands in phase 7).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.core.embeddings import cosine
from api.models.orm import VectorChunk

ARTIFACT_COLLECTION = "hive_artifacts"
KNOWLEDGE_COLLECTION = "hive_knowledge_repo"


@dataclass(slots=True)
class VectorRecord:
    id: str
    ref_id: str
    document: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VectorHit:
    id: str
    ref_id: str
    document: str
    metadata: dict[str, Any]
    score: float


def _matches(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    return all(str(metadata.get(key)) == str(value) for key, value in where.items())


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, session: Session, collection: str, records: list[VectorRecord]) -> None: ...

    @abstractmethod
    def query(
        self,
        session: Session,
        collection: str,
        embedding: list[float],
        n_results: int = 15,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]: ...

    @abstractmethod
    def delete_by_ref(self, session: Session, collection: str, ref_id: str) -> None: ...

    @abstractmethod
    def count(self, session: Session, collection: str) -> int: ...


class SqlVectorStore(VectorStore):
    def upsert(self, session: Session, collection: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        session.execute(
            delete(VectorChunk).where(
                VectorChunk.collection == collection,
                VectorChunk.id.in_([record.id for record in records]),
            )
        )
        session.add_all(
            VectorChunk(
                id=record.id,
                collection=collection,
                ref_id=record.ref_id,
                document=record.document,
                embedding=record.embedding,
                meta=record.metadata,
            )
            for record in records
        )
        session.flush()

    def query(
        self,
        session: Session,
        collection: str,
        embedding: list[float],
        n_results: int = 15,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        rows = session.execute(
            select(VectorChunk).where(VectorChunk.collection == collection)
        ).scalars()
        hits = [
            VectorHit(
                id=row.id,
                ref_id=row.ref_id,
                document=row.document,
                metadata=row.meta or {},
                score=cosine(embedding, row.embedding),
            )
            for row in rows
            if _matches(row.meta or {}, where)
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:n_results]

    def delete_by_ref(self, session: Session, collection: str, ref_id: str) -> None:
        session.execute(
            delete(VectorChunk).where(
                VectorChunk.collection == collection, VectorChunk.ref_id == ref_id
            )
        )

    def count(self, session: Session, collection: str) -> int:
        return len(
            session.execute(
                select(VectorChunk.id).where(VectorChunk.collection == collection)
            ).all()
        )


class ChromaVectorStore(VectorStore):  # pragma: no cover - optional dependency
    def __init__(self) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "VECTOR_PROVIDER=chroma requires `pip install -r requirements-ml.txt`"
            ) from exc
        settings = get_settings()
        if settings.chroma_url:
            host, _, port = settings.chroma_url.removeprefix("http://").removeprefix(
                "https://"
            ).partition(":")
            self._client = chromadb.HttpClient(host=host, port=int(port or 8000))
        else:
            self._client = chromadb.PersistentClient(path=settings.chroma_path)

    def _collection(self, collection: str):
        return self._client.get_or_create_collection(collection)

    def upsert(self, session: Session, collection: str, records: list[VectorRecord]) -> None:
        if not records:
            return
        self._collection(collection).upsert(
            ids=[record.id for record in records],
            embeddings=[record.embedding for record in records],
            documents=[record.document for record in records],
            metadatas=[{**record.metadata, "ref_id": record.ref_id} for record in records],
        )

    def query(
        self,
        session: Session,
        collection: str,
        embedding: list[float],
        n_results: int = 15,
        where: dict[str, Any] | None = None,
    ) -> list[VectorHit]:
        result = self._collection(collection).query(
            query_embeddings=[embedding], n_results=n_results, where=where or None
        )
        hits: list[VectorHit] = []
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] or {}
            hits.append(
                VectorHit(
                    id=chunk_id,
                    ref_id=str(metadata.get("ref_id") or metadata.get("artifact_id") or ""),
                    document=documents[index],
                    metadata=metadata,
                    score=1.0 - float(distances[index]),
                )
            )
        return hits

    def delete_by_ref(self, session: Session, collection: str, ref_id: str) -> None:
        self._collection(collection).delete(where={"ref_id": ref_id})

    def count(self, session: Session, collection: str) -> int:
        return int(self._collection(collection).count())


@lru_cache
def get_vector_store() -> VectorStore:
    if get_settings().vector_provider == "chroma":
        return ChromaVectorStore()
    return SqlVectorStore()
