"""In-memory state for serial connections."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import serial as pyserial

from serial_mcp_server.mirror import ReaderThread, SerialBuffer

logger = logging.getLogger("serial_mcp_server")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SerialConnection:
    """A managed serial port connection."""

    connection_id: str
    port: str
    baudrate: int
    bytesize: int
    parity: str
    stopbits: float
    timeout: float  # seconds
    write_timeout: float  # seconds
    encoding: str
    newline: str
    ser: pyserial.Serial
    buffer: SerialBuffer = field(default_factory=SerialBuffer)
    reader: ReaderThread | None = None
    opened_at: float = field(default_factory=time.time)
    last_seen_ts: float = field(default_factory=time.time)
    spec: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class SerialState:
    """Central mutable state shared by all tool handlers."""

    def __init__(self, max_connections: int = 10) -> None:
        self.connections: dict[str, SerialConnection] = {}
        self.max_connections = max_connections

    def generate_id(self) -> str:
        return f"s{uuid.uuid4().hex[:8]}"

    def get_connection(self, connection_id: str) -> SerialConnection:
        if connection_id not in self.connections:
            raise KeyError(
                f"Unknown connection_id: {connection_id}. "
                "Call serial.connections.list to see active connections."
            )
        return self.connections[connection_id]

    def add_connection(self, conn: SerialConnection) -> None:
        if len(self.connections) >= self.max_connections:
            raise RuntimeError(
                f"Maximum connections ({self.max_connections}) reached. "
                "Close a connection first. Set SERIAL_MCP_MAX_CONNECTIONS to adjust."
            )
        self.connections[conn.connection_id] = conn

    def remove_connection(self, connection_id: str) -> SerialConnection:
        if connection_id not in self.connections:
            raise KeyError(
                f"Unknown connection_id: {connection_id}. "
                "Call serial.connections.list to see active connections."
            )
        return self.connections.pop(connection_id)

    def close_connection(self, connection_id: str) -> dict[str, Any]:
        """Close and remove a connection. Idempotent on already-closed ports."""
        conn = self.remove_connection(connection_id)
        # Stop the background reader first (cleans up PTY if mirror is active).
        if conn.reader is not None:
            try:
                conn.reader.stop()
            except Exception:
                pass
        try:
            if conn.ser.is_open:
                conn.ser.close()
        except Exception:
            pass
        return {"connection_id": connection_id, "port": conn.port}

    async def shutdown(self) -> None:
        """Stop all readers and close all open serial ports."""
        for conn in list(self.connections.values()):
            if conn.reader is not None:
                try:
                    conn.reader.stop()
                except Exception:
                    pass
            try:
                if conn.ser.is_open:
                    conn.ser.close()
            except Exception:
                pass
        self.connections.clear()
