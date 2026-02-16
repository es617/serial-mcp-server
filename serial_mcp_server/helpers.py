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

# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _ok(**kwargs: Any) -> dict[str, Any]:
    return {"ok": True, **kwargs}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _result_text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, default=str))]
