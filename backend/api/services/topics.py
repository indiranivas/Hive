"""Topic extraction -- the substrate for expertise scores and KR routing.

LLM extraction when a real provider is configured, otherwise a heuristic pass
over identifiers, paths and known tech vocabulary. Both return kebab-case slugs.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from api.core.config import get_settings
from api.core.embeddings import tokenize, words
from api.core.llm import LLMClient, get_llm
from api.core.prompts import TOPIC_EXTRACTION_PROMPT

GENERIC = words(
    "code work update updates fix fixes fixed bug bugs issue issues",
    "change changes changed add added adds remove removed refactor refactoring",
    "cleanup chore wip test tests testing merge merged revert bump version release",
    "feature stuff thing things misc minor major initial commit pull request review",
    "comment file files line lines todo done draft new old first second final",
    "please thanks thank hi hello regards team meeting call email reply",
    "following attached below above today tomorrow yesterday week month sprint",
)

TECH_VOCAB = words(
    "api rest graphql grpc webhook oauth oauth2 saml sso jwt token auth",
    "authentication authorization rbac session cookie csrf cors tls ssl",
    "certificate encryption redis postgres postgresql mysql sqlite mongodb",
    "kafka rabbitmq celery airflow cron queue worker scheduler",
    "docker kubernetes k8s helm terraform ansible azure aws gcp lambda s3",
    "blob storage cdn nginx gunicorn uvicorn fastapi flask django express",
    "react nextjs vue angular svelte typescript javascript python java golang",
    "rust csharp dotnet tailwind css html sql orm sqlalchemy alembic migration",
    "schema index cache caching pagination throttling ratelimit retry idempotency",
    "billing invoice payment stripe salesforce sharepoint graph teams devops ado",
    "pipeline ci cd build deploy deployment rollback observability logging",
    "metrics tracing prometheus grafana sentry embedding embeddings vector",
    "chromadb qdrant llm prompt rag chunking tokenizer transformer inference",
    "latency throughput timeout websocket sse polling parser serializer",
    "validation pydantic dto middleware router endpoint controller service",
    "repository model dashboard chart frontend backend mobile ios android",
    "sdk cli bot connector ingestion normalizer transcript mailbox",
)

QUALIFIERS = words(
    "api service module pipeline connector endpoint worker job queue schema",
    "migration dashboard token auth layer client server webhook parser cache",
    "index report bot",
)

EXTENSION_TOPICS = {
    "py": "python",
    "ts": "typescript",
    "tsx": "react",
    "js": "javascript",
    "jsx": "react",
    "java": "java",
    "cs": "csharp",
    "go": "golang",
    "rs": "rust",
    "sql": "sql",
    "tf": "terraform",
    "yml": "configuration",
    "yaml": "configuration",
    "css": "css",
    "html": "html",
}

SLUG_RE = re.compile(r"[^a-z0-9]+")
CAMEL_RE = re.compile(r"[A-Z][a-z0-9]+(?=[A-Z]|\b)")
PATH_RE = re.compile(r"[\w\-/]+\.[a-z]{1,4}\b")


def slugify(value: str) -> str:
    return SLUG_RE.sub("-", value.strip().lower()).strip("-")


def _is_useful(slug: str) -> bool:
    if len(slug) < 3 or slug.isdigit():
        return False
    parts = slug.split("-")
    return not all(part in GENERIC or part.isdigit() for part in parts)


def _add_path_topics(counts: Counter[str], paths: list[str], weight: int = 2) -> None:
    """Credit the language and the module name behind each file path."""
    for path in paths:
        stem, _, extension = path.lower().rpartition(".")
        if extension in EXTENSION_TOPICS:
            counts[EXTENSION_TOPICS[extension]] += weight
        module = slugify(stem.split("/")[-1])
        if _is_useful(module):
            counts[module] += weight


def extract_topics_heuristic(text: str, metadata: dict[str, Any] | None = None,
                             limit: int = 5) -> list[str]:
    counts: Counter[str] = Counter()

    _add_path_topics(counts, PATH_RE.findall(text.lower()))

    for camel in CAMEL_RE.findall(text):
        slug = slugify(camel)
        if slug in TECH_VOCAB or (len(slug) > 4 and slug not in GENERIC):
            counts[slug] += 1

    tokens = tokenize(text)
    for token in tokens:
        slug = slugify(token)
        if not _is_useful(slug):
            continue
        if slug in TECH_VOCAB or "-" in slug or "_" in token or "." in token:
            counts[slug] += 2

    for left, right in zip(tokens, tokens[1:], strict=False):
        if right in QUALIFIERS and left not in GENERIC and len(left) > 2:
            pair = slugify(f"{left}-{right}")
            if _is_useful(pair):
                counts[pair] += 3

    if metadata:
        for key in ("repo", "repository", "project", "iteration"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                slug = slugify(value.split("/")[-1])
                if _is_useful(slug):
                    counts[slug] += 3
        for tag in metadata.get("tags") or []:
            slug = slugify(str(tag))
            if _is_useful(slug):
                counts[slug] += 3
        # Changed files name the modules and languages someone actually touched.
        files = metadata.get("files_changed")
        if isinstance(files, list):
            _add_path_topics(counts, [str(path) for path in files], weight=3)

    ranked = sorted(counts.items(), key=lambda item: (-item[1], "-" not in item[0], item[0]))
    return [slug for slug, _ in ranked[:limit]]


def extract_topics_llm(text: str, llm: LLMClient, limit: int = 5) -> list[str]:
    response = llm.chat(
        system=TOPIC_EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": text[:6000]}],
    )
    match = re.search(r"\[.*\]", response.text, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    topics = [slugify(str(item)) for item in parsed if isinstance(item, (str, int))]
    return [topic for topic in topics if _is_useful(topic)][:limit]


def extract_topics(text: str, metadata: dict[str, Any] | None = None,
                   limit: int = 5) -> list[str]:
    settings = get_settings()
    if settings.llm_provider != "stub":
        try:
            topics = extract_topics_llm(text, get_llm(), limit=limit)
        except Exception:  # noqa: BLE001 - never fail ingestion on topic extraction
            topics = []
        if topics:
            return topics
    return extract_topics_heuristic(text, metadata, limit=limit)
