"""The MCP transport itself: what a client actually sees on the wire.

Needs the SDK, so the whole module skips without it -- the same arrangement as
test_bot_transport.py. The tool logic is covered SDK-free in test_mcp.py.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp", reason="needs requirements-mcp.txt")

from mcp_server import tools  # noqa: E402
from mcp_server.app import INSTRUCTIONS, build_server  # noqa: E402


def _published_tools():
    return asyncio.run(build_server().list_tools())


def test_every_hive_tool_reaches_the_wire():
    published = {tool.name for tool in _published_tools()}
    assert published == {spec.name for spec in tools.TOOLS}


def test_published_schemas_name_their_real_arguments():
    """Regression: a **kwargs wrapper published six tools all taking `kwargs`.

    The handshake still succeeded and the tools still listed -- every call just
    failed validation, which is why this asserts on the schema and not on a
    successful call.
    """
    schemas = {tool.name: tool.inputSchema for tool in _published_tools()}

    assert list(schemas["hive_prior_art"]["properties"]) == ["problem"]
    assert schemas["hive_prior_art"]["required"] == ["problem"]
    assert list(schemas["hive_blast_radius"]["properties"]) == ["target"]
    assert list(schemas["hive_area_briefing"]["properties"]) == ["area"]
    assert list(schemas["hive_who_knows"]["properties"]) == ["topic"]
    # context is optional; question is not.
    assert set(schemas["hive_raise_request"]["properties"]) == {"question", "context"}
    assert schemas["hive_raise_request"]["required"] == ["question"]
    assert "kwargs" not in {
        name for schema in schemas.values() for name in schema.get("properties", {})
    }


def test_descriptions_survive_registration():
    published = {tool.name: tool.description for tool in _published_tools()}
    for spec in tools.TOOLS:
        assert published[spec.name] == spec.description


def test_server_instructions_tell_claude_when_to_reach_for_hive():
    # The instructions are the only thing steering unprompted use, so assert the
    # trigger for each headline scenario actually made it in.
    for trigger in ("hive_prior_art", "hive_blast_radius", "hive_area_briefing"):
        assert trigger in INSTRUCTIONS
    assert "read-only" in INSTRUCTIONS.lower()


def test_a_raising_tool_answers_instead_of_breaking_the_protocol(monkeypatch):
    """A tool exception must reach the model as text, not a transport error."""

    def explode(problem: str) -> str:
        raise RuntimeError("chroma is unreachable")

    monkeypatch.setattr(
        tools,
        "TOOLS",
        [tools.ToolSpec("hive_prior_art", "x" * 90, tools._safe(explode))],
    )
    server = build_server()
    result = asyncio.run(server.call_tool("hive_prior_art", {"problem": "anything"}))

    rendered = str(result)
    assert "chroma is unreachable" in rendered
    assert "Nothing was changed" in rendered
