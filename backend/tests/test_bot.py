"""Bot logic tests: parsing, dispatch, cards, identity mapping, proactive storage.

bot/app.py (the Bot Framework transport) is deliberately excluded -- it needs the
SDK installed and a live channel. Everything it delegates to is covered here.
"""

from __future__ import annotations

from sqlalchemy import func, select

from api.models.orm import BotConversation, KnowledgeRequest, Person
from bot import cards
from bot.commands import parse_command, strip_mentions
from bot.handlers import BotUser, handle_activity, resolve_bot_person
from bot.proactive import get_conversation, remember_conversation, serialize_reference

# --- command parsing ---------------------------------------------------------


def test_strip_mentions_removes_teams_markup():
    assert strip_mentions("<at>Hive</at> who broke the build?") == "who broke the build?"
    assert strip_mentions("@Hive   status") == "status"
    assert strip_mentions(None) == ""


def test_parse_ask_is_the_default():
    command = parse_command("<at>Hive</at> who wrote the most commits this week?")
    assert command.kind == "ask"
    assert command.text == "who wrote the most commits this week?"


def test_parse_explicit_ask_prefix():
    assert parse_command("ask why did billing fail?").text == "why did billing fail?"


def test_parse_help_variants():
    for text in ("help", "Help", "?", "commands", "<at>Hive</at>", "what can you do"):
        assert parse_command(text).kind == "help", text


def test_parse_who_knows_variants_and_filler():
    for text in (
        "who knows billing-service",
        "who knows about billing-service",
        "who-knows billing-service",
        "who has worked on billing-service",
        "who owns billing-service?",
    ):
        command = parse_command(text)
        assert command.kind == "who_knows", text
        assert command.text == "billing-service", text


def test_parse_kr_variants():
    assert parse_command("kr how do we rotate the PAT?").kind == "kr"
    assert parse_command("raise kr: how do we rotate the PAT?").text == (
        "how do we rotate the PAT?"
    )


def test_parse_status():
    assert parse_command("status").kind == "status"
    assert parse_command("status deepa").text == "deepa"


# --- cards -------------------------------------------------------------------


def _sources() -> list[dict]:
    return [
        {
            "title": "Fix JWT refresh loop",
            "author": "Deepa V",
            "date": "2026-08-16",
            "reference": "billing-service@a1b2c3d4",
        }
    ]


def test_answer_card_shape_and_sources():
    card = cards.answer_card("who fixed billing?", "Deepa V did.", _sources(), model="stub")
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == cards.CARD_VERSION
    factset = next(block for block in card["body"] if block["type"] == "FactSet")
    assert "billing-service@a1b2c3d4" in factset["facts"][0]["value"]
    assert "actions" not in card  # no gap -> no KR button


def test_answer_card_offers_kr_when_gap():
    card = cards.answer_card("unknowable?", "No evidence.", [], has_gap=True)
    action = card["actions"][0]
    assert action["type"] == "Action.Submit"
    assert action["data"] == {"action": "raise_kr", "question": "unknowable?"}


def test_answer_card_truncates_and_caps_sources():
    many = [dict(_sources()[0], title=f"Source {index}") for index in range(9)]
    card = cards.answer_card("q", "x" * 5000, many)
    body_text = " ".join(
        block.get("text", "") for block in card["body"] if block["type"] == "TextBlock"
    )
    assert "..." in body_text
    assert "+4 more sources" in body_text
    factset = next(block for block in card["body"] if block["type"] == "FactSet")
    assert len(factset["facts"]) == cards.MAX_SOURCES_SHOWN


def test_answer_card_separates_lines_into_paragraphs():
    """Teams collapses single newlines, so bullets must be blank-line separated."""
    answer = "Deepa V fixed it:" + chr(10) + "- commit a1b2c3d4" + chr(10) + "- PR #312"
    card = cards.answer_card("who fixed it?", answer, [])
    answer_block = card["body"][2]["text"]
    assert chr(10) * 2 in answer_block
    assert answer_block.count("- ") == 2
    assert chr(10) * 3 not in answer_block


def test_answer_card_adds_open_url_action_when_source_has_url():
    sources = [dict(_sources()[0], url="https://dev.azure.com/x/_git/y/commit/a1b2c3d4")]
    card = cards.answer_card("q", "a", sources)
    assert card["actions"][0]["type"] == "Action.OpenUrl"


def test_experts_card_empty_offers_kr():
    card = cards.experts_card("kubernetes", [])
    assert card["actions"][0]["data"]["action"] == "raise_kr"


def test_as_attachment_wraps_for_bot_framework():
    attachment = cards.as_attachment(cards.help_card())
    assert attachment["contentType"] == cards.CARD_CONTENT_TYPE
    assert attachment["content"]["type"] == "AdaptiveCard"


# --- identity ----------------------------------------------------------------


def test_resolve_bot_person_matches_on_entra_object_id(db_session, person):
    person.azure_ad_id = "aad-123"
    db_session.flush()
    resolved = resolve_bot_person(db_session, BotUser(aad_object_id="aad-123"))
    assert resolved.id == person.id


def test_resolve_bot_person_backfills_entra_id_on_email_match(db_session, person):
    """The git connector created this person from a commit email; first sign-in links it."""
    assert person.azure_ad_id is None
    resolved = resolve_bot_person(
        db_session, BotUser(aad_object_id="aad-456", email="DEV.ONE@example.com")
    )
    assert resolved.id == person.id
    assert resolved.azure_ad_id == "aad-456"
    assert db_session.execute(select(func.count(Person.id))).scalar_one() == 1


def test_resolve_bot_person_handles_missing_email(db_session):
    resolved = resolve_bot_person(db_session, BotUser(aad_object_id="aad-789", name="Guest"))
    assert resolved.email == "aad-789@teams.local"
    assert resolved.display_name == "Guest"


# --- dispatch ----------------------------------------------------------------


def test_ask_returns_an_answer_card_with_sources(db_session, artifact_factory, person):
    artifact_factory(
        "Fix JWT refresh loop in billing auth middleware",
        "Cache the refreshed token for its full TTL and retry once.",
        metadata={"repo": "billing-service", "sha": "a1b2c3d4e5"},
    )
    person.azure_ad_id = "aad-1"
    db_session.flush()

    reply = handle_activity(
        db_session,
        text="<at>Hive</at> billing auth jwt refresh",
        user=BotUser(aad_object_id="aad-1", email=person.email),
    )
    assert reply.kind == "answer"
    assert reply.meta["sources"] >= 1
    assert reply.attachments[0]["contentType"] == cards.CARD_CONTENT_TYPE


def test_ask_with_no_evidence_offers_a_knowledge_request(db_session, person):
    person.azure_ad_id = "aad-1"
    db_session.flush()
    reply = handle_activity(
        db_session,
        text="what is our kubernetes autoscaling policy?",
        user=BotUser(aad_object_id="aad-1", email=person.email),
    )
    assert reply.meta["has_gap"] is True
    assert reply.card["actions"][0]["data"]["action"] == "raise_kr"


def test_who_knows_returns_experts(db_session, person, team):
    from datetime import UTC, datetime

    from api.services.expertise_mapper import update_expertise

    update_expertise(db_session, person.id, ["billing-service"], datetime.now(UTC))
    person.azure_ad_id = "aad-1"
    db_session.flush()

    reply = handle_activity(
        db_session,
        text="who knows billing-service",
        user=BotUser(aad_object_id="aad-1", email=person.email),
    )
    assert reply.kind == "experts"
    assert reply.meta["experts"] == 1


def test_who_knows_without_a_topic_asks_for_one(db_session, person):
    reply = handle_activity(db_session, text="who knows", user=BotUser(email=person.email))
    assert reply.kind == "notice"


def test_kr_command_records_a_request(db_session, person):
    reply = handle_activity(
        db_session,
        text="kr how do we rotate the ADO PAT?",
        user=BotUser(aad_object_id="aad-1", email=person.email),
    )
    assert reply.kind == "kr_created"
    kr = db_session.execute(select(KnowledgeRequest)).scalars().one()
    assert kr.question == "how do we rotate the ADO PAT?"
    assert kr.requester_id == person.id
    assert kr.status == "open"
    assert kr.routed_to_id is None  # routing is Phase 4


def test_raise_kr_button_creates_a_request_and_is_idempotent(db_session, person):
    payload = {"action": "raise_kr", "question": "what is our autoscaling policy?"}
    user = BotUser(aad_object_id="aad-1", email=person.email)

    first = handle_activity(db_session, value=payload, user=user)
    second = handle_activity(db_session, value=payload, user=user)

    assert first.meta["kr_id"] == second.meta["kr_id"]
    assert db_session.execute(select(func.count(KnowledgeRequest.id))).scalar_one() == 1


def test_unknown_card_action_is_reported_not_crashed(db_session, person):
    reply = handle_activity(
        db_session, value={"action": "launch_missiles"}, user=BotUser(email=person.email)
    )
    assert reply.kind == "notice"


def test_status_command_says_it_is_not_built_yet(db_session, person):
    reply = handle_activity(db_session, text="status", user=BotUser(email=person.email))
    assert reply.kind == "notice"
    assert "Phase 3" in reply.card["body"][-1]["text"]


def test_empty_message_returns_help(db_session, person):
    reply = handle_activity(db_session, text="<at>Hive</at>", user=BotUser(email=person.email))
    assert reply.kind == "help"


# --- proactive storage -------------------------------------------------------


def test_remember_conversation_upserts(db_session, person):
    remember_conversation(db_session, person.id, {"serviceUrl": "https://smba.one", "id": "a"})
    remember_conversation(db_session, person.id, {"serviceUrl": "https://smba.two", "id": "b"})

    records = db_session.execute(select(BotConversation)).scalars().all()
    assert len(records) == 1
    assert records[0].service_url == "https://smba.two"
    assert get_conversation(db_session, person.id)["id"] == "b"


def test_get_conversation_is_none_when_unseen(db_session, person):
    assert get_conversation(db_session, person.id) is None


def test_serialize_reference_handles_dicts_objects_and_none():
    assert serialize_reference(None) == {}
    assert serialize_reference({"id": "a"}) == {"id": "a"}

    class WithSerialize:
        def serialize(self):
            return {"id": "from-serialize"}

    class Plain:
        def __init__(self):
            self.id = "plain"
            self._private = "hidden"

    assert serialize_reference(WithSerialize()) == {"id": "from-serialize"}
    assert serialize_reference(Plain()) == {"id": "plain"}
