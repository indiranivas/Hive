"""Embedding providers.

`hashing` is the default: a deterministic, dependency-free lexical embedder so
the pipeline runs offline and tests are reproducible. It captures term overlap,
not semantics -- switch EMBEDDING_PROVIDER to azure_openai (production) or
sentence-transformers (local, no egress) for real semantic recall.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
from functools import lru_cache

import httpx

from api.core.azure_auth import build_auth_headers
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


class MistralEmbedder(Embedder):
    URL = "https://api.mistral.ai/v1/embeddings"
    BATCH = 64

    def __init__(self, api_key: str, model: str = "mistral-embed", dim: int = 1024) -> None:
        if not api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=mistral requires LLM_API_KEY")
        self._api_key = api_key
        self._model = model
        self.dim = dim

    def encode(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - network
        vectors: list[list[float]] = []
        with httpx.Client(timeout=60.0) as client:
            for start in range(0, len(texts), self.BATCH):
                batch = texts[start : start + self.BATCH]
                response = client.post(
                    self.URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": batch},
                )
                response.raise_for_status()
                vectors.extend(item["embedding"] for item in response.json()["data"])
        return vectors


class AzureOpenAIEmbedder(Embedder):
    """Azure OpenAI Service embeddings.

    `dimensions` is sent when set: the v3 embedding models can be shortened,
    which matters here because the SQL vector store keeps vectors as JSON and
    scans them in Python -- 3072 floats per chunk is a lot of rows to carry.
    """

    BATCH = 16  # Azure's per-request input cap is lower than OpenAI's

    def __init__(self, endpoint: str, deployment: str, api_version: str,
                 api_key: str | None = None, auth_mode: str = "key",
                 dim: int = 1536, send_dimensions: bool = False, timeout: float = 60.0,
                 client: httpx.Client | None = None,
                 token_provider: Callable[[], str] | None = None) -> None:
        if not endpoint:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT"
            )
        if not deployment:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=azure_openai requires "
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
            )
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._api_version = api_version
        self._api_key = api_key
        self._auth_mode = auth_mode
        self.dim = dim
        self._send_dimensions = send_dimensions
        self._timeout = timeout
        self._client = client
        self._token_provider = token_provider

    @property
    def url(self) -> str:
        return (
            f"{self._endpoint}/openai/deployments/{self._deployment}/embeddings"
            f"?api-version={self._api_version}"
        )

    def build_payload(self, batch: list[str]) -> dict:
        payload: dict = {"input": batch}
        if self._send_dimensions:
            payload["dimensions"] = self.dim
        return payload

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(self._auth_mode, self._api_key, self._token_provider),
        }
        client = self._client or httpx.Client(timeout=self._timeout)
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.BATCH):
                batch = texts[start : start + self.BATCH]
                response = client.post(
                    self.url, headers=headers, json=self.build_payload(batch)
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda item: item.get("index", 0))
                vectors.extend(item["embedding"] for item in data)
        finally:
            if self._client is None:
                client.close()
        return vectors


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_provider == "sentence-transformers":
        return SentenceTransformersEmbedder(settings.embedding_model)
    if settings.embedding_provider == "azure_openai":
        return AzureOpenAIEmbedder(
            endpoint=settings.azure_openai_endpoint or "",
            deployment=settings.azure_openai_embedding_deployment or "",
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key,
            auth_mode=settings.azure_openai_auth,
            dim=settings.embedding_dim,
            send_dimensions=settings.azure_openai_send_dimensions,
            timeout=settings.llm_timeout_seconds,
        )
    if settings.embedding_provider == "mistral":
        return MistralEmbedder(settings.llm_api_key or "", dim=settings.embedding_dim)
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
