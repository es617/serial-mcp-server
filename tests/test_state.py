"""Unit tests for serial_mcp_server.state."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from serial_mcp_server.state import SerialConnection, SerialState


class TestSerialState:
    def test_generate_id(self):
        state = SerialState()
        cid = state.generate_id()
        assert cid.startswith("s")
        assert len(cid) == 9  # "s" + 8 hex chars

    def test_add_and_get_connection(self):
        state = SerialState()
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
            ser=MagicMock(),
        )
        state.add_connection(conn)
        assert state.get_connection("s1") is conn

    def test_get_connection_missing_raises(self):
        state = SerialState()
        with pytest.raises(KeyError, match="Unknown connection_id"):
            state.get_connection("nonexistent")

    def test_add_connection_limit(self):
        state = SerialState(max_connections=1)
        conn1 = SerialConnection(
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
            ser=MagicMock(),
        )
        state.add_connection(conn1)

        conn2 = SerialConnection(
            connection_id="s2",
            port="/dev/ttyUSB1",
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=0.2,
            write_timeout=0.2,
            encoding="utf-8",
            newline="\n",
            ser=MagicMock(),
        )
        with pytest.raises(RuntimeError, match="Maximum connections"):
            state.add_connection(conn2)

    def test_remove_connection(self):
        state = SerialState()
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
            ser=MagicMock(),
        )
        state.add_connection(conn)
        removed = state.remove_connection("s1")
        assert removed is conn
        assert "s1" not in state.connections

    def test_remove_connection_missing_raises(self):
        state = SerialState()
        with pytest.raises(KeyError, match="Unknown connection_id"):
            state.remove_connection("nonexistent")

    def test_close_connection(self):
        mock_ser = MagicMock()
        mock_ser.is_open = True
        state = SerialState()
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
            ser=mock_ser,
        )
        state.add_connection(conn)
        info = state.close_connection("s1")
        assert info["port"] == "/dev/ttyUSB0"
        mock_ser.close.assert_called_once()
        assert "s1" not in state.connections

    async def test_shutdown_closes_all(self):
        mock_ser1 = MagicMock()
        mock_ser1.is_open = True
        mock_ser2 = MagicMock()
        mock_ser2.is_open = True
        state = SerialState()
        for cid, ser in [("s1", mock_ser1), ("s2", mock_ser2)]:
            conn = SerialConnection(
                connection_id=cid,
                port=f"/dev/tty{cid}",
                baudrate=115200,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=0.2,
                write_timeout=0.2,
                encoding="utf-8",
                newline="\n",
                ser=ser,
            )
            state.add_connection(conn)
        await state.shutdown()
        mock_ser1.close.assert_called_once()
        mock_ser2.close.assert_called_once()
        assert len(state.connections) == 0


class TestSerialConnection:
    def test_defaults(self):
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
            ser=MagicMock(),
        )
        assert conn.opened_at > 0
        assert conn.last_seen_ts > 0
