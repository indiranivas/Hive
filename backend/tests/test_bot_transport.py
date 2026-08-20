"""Bot Framework transport tests for bot/app.py.

Skipped unless the SDK is installed (`pip install -r requirements-bot.txt`),
which is why the rest of the bot's logic lives in SDK-free modules. What this
covers is the part only the transport can get wrong: turning a real Teams
activity into a card, pulling the user's identity out of the payload, and
storing the conversation reference for proactive messaging.

A recording adapter stands in for the channel, so no credentials or tunnel are
needed -- posting a fabricated activity at a live bot cannot work, because every
reply goes back to a serviceUrl that rejects it as Unauthorized.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("botbuilder.core", reason="needs requirements-bot.txt")

from botbuilder.core import BotAdapter, TurnContext  # noqa: E402
from botbuilder.schema import (  # noqa: E402
    Activity,
    ActivityTypes,
    ChannelAccount,
    ConversationAccount,
)

CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"


class RecordingAdapter(BotAdapter):
    """Captures outbound activities instead of calling the Bot Framework."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[Activity] = []

    async def send_activities(self, context, activities):
        self.sent.extend(activities)
        return []

    async def update_activity(self, context, activity):
        return None

    async def delete_activity(self, context, reference):
        return None


def _activity(text: str | None = None, value: dict | None = None,
              activity_type: str = ActivityTypes.message) -> Activity:
    return Activity(
        type=activity_type,
        id="activity-1",
        channel_id="msteams",
        service_url="https://smba.example.invalid/emea/",
        text=text,
        value=value,
        from_property=ChannelAccount(
            id="29:1abcdef",
            name="Nivas S",
            aad_object_id="aad-nivas-0001",
            additional_properties={"userPrincipalName": "nivas.s@example.com"},
        ),
        recipient=ChannelAccount(id="28:bot", name="Hive"),
        conversation=ConversationAccount(id="a:1conv", conversation_type="personal"),
    )


def _run_turn(activity: Activity) -> RecordingAdapter:
    from bot.app import HiveBot

    adapter = RecordingAdapter()
    asyncio.run(HiveBot().on_turn(TurnContext(adapter, activity)))
    return adapter


def _cards(adapter: RecordingAdapter) -> list[dict]:
    return [
        attachment.content
        for activity in adapter.sent
        for attachment in (activity.attachments or [])
        if attachment.content_type == CARD_CONTENT_TYPE
    ]


def _card_text(card: dict) -> str:
    return " ".join(
        block.get("text", "") for block in card.get("body", []) if block.get("type") == "TextBlock"
    )


@pytest.fixture
def committed(db_session, artifact_factory, person):
    """bot/app.py opens its own session, so fixture data must be committed to be
    visible to it."""
    artifact_factory(
        "Fix JWT refresh loop in billing auth middleware",
        "Cache the refreshed token for its full TTL and retry once.",
        metadata={"repo": "billing-service", "sha": "a1b2c3d4e5"},
    )
    person.azure_ad_id = "aad-nivas-0001"
    person.email = "nivas.s@example.com"
    db_session.commit()
    return person


def test_a_question_comes_back_as_an_adaptive_card(committed):
    adapter = _run_turn(_activity("<at>Hive</at> billing auth jwt refresh"))

    assert ActivityTypes.typing in [activity.type for activity in adapter.sent]
    cards = _cards(adapter)
    assert len(cards) == 1
    assert cards[0]["type"] == "AdaptiveCard"
    assert "billing-service@a1b2c3d4" in _card_text(cards[0]) or any(
        "billing-service@a1b2c3d4" in fact.get("value", "")
        for block in cards[0]["body"]
        if block.get("type") == "FactSet"
        for fact in block.get("facts", [])
    )


def test_the_turn_stores_a_conversation_reference(committed, db_session):
    """Without this, Hive could never message the person proactively."""
    from api.models.orm import BotConversation

    _run_turn(_activity("help"))

    db_session.expire_all()
    record = db_session.get(BotConversation, committed.id)
    assert record is not None
    assert record.service_url == "https://smba.example.invalid/emea/"
    assert record.conversation_reference


def test_a_card_action_round_trips(committed, db_session):
    from sqlalchemy import select

    from api.models.orm import KnowledgeRequest

    adapter = _run_turn(
        _activity(value={"action": "raise_kr", "question": "What signs our webhooks?"})
    )

    assert _cards(adapter)
    db_session.expire_all()
    kr = db_session.execute(select(KnowledgeRequest)).scalars().one()
    assert kr.question == "What signs our webhooks?"


def test_being_added_to_a_chat_sends_the_help_card(committed):
    activity = _activity(activity_type=ActivityTypes.conversation_update)
    activity.members_added = [ChannelAccount(id="29:1abcdef", name="Nivas S")]

    adapter = _run_turn(activity)

    cards = _cards(adapter)
    assert cards
    assert "Ask me about your team" in _card_text(cards[0])


def test_the_bot_itself_joining_does_not_trigger_a_reply(committed):
    activity = _activity(activity_type=ActivityTypes.conversation_update)
    activity.members_added = [ChannelAccount(id="28:bot", name="Hive")]

    adapter = _run_turn(activity)

    assert _cards(adapter) == []


def test_a_dispatch_failure_replies_instead_of_crashing(committed, monkeypatch):
    """A broken turn must apologise in-channel, not surface a 500 to Teams."""
    import bot.app as bot_app

    def explode(*args, **kwargs):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(bot_app, "_dispatch", explode)
    adapter = _run_turn(_activity("who knows billing-service"))

    text = " ".join(activity.text or "" for activity in adapter.sent)
    assert "Something broke" in text
    assert _cards(adapter) == []
