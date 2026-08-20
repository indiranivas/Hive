"""Adaptive Card templates (blueprint section 9.3).

Plain dicts, no SDK types, so cards can be asserted on in tests and rendered by
any surface. Teams supports Adaptive Cards up to 1.5.
"""

from __future__ import annotations

from typing import Any

CARD_VERSION = "1.5"
CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
MAX_SOURCES_SHOWN = 5
ANSWER_CHAR_LIMIT = 3000


def _card(body: list[dict], actions: list[dict] | None = None) -> dict[str, Any]:
    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": CARD_VERSION,
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def _text(text: str, *, size: str | None = None, weight: str | None = None,
          color: str | None = None, subtle: bool = False, spacing: str | None = None) -> dict:
    block: dict[str, Any] = {"type": "TextBlock", "text": text, "wrap": True}
    if size:
        block["size"] = size
    if weight:
        block["weight"] = weight
    if color:
        block["color"] = color
    if subtle:
        block["isSubtle"] = True
    if spacing:
        block["spacing"] = spacing
    return block


def _truncate(text: str, limit: int = ANSWER_CHAR_LIMIT) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _paragraphs(text: str) -> str:
    """Force blank lines between lines of an answer.

    A TextBlock renders markdown, and Teams collapses single newlines -- bullet
    lists and multi-line answers run together without a blank line between them.
    """
    lines = [line.strip() for line in (text or "").splitlines()]
    return "\n\n".join(line for line in lines if line)


def source_label(source: dict[str, Any]) -> str:
    """One-line provenance: who, when, and the hard reference."""
    parts = [source.get("author") or "unknown", source.get("date") or "-"]
    reference = source.get("reference")
    if reference:
        parts.append(str(reference))
    return " | ".join(parts)


def answer_card(question: str, answer: str, sources: list[dict[str, Any]],
                has_gap: bool = False, model: str = "") -> dict[str, Any]:
    body: list[dict] = [
        _text("Hive", size="Small", weight="Bolder", subtle=True),
        _text(question, weight="Bolder", size="Medium"),
        _text(_paragraphs(_truncate(answer)), spacing="Medium"),
    ]

    shown = sources[:MAX_SOURCES_SHOWN]
    if shown:
        body.append(_text("Sources", weight="Bolder", spacing="Medium"))
        body.append(
            {
                "type": "FactSet",
                "facts": [
                    {
                        "title": f"{index}. {source.get('title') or '(no title)'}",
                        "value": source_label(source),
                    }
                    for index, source in enumerate(shown, start=1)
                ],
            }
        )
        if len(sources) > MAX_SOURCES_SHOWN:
            body.append(
                _text(f"+{len(sources) - MAX_SOURCES_SHOWN} more sources", subtle=True,
                      size="Small")
            )
    else:
        body.append(_text("No matching evidence in the team's work trail.", subtle=True))

    if model:
        body.append(_text(f"model: {model}", size="Small", subtle=True, spacing="Small"))

    actions: list[dict] = []
    if has_gap:
        actions.append(
            {
                "type": "Action.Submit",
                "title": "Raise a Knowledge Request",
                "data": {"action": "raise_kr", "question": question},
            }
        )
    for source in shown:
        url = source.get("url")
        if url:
            actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": f"Open {source.get('reference') or 'source'}",
                    "url": url,
                }
            )
    return _card(body, actions)


def experts_card(topic: str, experts: list[dict[str, Any]]) -> dict[str, Any]:
    body: list[dict] = [
        _text("Who knows this", size="Small", weight="Bolder", subtle=True),
        _text(topic, weight="Bolder", size="Medium"),
    ]
    if not experts:
        body.append(
            _text(
                "No evidence yet. Nobody on this team has work artifacts on that topic.",
                spacing="Medium",
            )
        )
        return _card(
            body,
            [
                {
                    "type": "Action.Submit",
                    "title": "Raise a Knowledge Request",
                    "data": {"action": "raise_kr", "question": f"Who knows about {topic}?"},
                }
            ],
        )

    for rank, expert in enumerate(experts, start=1):
        topics = ", ".join(expert.get("topics", [])[:4])
        last_seen = expert.get("last_seen") or "-"
        body.append(
            {
                "type": "Container",
                "spacing": "Medium",
                "items": [
                    _text(f"{rank}. {expert.get('display_name')}", weight="Bolder"),
                    _text(
                        f"{expert.get('email')} | score {expert.get('score')} | "
                        f"{expert.get('evidence_count')} artifacts | last seen {last_seen}",
                        size="Small",
                        subtle=True,
                    ),
                    _text(f"Evidence topics: {topics}", size="Small") if topics else _text(""),
                ],
            }
        )
    return _card(body)


def kr_created_card(question: str, kr_id: str, tags: list[str],
                    routing_note: str) -> dict[str, Any]:
    body = [
        _text("Knowledge Request raised", size="Small", weight="Bolder", subtle=True),
        _text(question, weight="Bolder", size="Medium"),
        _text(f"Reference: {kr_id}", size="Small", subtle=True),
    ]
    if tags:
        body.append(_text(f"Tagged: {', '.join(tags)}", size="Small", spacing="Small"))
    body.append(_text(routing_note, spacing="Medium"))
    return _card(body)


def help_card() -> dict[str, Any]:
    return _card(
        [
            _text("Hive", size="Small", weight="Bolder", subtle=True),
            _text("Ask me about your team's work", weight="Bolder", size="Medium"),
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Ask anything", "value": "@Hive who fixed the billing auth bug?"},
                    {"title": "Find an expert", "value": "@Hive who knows jwt-auth"},
                    {"title": "Raise a request", "value": "@Hive kr how do we rotate the PAT?"},
                    {"title": "Help", "value": "@Hive help"},
                ],
            },
            _text(
                "Every answer cites the commits, PRs and tickets it came from. Hive is "
                "read-only: it never posts, commits or emails on your behalf.",
                size="Small",
                subtle=True,
                spacing="Medium",
            ),
        ]
    )


def notice_card(title: str, message: str) -> dict[str, Any]:
    return _card(
        [
            _text("Hive", size="Small", weight="Bolder", subtle=True),
            _text(title, weight="Bolder", size="Medium"),
            _text(message, spacing="Medium"),
        ]
    )


def as_attachment(card: dict[str, Any]) -> dict[str, Any]:
    """Wrap a card for Bot Framework / REST delivery."""
    return {"contentType": CARD_CONTENT_TYPE, "content": card}
