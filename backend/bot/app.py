"""Bot Framework transport for @Hive.

The only module that imports botbuilder. All decisions live in bot/handlers.py,
so this file stays a shim: receive activity -> run sync handler in a thread ->
send the card back.

Run locally:
    python -m bot.app                      # listens on :3978
    ngrok http 3978                        # public HTTPS for the Bot Service
Point the Azure Bot messaging endpoint at https://<tunnel>/api/messages
"""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import select

from api.core.config import get_settings
from api.core.db import init_db, session_scope
from api.models.orm import Person
from bot.handlers import BotUser, handle_activity
from bot.proactive import remember_conversation, serialize_reference

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    from aiohttp import web
    from botbuilder.core import ActivityHandler, MessageFactory, TurnContext
    from botbuilder.core.integration import aiohttp_error_middleware
    from botbuilder.integration.aiohttp import (
        CloudAdapter,
        ConfigurationBotFrameworkAuthentication,
    )
    from botbuilder.schema import Activity, ActivityTypes, Attachment, ChannelAccount
except ImportError as exc:  # pragma: no cover - optional transport dependency
    raise SystemExit(
        "The Teams bot needs the Bot Framework SDK:\n"
        "    pip install -r requirements-bot.txt\n"
        f"(import failed: {exc})"
    ) from exc


class BotConfig:
    """Shape ConfigurationBotFrameworkAuthentication expects."""

    APP_ID = settings.bot_app_id or ""
    APP_PASSWORD = settings.bot_app_password or ""
    APP_TYPE = "MultiTenant"
    APP_TENANTID = settings.azure_ad_tenant_id or ""


def _user_from_activity(activity: Activity) -> BotUser:
    sender: ChannelAccount | None = activity.from_property
    email = None
    if sender is not None:
        # Teams puts the UPN in different places depending on scope and consent.
        properties = getattr(sender, "additional_properties", None) or {}
        email = properties.get("userPrincipalName") or properties.get("email")
    return BotUser(
        aad_object_id=getattr(sender, "aad_object_id", None),
        email=email,
        name=getattr(sender, "name", None),
    )


def _dispatch(activity_text: str | None, activity_value: dict | None, user: BotUser,
              reference: dict) -> tuple[list[dict], str | None]:
    """Sync worker: one transaction per turn."""
    with session_scope() as session:
        reply = handle_activity(session, text=activity_text, value=activity_value, user=user)
        person = None
        if reference:
            if user.aad_object_id:
                person = session.execute(
                    select(Person).where(Person.azure_ad_id == user.aad_object_id)
                ).scalar_one_or_none()
            if person is not None:
                remember_conversation(session, person.id, reference)
        return reply.attachments, reply.text


class HiveBot(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity = turn_context.activity
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        user = _user_from_activity(activity)
        reference = serialize_reference(TurnContext.get_conversation_reference(activity))
        value = activity.value if isinstance(activity.value, dict) else None

        try:
            attachments, text = await asyncio.to_thread(
                _dispatch, activity.text, value, user, reference
            )
        except Exception:
            logger.exception("dispatch failed for activity %s", activity.id)
            await turn_context.send_activity(
                MessageFactory.text(
                    "Something broke on my side. The error is logged; nothing was changed."
                )
            )
            return

        if attachments:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    attachments=[
                        Attachment(
                            content_type=attachment["contentType"],
                            content=attachment["content"],
                        )
                        for attachment in attachments
                    ],
                )
            )
        elif text:
            await turn_context.send_activity(MessageFactory.text(text))

    async def on_members_added_activity(self, members_added, turn_context: TurnContext) -> None:
        bot_id = turn_context.activity.recipient.id
        for member in members_added:
            if member.id == bot_id:
                continue
            attachments, _ = await asyncio.to_thread(
                _dispatch, "help", None, _user_from_activity(turn_context.activity), {}
            )
            if attachments:
                await turn_context.send_activity(
                    Activity(
                        type=ActivityTypes.message,
                        attachments=[
                            Attachment(
                                content_type=attachment["contentType"],
                                content=attachment["content"],
                            )
                            for attachment in attachments
                        ],
                    )
                )


def build_app() -> web.Application:
    adapter = CloudAdapter(ConfigurationBotFrameworkAuthentication(BotConfig()))
    bot = HiveBot()

    async def on_error(context: TurnContext, error: Exception) -> None:
        logger.exception("unhandled bot error: %s", error)
        await context.send_activity("Hive hit an unexpected error. It has been logged.")

    adapter.on_turn_error = on_error

    async def messages(request: web.Request) -> web.Response:
        return await adapter.process(request, bot)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "surface": "teams"})

    app = web.Application(middlewares=[aiohttp_error_middleware])
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/health", health)
    return app


def main() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    if not settings.bot_app_id:
        logger.warning(
            "BOT_APP_ID is unset. Local emulator traffic works; Teams will not authenticate."
        )
    if settings.auto_create_schema:
        init_db()
    try:
        web.run_app(build_app(), host="0.0.0.0", port=3978)
    except OSError as exc:  # pragma: no cover - port already taken
        logger.error("cannot bind :3978 (%s)", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
