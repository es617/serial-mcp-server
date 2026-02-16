"""Introspection tool definitions and handlers — list connections."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from serial_mcp_server.helpers import _ok
from serial_mcp_server.state import SerialState

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="serial.connections.list",
        description=(
            "List all open serial connections with their status, port, configuration, "
            "and timestamps. Useful for recovering connection IDs after context loss."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_connections_list(state: SerialState, _args: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for conn in state.connections.values():
        items.append(
            {
                "connection_id": conn.connection_id,
                "port": conn.port,
                "is_open": conn.ser.is_open,
                "baudrate": conn.baudrate,
                "encoding": conn.encoding,
                "opened_at": conn.opened_at,
                "last_seen_ts": conn.last_seen_ts,
            }
        )
    return _ok(
        message=f"{len(items)} connection(s).",
        connections=items,
        count=len(items),
    )


HANDLERS: dict[str, Any] = {
    "serial.connections.list": handle_connections_list,
}
