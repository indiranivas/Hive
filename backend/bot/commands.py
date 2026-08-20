"""Parsing what a user typed at @Hive into an intent.

Kept free of botbuilder imports so the whole dispatch path is testable without
the Bot Framework SDK installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CommandKind = Literal["ask", "who_knows", "kr", "help", "status"]

# Teams delivers mentions as <at>Hive</at> inside activity.text.
MENTION_TAG_RE = re.compile(r"<at\b[^>]*>.*?</at>", re.IGNORECASE | re.DOTALL)
AT_NAME_RE = re.compile(r"(?:^|\s)@hive\b", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")

WHO_KNOWS_PREFIXES = (
    "who knows about",
    "who knows",
    "who-knows",
    "whoknows",
    "who has worked on",
    "who worked on",
    "who owns",
    "who is the expert on",
    "expert on",
)
KR_PREFIXES = ("kr ", "raise kr", "raise a kr", "knowledge request", "ask an expert")
HELP_WORDS = ("help", "?", "commands", "what can you do")
FILLER_PREFIXES = ("about ", "the ", "on ", "our ", "with ")


@dataclass(slots=True)
class Command:
    kind: CommandKind
    text: str
    raw: str


def strip_mentions(text: str | None) -> str:
    """Remove @Hive mentions and collapse whitespace."""
    cleaned = MENTION_TAG_RE.sub(" ", text or "")
    cleaned = AT_NAME_RE.sub(" ", cleaned)
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def _strip_filler(text: str) -> str:
    lowered = text.lower()
    for filler in FILLER_PREFIXES:
        if lowered.startswith(filler):
            return text[len(filler) :].strip()
    return text


def parse_command(text: str | None) -> Command:
    raw = strip_mentions(text)
    lowered = raw.lower()

    if not raw:
        return Command("help", "", raw)
    if lowered in HELP_WORDS or lowered.startswith("help"):
        return Command("help", "", raw)

    for prefix in KR_PREFIXES:
        if lowered.startswith(prefix):
            return Command("kr", raw[len(prefix) :].strip(" :"), raw)

    for prefix in WHO_KNOWS_PREFIXES:
        if lowered.startswith(prefix):
            topic = _strip_filler(raw[len(prefix) :].strip(" :?"))
            return Command("who_knows", topic, raw)

    if lowered == "status" or lowered.startswith("status "):
        return Command("status", raw[6:].strip(), raw)

    if lowered.startswith("ask "):
        return Command("ask", raw[4:].strip(), raw)

    return Command("ask", raw, raw)
