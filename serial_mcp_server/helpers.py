"""Shared helpers, configuration, and response builders for handler modules."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from mcp.types import TextContent

logger = logging.getLogger("serial_mcp_server")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_CONNECTIONS = int(os.environ.get("SERIAL_MCP_MAX_CONNECTIONS", "10"))

# PTY mirror: "off" (default), "ro" (read-only), or "rw" (read-write).
MIRROR_PTY = os.environ.get("SERIAL_MCP_MIRROR", "off").strip().lower()
if MIRROR_PTY not in ("off", "ro", "rw"):
    logger.warning("Invalid SERIAL_MCP_MIRROR=%r, defaulting to 'off'.", MIRROR_PTY)
    MIRROR_PTY = "off"
if MIRROR_PTY != "off" and os.name == "nt":
    logger.warning("PTY mirror is not supported on Windows. Ignoring SERIAL_MCP_MIRROR=%r.", MIRROR_PTY)
    MIRROR_PTY = "off"
MIRROR_PTY_LINK: str | None = os.environ.get("SERIAL_MCP_MIRROR_LINK", "").strip() or None
if MIRROR_PTY != "off" and MIRROR_PTY_LINK is None:
    MIRROR_PTY_LINK = "/tmp/serial-mcp"

# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _ok(**kwargs: Any) -> dict[str, Any]:
    return {"ok": True, **kwargs}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _result_text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, default=str))]
