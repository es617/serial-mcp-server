"""Shared fixtures for Serial MCP handler tests."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, PropertyMock

import pytest

from serial_mcp_server.mirror import SerialBuffer
from serial_mcp_server.state import SerialConnection, SerialState


@pytest.fixture()
def serial_state():
    """Fresh SerialState instance."""
    return SerialState()


@pytest.fixture()
def mock_serial():
    """MagicMock pyserial.Serial with sensible defaults."""
    ser = MagicMock()
    ser.is_open = True
    ser.in_waiting = 0
    ser.read.return_value = b""
    ser.write.return_value = 0
    ser.read_until.return_value = b""
    type(ser).dtr = PropertyMock(return_value=True)
    type(ser).rts = PropertyMock(return_value=True)
    return ser


@pytest.fixture()
def mock_reader():
    """MagicMock ReaderThread with write_lock."""
    reader = MagicMock()
    reader.write_lock = threading.Lock()
    reader.mirror_info.return_value = None
    return reader


@pytest.fixture()
def connected_entry(serial_state, mock_serial, mock_reader):
    """SerialConnection registered in serial_state as 's1'. Returns (state, conn)."""
    buf = SerialBuffer()
    conn = SerialConnection(
        connection_id="s1",
        port="/dev/ttyUSB0",
        baudrate=115200,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=0.2,
        write_timeout=0.2,
        encoding="utf-8",
        newline="\n",
        ser=mock_serial,
        buffer=buf,
        reader=mock_reader,
    )
    serial_state.connections["s1"] = conn
    return serial_state, conn
