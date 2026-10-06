"""Launcher for Hive's MCP server.

    python scripts/hive_mcp.py

Exists so the editor config never has to set PYTHONPATH or a working directory:
the backend package root is resolved from this file's own location, so the
server starts identically from any cwd. Everything else lives in
backend/mcp_server/.
"""

from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mcp_server.app import main  # noqa: E402  - path bootstrap must run first

if __name__ == "__main__":
    main()
