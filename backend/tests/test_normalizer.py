from __future__ import annotations

from datetime import UTC, datetime

from api.core.timeutil import as_utc, to_utc
from ingestion.normalizer import (
    chunk_content,
    display_name_from_email,
    resolve_person,
    strip_html,
    strip_quoted_reply,
)


def test_strip_html_drops_markup_and_scripts():
    raw = "<div>Hello <b>team</b><script>alert('x')</script><br>Second line &amp; more</div>"
    assert strip_html(raw) == "Hello team\nSecond line & more"


def test_strip_html_handles_none_and_empty():
    assert strip_html(None) == ""
    assert strip_html("") == ""


def test_strip_quoted_reply_trims_original_message():
    body = "Latest reply here.\n-----Original Message-----\nFrom: someone\nOld content"
    assert strip_quoted_reply(body) == "Latest reply here."


def test_chunk_content_respects_window_and_overlaps():
    content = ". ".join(f"sentence number {index} about billing" for index in range(60)) + "."
    chunks = chunk_content(content, max_tokens=20, overlap_ratio=0.2)
    assert len(chunks) > 1
    assert all(len(chunk.split()) <= 30 for chunk in chunks)
    # Overlap means the tail of one chunk reappears at the head of the next.
    assert chunks[0].split(". ")[-1] in chunks[1]


def test_chunk_content_hard_splits_a_single_giant_sentence():
    content = " ".join(["token"] * 500)
    chunks = chunk_content(content, max_tokens=50, overlap_ratio=0.0)
    assert len(chunks) >= 10
    assert max(len(chunk.split()) for chunk in chunks) <= 50


def test_chunk_content_empty_is_no_chunks():
    assert chunk_content("   ") == []


def test_display_name_from_email():
    assert display_name_from_email("nivas.s@levelshift.com") == "Nivas S"
    assert display_name_from_email("deepa-v@levelshift.com") == "Deepa V"


def test_resolve_person_is_idempotent_and_case_insensitive(db_session, team):
    first = resolve_person(db_session, "New.Person@Example.com", "New Person", team.id)
    second = resolve_person(db_session, "new.person@example.com", None, team.id)
    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert first.email == "new.person@example.com"


def test_resolve_person_skips_noreply_and_invalid(db_session, team):
    assert resolve_person(db_session, "noreply@example.com", None, team.id) is None
    assert resolve_person(db_session, "not-an-email", None, team.id) is None
    assert resolve_person(db_session, None, None, team.id) is None


def test_as_utc_parses_iso_variants():
    assert as_utc("2026-08-18T10:00:00Z").tzinfo is UTC
    assert as_utc("2026-08-18T10:00:00+05:30").hour == 4
    assert as_utc(datetime(2026, 8, 18, 10, 0, 0)).tzinfo is UTC


def test_to_utc_treats_naive_as_utc():
    naive = datetime(2026, 8, 18, 10, 0, 0)
    assert to_utc(naive) == datetime(2026, 8, 18, 10, 0, 0, tzinfo=UTC)
    assert to_utc(None) is None
