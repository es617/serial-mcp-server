"""Tests for serial tool handlers in serial_mcp_server.handlers_serial."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from serial_mcp_server.handlers_serial import (
    HANDLERS,
    TOOLS,
    _format_data,
    handle_close,
    handle_connection_status,
    handle_flush,
    handle_list_ports,
    handle_open,
    handle_read,
    handle_read_until,
    handle_readline,
    handle_set_dtr,
    handle_set_rts,
    handle_write,
)
from serial_mcp_server.state import SerialState


class TestToolRegistration:
    def test_all_tools_have_handlers(self):
        tool_names = {t.name for t in TOOLS}
        handler_names = set(HANDLERS.keys())
        assert tool_names == handler_names

    def test_tool_count(self):
        assert len(TOOLS) == 13


class TestListPorts:
    async def test_list_ports(self):
        state = SerialState()
        mock_port = MagicMock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.name = "ttyUSB0"
        mock_port.description = "USB Serial"
        mock_port.hwid = "USB VID:PID=1234:5678"
        mock_port.vid = 0x1234
        mock_port.pid = 0x5678
        mock_port.serial_number = "ABC123"
        mock_port.manufacturer = "TestCo"
        mock_port.product = "TestDevice"
        mock_port.location = "1-1"

        with patch(
            "serial_mcp_server.handlers_serial.serial.tools.list_ports.comports", return_value=[mock_port]
        ):
            result = await handle_list_ports(state, {})
        assert result["ok"]
        assert result["count"] == 1
        port = result["ports"][0]
        assert port["device"] == "/dev/ttyUSB0"
        assert port["vid"] == "0x1234"
        assert port["pid"] == "0x5678"

    async def test_list_ports_empty(self):
        state = SerialState()
        with patch("serial_mcp_server.handlers_serial.serial.tools.list_ports.comports", return_value=[]):
            result = await handle_list_ports(state, {})
        assert result["ok"]
        assert result["count"] == 0


class TestOpen:
    async def test_open_success(self):
        state = SerialState()
        mock_ser = MagicMock()
        mock_ser.is_open = True
        with patch("serial_mcp_server.handlers_serial.pyserial.Serial", return_value=mock_ser):
            result = await handle_open(state, {"port": "/dev/ttyUSB0"})
        assert result["ok"]
        assert "connection_id" in result
        assert result["config"]["baudrate"] == 115200

    async def test_open_invalid_parity(self):
        state = SerialState()
        result = await handle_open(state, {"port": "/dev/ttyUSB0", "parity": "X"})
        assert not result["ok"]
        assert result["error"]["code"] == "invalid_params"

    async def test_open_invalid_stopbits(self):
        state = SerialState()
        result = await handle_open(state, {"port": "/dev/ttyUSB0", "stopbits": 3})
        assert not result["ok"]
        assert result["error"]["code"] == "invalid_params"

    async def test_open_duplicate_port(self):
        state = SerialState()
        mock_ser = MagicMock()
        mock_ser.is_open = True
        with patch("serial_mcp_server.handlers_serial.pyserial.Serial", return_value=mock_ser):
            result1 = await handle_open(state, {"port": "/dev/ttyUSB0"})
        assert result1["ok"]

        result2 = await handle_open(state, {"port": "/dev/ttyUSB0"})
        assert not result2["ok"]
        assert result2["error"]["code"] == "already_open"


class TestClose:
    async def test_close(self, connected_entry):
        state, _conn = connected_entry
        result = await handle_close(state, {"connection_id": "s1"})
        assert result["ok"]
        assert result["port"] == "/dev/ttyUSB0"
        assert "s1" not in state.connections

    async def test_close_missing(self):
        state = SerialState()
        with pytest.raises(KeyError):
            await handle_close(state, {"connection_id": "nonexistent"})


class TestConnectionStatus:
    async def test_status(self, connected_entry):
        state, _conn = connected_entry
        result = await handle_connection_status(state, {"connection_id": "s1"})
        assert result["ok"]
        assert result["is_open"] is True
        assert result["config"]["baudrate"] == 115200


class TestRead:
    async def test_read_text(self, connected_entry):
        state, conn = connected_entry
        conn.ser.read.return_value = b"hello"
        result = await handle_read(state, {"connection_id": "s1"})
        assert result["ok"]
        assert result["data"] == "hello"
        assert result["n_read"] == 5
        assert result["format"] == "text"

    async def test_read_hex(self, connected_entry):
        state, conn = connected_entry
        conn.ser.read.return_value = b"\x01\x02\x03"
        result = await handle_read(state, {"connection_id": "s1", "as": "hex"})
        assert result["ok"]
        assert result["data"] == "010203"

    async def test_read_base64(self, connected_entry):
        state, conn = connected_entry
        conn.ser.read.return_value = b"\x01\x02\x03"
        result = await handle_read(state, {"connection_id": "s1", "as": "base64"})
        assert result["ok"]
        assert result["data"] == "AQID"

    async def test_read_timeout_override(self, connected_entry):
        state, conn = connected_entry
        conn.ser.read.return_value = b""
        original = conn.ser.timeout
        await handle_read(state, {"connection_id": "s1", "timeout_ms": 500})
        # Timeout should be restored
        assert conn.ser.timeout == original


class TestWrite:
    async def test_write_text(self, connected_entry):
        state, conn = connected_entry
        conn.ser.write.return_value = 5
        result = await handle_write(state, {"connection_id": "s1", "data": "hello"})
        assert result["ok"]
        assert result["bytes_written"] == 5
        conn.ser.write.assert_called_once_with(b"hello")

    async def test_write_hex(self, connected_entry):
        state, conn = connected_entry
        conn.ser.write.return_value = 3
        result = await handle_write(state, {"connection_id": "s1", "data": "010203", "as": "hex"})
        assert result["ok"]
        conn.ser.write.assert_called_once_with(b"\x01\x02\x03")

    async def test_write_invalid_hex(self, connected_entry):
        state, conn = connected_entry
        result = await handle_write(state, {"connection_id": "s1", "data": "ZZZZ", "as": "hex"})
        assert not result["ok"]
        assert result["error"]["code"] == "invalid_value"

    async def test_write_append_newline(self, connected_entry):
        state, conn = connected_entry
        conn.ser.write.return_value = 6
        result = await handle_write(state, {"connection_id": "s1", "data": "hello", "append_newline": True})
        assert result["ok"]
        conn.ser.write.assert_called_once_with(b"hello\n")


class TestReadline:
    async def test_readline(self, connected_entry):
        state, conn = connected_entry
        conn.ser.read_until.return_value = b"hello\n"
        result = await handle_readline(state, {"connection_id": "s1"})
        assert result["ok"]
        assert result["data"] == "hello\n"
        conn.ser.read_until.assert_called_once_with(b"\n", 4096)


class TestReadUntil:
    async def test_read_until_custom_delimiter(self, connected_entry):
        state, conn = connected_entry
        conn.ser.read_until.return_value = b"hello>"
        result = await handle_read_until(state, {"connection_id": "s1", "delimiter": ">"})
        assert result["ok"]
        assert result["data"] == "hello>"
        conn.ser.read_until.assert_called_once_with(b">", 4096)


class TestFlush:
    async def test_flush_both(self, connected_entry):
        state, conn = connected_entry
        result = await handle_flush(state, {"connection_id": "s1"})
        assert result["ok"]
        conn.ser.reset_input_buffer.assert_called_once()
        conn.ser.reset_output_buffer.assert_called_once()

    async def test_flush_input_only(self, connected_entry):
        state, conn = connected_entry
        result = await handle_flush(state, {"connection_id": "s1", "what": "input"})
        assert result["ok"]
        conn.ser.reset_input_buffer.assert_called_once()
        conn.ser.reset_output_buffer.assert_not_called()


class TestControlLines:
    async def test_set_dtr(self, connected_entry):
        state, _conn = connected_entry
        result = await handle_set_dtr(state, {"connection_id": "s1", "value": False})
        assert result["ok"]
        assert result["dtr"] is False

    async def test_set_rts(self, connected_entry):
        state, _conn = connected_entry
        result = await handle_set_rts(state, {"connection_id": "s1", "value": True})
        assert result["ok"]
        assert result["rts"] is True


class TestFormatData:
    def test_text(self):
        r = _format_data(b"hello", "text", "utf-8")
        assert r["data"] == "hello"
        assert r["format"] == "text"

    def test_hex(self):
        r = _format_data(b"\xab\xcd", "hex", "utf-8")
        assert r["data"] == "abcd"

    def test_base64(self):
        r = _format_data(b"\x01\x02", "base64", "utf-8")
        assert r["data"] == "AQI="

    def test_text_replace_errors(self):
        r = _format_data(b"\xff\xfe", "text", "utf-8")
        assert "\ufffd" in r["data"]
