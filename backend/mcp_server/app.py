"""MCP transport for Hive. The only module that imports the MCP SDK.

    python -m mcp_server            # speaks MCP over stdio

Claude (in VS Code, or the Claude Code CLI) spawns this as a subprocess and
talks JSON-RPC over stdin/stdout. Every decision lives in mcp_server/tools.py,
which holds no SDK import -- the same split as bot/handlers.py and bot/app.py,
for the same reason: the surface stays testable without the SDK installed.

Two rules this file exists to enforce:

  * stdout belongs to the protocol. Anything printed there corrupts the JSON-RPC
    stream and the client drops the connection, so logging goes to stderr.
  * a tool must not raise. An exception becomes a protocol error the model
    cannot read; a sentence explaining what broke is something it can act on.
"""

from __future__ import annotations

import logging
import sys

from api.core.config import get_settings
from api.core.db import init_db
from mcp_server import tools

logger = logging.getLogger("hive.mcp")

INSTRUCTIONS = """Hive is this team's institutional memory, derived from their real work trail:
commits, pull requests, reviews, and questions colleagues have already answered.

Reach for it while coding, not just when asked about it:
  * before debugging an error from scratch -> hive_prior_art
  * before changing a shared service -> hive_blast_radius
  * when opening code you have not worked in -> hive_area_briefing
  * when you need a person rather than an answer -> hive_who_knows

Hive is read-only over the team's work; hive_raise_request is the single
exception and records a gap for a human to answer. Everything it returns is
retrieved evidence with a named author and a commit or PR reference — cite that
provenance when you pass it on, and never present a retrieved change as a
verified fix without reading it first. When Hive says it has no evidence, that
is a real gap in what the team has written down, not a reason to guess."""


def build_server():
    """Wire every ToolSpec onto a FastMCP server.

    Handlers are registered as-is: FastMCP derives each tool's input schema from
    the function signature, so anything that wraps them has to preserve it.
    tools._safe uses functools.wraps for exactly that reason, and already turns
    a raise into a readable sentence — there is nothing left for this layer to do
    but name the tool and hand it over.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(name="hive", instructions=INSTRUCTIONS)
    for spec in tools.TOOLS:
        server.tool(name=spec.name, description=spec.description)(spec.handler)
    return server


def main() -> None:
    settings = get_settings()
    # stderr: stdout is the JSON-RPC channel and must carry nothing else.
    logging.basicConfig(level=settings.log_level.upper(), stream=sys.stderr)

    if settings.auto_create_schema:
        init_db()

    # Must happen before the event loop starts -- see tools.warm_providers.
    tools.warm_providers()

    try:
        print(tools.server_banner(), file=sys.stderr)
    except Exception:  # noqa: BLE001 - a banner must never stop the server booting
        logger.warning("could not resolve the local identity", exc_info=True)

    try:
        build_server().run(transport="stdio")
    except ImportError as exc:  # pragma: no cover - optional transport dependency
        raise SystemExit(
            "The Hive MCP server needs the MCP SDK:\n"
            "    pip install -r backend/requirements-mcp.txt\n"
            f"(import failed: {exc})"
        ) from exc


if __name__ == "__main__":
    main()
