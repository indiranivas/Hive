"""Proactive delivery into Teams.

Split from bot/app.py so the Celery worker can send without importing the whole
aiohttp bot. Requires the Bot Framework SDK (requirements-bot.txt).
"""

from __future__ import annotations

import asyncio
from typing import Any

from api.models.orm import Notification
from bot import cards


def notification_card(notification: Notification) -> dict[str, Any]:
    """Render an outbox row as an Adaptive Card."""
    return cards.notice_card(notification.subject, notification.body or "")


def send_notification(reference: dict[str, Any], notification: Notification) -> None:
    """Deliver one notification. Raises if the SDK or channel is unavailable."""
    try:
        from botbuilder.core import MessageFactory
        from botbuilder.integration.aiohttp import (
            CloudAdapter,
            ConfigurationBotFrameworkAuthentication,
        )
        from botbuilder.schema import Attachment, ConversationReference
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "proactive delivery needs the Bot Framework SDK: "
            "pip install -r requirements-bot.txt"
        ) from exc

    from bot.app import BotConfig

    adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(BotConfig()))
    card = notification_card(notification)

    async def send(turn_context) -> None:
        await turn_context.send_activity(
            MessageFactory.attachment(
                Attachment(
                    content_type=cards.CARD_CONTENT_TYPE,
                    content=card,
                )
            )
        )

    asyncio.run(
        adapter.continue_conversation(
            ConversationReference().deserialize(reference),
            send,
            BotConfig.APP_ID,
        )
    )
