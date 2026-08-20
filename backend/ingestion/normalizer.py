"""Raw source payloads -> the unified WorkArtifact DTO (blueprint section 6.5)."""

from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.config import get_settings
from api.core.timeutil import as_utc  # re-exported: connectors import it from here
from api.models.orm import Person

__all__ = [
    "WorkArtifact",
    "as_utc",
    "chunk_content",
    "display_name_from_email",
    "resolve_person",
    "strip_html",
    "strip_quoted_reply",
]

SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
BREAK_RE = re.compile(r"<(br|/p|/div|/tr|/li|/h[1-6])\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
BLANKS_RE = re.compile(r"[ \t\r\f\v]+")
NEWLINES_RE = re.compile(r"\n{3,}")
QUOTED_REPLY_RE = re.compile(
    r"\n(-{2,}\s*original message\s*-{2,}|from:\s.+?\nsent:\s)", re.IGNORECASE | re.DOTALL
)
NOREPLY_RE = re.compile(r"(noreply|no-reply|donotreply|mailer-daemon)", re.IGNORECASE)


@dataclass(slots=True)
class WorkArtifact:
    """Source-agnostic record. Mirrors the work_artifacts table."""

    source: str
    source_id: str
    artifact_type: str
    content: str
    occurred_at: datetime
    title: str | None = None
    author_id: uuid.UUID | None = None
    author_name: str | None = None
    team_id: uuid.UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = SCRIPT_STYLE_RE.sub(" ", raw)
    text = BREAK_RE.sub("\n", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = BLANKS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return NEWLINES_RE.sub("\n\n", text).strip()


def strip_quoted_reply(text: str) -> str:
    """Drop the quoted tail of an email so each thread message embeds once."""
    match = QUOTED_REPLY_RE.search(text)
    return text[: match.start()].strip() if match else text.strip()


def display_name_from_email(email: str) -> str:
    local = email.split("@")[0]
    parts = [part for part in re.split(r"[._\-+]", local) if part]
    return " ".join(part.capitalize() for part in parts) or email


def resolve_person(session: Session, email: str | None, display_name: str | None = None,
                   team_id: uuid.UUID | None = None) -> Person | None:
    """Find or create the person behind an artifact.

    Connectors know emails long before people sign in through Entra ID, so
    auto-created rows carry no azure_ad_id until their first login.
    """
    if not email or "@" not in email or NOREPLY_RE.search(email):
        return None
    normalized = email.strip().lower()
    person = session.execute(
        select(Person).where(func.lower(Person.email) == normalized)
    ).scalar_one_or_none()
    if person:
        if display_name and person.display_name in (person.email, ""):
            person.display_name = display_name
        if team_id and person.team_id is None:
            person.team_id = team_id
        return person

    person = Person(
        email=normalized,
        display_name=display_name or display_name_from_email(normalized),
        team_id=team_id,
    )
    session.add(person)
    session.flush()
    return person


def chunk_content(content: str, max_tokens: int | None = None,
                  overlap_ratio: float | None = None) -> list[str]:
    """Split into overlapping, sentence-aligned chunks for embedding.

    Any single sentence longer than the window is hard-split on word count so a
    minified blob or a wall-of-text transcript can never produce one giant chunk.
    """
    settings = get_settings()
    window = max_tokens or settings.chunk_max_tokens
    overlap = settings.chunk_overlap_ratio if overlap_ratio is None else overlap_ratio
    text = (content or "").strip()
    if not text:
        return []

    sentences: list[str] = []
    for raw in re.split(r"(?<=[.!?])\s+|\n{2,}", text):
        sentence = raw.strip()
        if not sentence:
            continue
        words = sentence.split()
        if len(words) <= window:
            sentences.append(sentence)
            continue
        for start in range(0, len(words), window):
            sentences.append(" ".join(words[start : start + window]))

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        length = len(sentence.split())
        if current and current_len + length > window:
            chunks.append(" ".join(current))
            keep = max(1, int(len(current) * overlap)) if overlap > 0 else 0
            current = current[len(current) - keep :] if keep else []
            current_len = sum(len(item.split()) for item in current)
        current.append(sentence)
        current_len += length
    if current:
        chunks.append(" ".join(current))
    return chunks
