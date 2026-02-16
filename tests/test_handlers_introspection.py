"""Tests for introspection tools: serial.connections.list."""

from __future__ import annotations

from serial_mcp_server.handlers_introspection import (
    HANDLERS,
    TOOLS,
    handle_connections_list,
)
from serial_mcp_server.state import SerialState


class TestToolRegistration:
    def test_all_tools_have_handlers(self):
        tool_names = {t.name for t in TOOLS}
        handler_names = set(HANDLERS.keys())
        assert tool_names == handler_names


class TestConnectionsList:
    async def test_empty(self):
        state = SerialState()
        result = await handle_connections_list(state, {})
        assert result["ok"]
        assert result["count"] == 0

    async def test_with_connection(self, connected_entry):
        state, conn = connected_entry
        result = await handle_connections_list(state, {})
        assert result["ok"]
        assert result["count"] == 1
        item = result["connections"][0]
        assert item["connection_id"] == "s1"
        assert item["port"] == "/dev/ttyUSB0"
        assert item["is_open"] is True
        assert item["baudrate"] == 115200
