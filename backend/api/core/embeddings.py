"""Embedding providers -- open source only, nothing leaves the machine.

`hashing` is the default: a deterministic, dependency-free lexical embedder so
the pipeline runs offline and tests are reproducible. It captures term overlap,
not semantics -- switch EMBEDDING_PROVIDER to sentence-transformers (local
models, no egress) for real semantic recall.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from functools import lru_cache

from api.core.config import get_settings

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-/+#]*")


def words(*lines: str) -> frozenset[str]:
    """Build a vocabulary set from space-separated lines."""
    return frozenset(word for line in lines for word in line.split())


STOPWORDS = words(
    "a an the and or but if then else of in on at to from for with without by as",
    "is are was were be been being do does did doing have has had",
    "this that these those it its i you he she we they them his her our your their",
    "not no so than too very can will just should now",
    "what which who whom when where why how",
)


def tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS and len(tok) > 1]


class Embedder(ABC):
    dim: int

    @abstractmethod
    def encode(self, texts: list[str]) -> list[list[float]]: ...

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]


class HashingEmbedder(Embedder):
    """Signed feature hashing over unigrams + bigrams, sublinear tf, L2 normalized."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _features(self, text: str) -> Counter[str]:
        tokens = tokenize(text)
        features: Counter[str] = Counter(tokens)
        features.update(f"{a}|{b}" for a, b in zip(tokens, tokens[1:], strict=False))
        return features

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        sign = 1.0 if value & 1 else -1.0
        return (value >> 1) % self.dim, sign

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dim
            for feature, count in self._features(text).items():
                index, sign = self._bucket(feature)
                vector[index] += sign * (1.0 + math.log(count))
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector] if norm else vector)
        return vectors


class SentenceTransformersEmbedder(Embedder):
    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "EMBEDDING_PROVIDER=sentence-transformers requires "
                "`pip install -r requirements-ml.txt`"
            ) from exc
        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - heavy dep
        return [
            vector.tolist()
            for vector in self._model.encode(texts, normalize_embeddings=True, batch_size=32)
        ]


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_provider == "sentence-transformers":
        return SentenceTransformersEmbedder(settings.embedding_model)
    return HashingEmbedder(dim=settings.embedding_dim)


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
