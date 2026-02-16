"""Serial tool definitions and handlers — list ports, open, read, write, control lines."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import serial as pyserial
import serial.tools.list_ports
from mcp.types import Tool

from serial_mcp_server.helpers import MIRROR_PTY, MIRROR_PTY_LINK, _err, _ok
from serial_mcp_server.mirror import SerialBuffer, create_reader
from serial_mcp_server.state import SerialConnection, SerialState

logger = logging.getLogger("serial_mcp_server")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARITY_MAP = {
    "N": pyserial.PARITY_NONE,
    "E": pyserial.PARITY_EVEN,
    "O": pyserial.PARITY_ODD,
    "M": pyserial.PARITY_MARK,
    "S": pyserial.PARITY_SPACE,
}

STOPBITS_MAP = {
    1: pyserial.STOPBITS_ONE,
    1.5: pyserial.STOPBITS_ONE_POINT_FIVE,
    2: pyserial.STOPBITS_TWO,
}

BYTESIZE_MAP = {
    5: pyserial.FIVEBITS,
    6: pyserial.SIXBITS,
    7: pyserial.SEVENBITS,
    8: pyserial.EIGHTBITS,
}

# Maximum read size to prevent accidental huge allocations.
MAX_READ_BYTES = 1_048_576  # 1 MiB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_data(raw: bytes, fmt: str, encoding: str) -> dict[str, Any]:
    """Format raw bytes according to *fmt* ("text", "hex", or "base64")."""
    if fmt == "hex":
        return {"data": raw.hex(), "format": "hex"}
    if fmt == "base64":
        return {"data": base64.b64encode(raw).decode("ascii"), "format": "base64"}
    # default: text
    return {"data": raw.decode(encoding, errors="replace"), "format": "text", "encoding": encoding}


def _conn_config(conn: SerialConnection) -> dict[str, Any]:
    """Return a dict describing the connection's serial configuration."""
    return {
        "port": conn.port,
        "baudrate": conn.baudrate,
        "bytesize": conn.bytesize,
        "parity": conn.parity,
        "stopbits": conn.stopbits,
        "timeout_ms": round(conn.timeout * 1000),
        "write_timeout_ms": round(conn.write_timeout * 1000),
        "encoding": conn.encoding,
        "newline": repr(conn.newline),
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # ---- 1. list_ports ----
    Tool(
        name="serial.list_ports",
        description="List available serial ports on the system.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    # ---- 2. open ----
    Tool(
        name="serial.open",
        description=(
            "Open a serial port connection. Returns a connection_id for use with other serial tools. "
            "The port stays open across tool calls until serial.close is called or the server exits. "
            "Defaults are 115200 baud, 8N1, \\r\\n line terminator — the most common settings. "
            "If you don't know the correct settings, check for a protocol spec with serial.spec.list "
            "or ask the user. Wrong baud rate is the most common cause of garbled data. "
            "After opening, do a serial.read to check for any buffered data — many devices "
            "send a boot banner, prompt, or status message on connection."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "port": {"type": "string", "description": "Serial port path (e.g. /dev/ttyUSB0, COM3)."},
                "baudrate": {
                    "type": "integer",
                    "default": 115200,
                    "description": "Baud rate (default 115200). Common values: 9600, 19200, 38400, 57600, 115200.",
                },
                "bytesize": {
                    "type": "integer",
                    "enum": [5, 6, 7, 8],
                    "default": 8,
                    "description": "Data bits (default 8).",
                },
                "parity": {
                    "type": "string",
                    "enum": ["N", "E", "O", "M", "S"],
                    "default": "N",
                    "description": "Parity: N(one), E(ven), O(dd), M(ark), S(pace). Default N.",
                },
                "stopbits": {
                    "type": "number",
                    "enum": [1, 1.5, 2],
                    "default": 1,
                    "description": "Stop bits (default 1).",
                },
                "timeout_ms": {
                    "type": "integer",
                    "default": 200,
                    "description": "Read timeout in milliseconds (default 200).",
                },
                "write_timeout_ms": {
                    "type": "integer",
                    "default": 200,
                    "description": "Write timeout in milliseconds (default 200).",
                },
                "exclusive": {
                    "type": "boolean",
                    "description": "Request exclusive access (platform-dependent, ignored if unsupported).",
                },
                "encoding": {
                    "type": "string",
                    "default": "utf-8",
                    "description": "Default text encoding for this connection (default utf-8).",
                },
                "newline": {
                    "type": "string",
                    "default": "\\r\\n",
                    "description": "Default line terminator for readline and append_newline (default \\r\\n).",
                },
            },
            "required": ["port"],
        },
    ),
    # ---- 3. close ----
    Tool(
        name="serial.close",
        description="Close a serial port connection and release the port.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The connection_id from serial.open."},
            },
            "required": ["connection_id"],
        },
    ),
    # ---- 4. connection_status ----
    Tool(
        name="serial.connection_status",
        description="Check whether a serial connection is still open and return its configuration.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The connection_id from serial.open."},
            },
            "required": ["connection_id"],
        },
    ),
    # ---- 5. read ----
    Tool(
        name="serial.read",
        description=(
            "Read up to nbytes from a serial port. Returns immediately with whatever data "
            "is available within the timeout. Use serial.readline or serial.read_until for "
            "line-oriented reads."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "nbytes": {
                    "type": "integer",
                    "default": 256,
                    "description": "Maximum bytes to read (default 256).",
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Override read timeout for this call only (milliseconds).",
                },
                "as": {
                    "type": "string",
                    "enum": ["text", "hex", "base64"],
                    "default": "text",
                    "description": "Output format: text (decoded string), hex, or base64. Default text.",
                },
            },
            "required": ["connection_id"],
        },
    ),
    # ---- 6. write ----
    Tool(
        name="serial.write",
        description="Write data to a serial port. Returns the number of bytes written.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "data": {"type": "string", "description": "Data to write."},
                "encoding": {
                    "type": "string",
                    "description": "Override encoding for this call (defaults to connection encoding).",
                },
                "append_newline": {
                    "type": "boolean",
                    "default": False,
                    "description": "Append the connection's newline character after data (default false).",
                },
                "newline": {
                    "type": "string",
                    "description": "Override newline for append_newline (defaults to connection newline).",
                },
                "as": {
                    "type": "string",
                    "enum": ["text", "hex", "base64"],
                    "default": "text",
                    "description": "How to interpret 'data': text (encode with encoding), hex, or base64.",
                },
            },
            "required": ["connection_id", "data"],
        },
    ),
    # ---- 7. readline ----
    Tool(
        name="serial.readline",
        description=(
            "Read a line from the serial port (reads until the newline character is received "
            "or max_bytes is reached). Uses the connection's newline setting by default."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "timeout_ms": {"type": "integer", "description": "Override read timeout (milliseconds)."},
                "max_bytes": {
                    "type": "integer",
                    "default": 4096,
                    "description": "Maximum bytes to read (default 4096).",
                },
                "newline": {
                    "type": "string",
                    "description": "Override line terminator (defaults to connection newline).",
                },
                "as": {
                    "type": "string",
                    "enum": ["text", "hex", "base64"],
                    "default": "text",
                    "description": "Output format (default text).",
                },
            },
            "required": ["connection_id"],
        },
    ),
    # ---- 8. read_until ----
    Tool(
        name="serial.read_until",
        description=(
            "Read from the serial port until a delimiter string is received or max_bytes is reached."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "delimiter": {
                    "type": "string",
                    "default": "\\n",
                    "description": "Delimiter to read until (default \\n).",
                },
                "timeout_ms": {"type": "integer", "description": "Override read timeout (milliseconds)."},
                "max_bytes": {
                    "type": "integer",
                    "default": 4096,
                    "description": "Maximum bytes to read (default 4096).",
                },
                "as": {
                    "type": "string",
                    "enum": ["text", "hex", "base64"],
                    "default": "text",
                    "description": "Output format (default text).",
                },
            },
            "required": ["connection_id"],
        },
    ),
    # ---- 9. flush ----
    Tool(
        name="serial.flush",
        description="Flush serial port buffers (discard pending input/output data).",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "what": {
                    "type": "string",
                    "enum": ["input", "output", "both"],
                    "default": "both",
                    "description": "Which buffer to flush: input, output, or both (default both).",
                },
            },
            "required": ["connection_id"],
        },
    ),
    # ---- 10. set_dtr ----
    Tool(
        name="serial.set_dtr",
        description="Set the DTR (Data Terminal Ready) control line. Usage is device-specific — check the protocol spec or ask the user.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "value": {"type": "boolean", "description": "True = high, False = low."},
            },
            "required": ["connection_id", "value"],
        },
    ),
    # ---- 11. set_rts ----
    Tool(
        name="serial.set_rts",
        description="Set the RTS (Request To Send) control line. Usage is device-specific — check the protocol spec or ask the user.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "value": {"type": "boolean", "description": "True = high, False = low."},
            },
            "required": ["connection_id", "value"],
        },
    ),
    # ---- 12. pulse_dtr ----
    Tool(
        name="serial.pulse_dtr",
        description=(
            "Pulse the DTR line: sets low, waits duration_ms, then sets high. "
            "Commonly used to reset microcontrollers (e.g. Arduino, ESP32). "
            "Check the protocol spec or ask the user before pulsing — effect is device-specific."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "duration_ms": {
                    "type": "integer",
                    "default": 100,
                    "description": "Pulse duration in milliseconds (default 100).",
                },
            },
            "required": ["connection_id"],
        },
    ),
    # ---- 13. pulse_rts ----
    Tool(
        name="serial.pulse_rts",
        description=(
            "Pulse the RTS line: sets low, waits duration_ms, then sets high. "
            "Some devices use RTS to enter bootloader mode. "
            "Check the protocol spec or ask the user before pulsing — effect is device-specific."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "duration_ms": {
                    "type": "integer",
                    "default": 100,
                    "description": "Pulse duration in milliseconds (default 100).",
                },
            },
            "required": ["connection_id"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_list_ports(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    ports = await asyncio.to_thread(serial.tools.list_ports.comports)
    port_list = []
    for p in sorted(ports, key=lambda x: x.device):
        info: dict[str, Any] = {"device": p.device, "description": p.description, "hwid": p.hwid}
        if p.name:
            info["name"] = p.name
        if p.vid is not None:
            info["vid"] = f"0x{p.vid:04X}"
        if p.pid is not None:
            info["pid"] = f"0x{p.pid:04X}"
        if p.serial_number:
            info["serial_number"] = p.serial_number
        if p.manufacturer:
            info["manufacturer"] = p.manufacturer
        if p.product:
            info["product"] = p.product
        if p.location:
            info["location"] = p.location
        port_list.append(info)
    return _ok(
        message=f"Found {len(port_list)} serial port(s).",
        ports=port_list,
        count=len(port_list),
    )


async def handle_open(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    port = args["port"]
    baudrate = args.get("baudrate", 115200)
    bytesize = args.get("bytesize", 8)
    parity = args.get("parity", "N")
    stopbits = args.get("stopbits", 1)
    timeout_ms = args.get("timeout_ms", 200)
    write_timeout_ms = args.get("write_timeout_ms", 200)
    exclusive = args.get("exclusive")
    encoding = args.get("encoding", "utf-8")
    newline = args.get("newline", "\r\n")

    # Validate parameters
    if parity not in PARITY_MAP:
        return _err("invalid_params", f"Invalid parity '{parity}'. Must be one of: N, E, O, M, S.")
    if stopbits not in STOPBITS_MAP:
        return _err("invalid_params", f"Invalid stopbits '{stopbits}'. Must be one of: 1, 1.5, 2.")
    if bytesize not in BYTESIZE_MAP:
        return _err("invalid_params", f"Invalid bytesize '{bytesize}'. Must be one of: 5, 6, 7, 8.")
    if timeout_ms < 0 or write_timeout_ms < 0:
        return _err("invalid_params", "Timeouts must be non-negative.")

    # Check for duplicate port
    for conn in state.connections.values():
        if conn.port == port and conn.ser.is_open:
            return _err(
                "already_open",
                f"Port {port} is already open as connection {conn.connection_id}.",
            )

    timeout_s = timeout_ms / 1000.0
    write_timeout_s = write_timeout_ms / 1000.0

    kwargs: dict[str, Any] = {
        "port": port,
        "baudrate": baudrate,
        "bytesize": BYTESIZE_MAP[bytesize],
        "parity": PARITY_MAP[parity],
        "stopbits": STOPBITS_MAP[stopbits],
        "timeout": timeout_s,
        "write_timeout": write_timeout_s,
    }
    if exclusive is not None:
        kwargs["exclusive"] = exclusive

    ser = await asyncio.to_thread(pyserial.Serial, **kwargs)

    connection_id = state.generate_id()
    buf = SerialBuffer()
    reader = create_reader(ser, buf, MIRROR_PTY, MIRROR_PTY_LINK)
    reader.start()

    conn = SerialConnection(
        connection_id=connection_id,
        port=port,
        baudrate=baudrate,
        bytesize=bytesize,
        parity=parity,
        stopbits=stopbits,
        timeout=timeout_s,
        write_timeout=write_timeout_s,
        encoding=encoding,
        newline=newline,
        ser=ser,
        buffer=buf,
        reader=reader,
    )
    try:
        state.add_connection(conn)
    except Exception:
        reader.stop()
        ser.close()
        raise

    result = _ok(
        message=f"Opened {port} at {baudrate} baud.",
        connection_id=connection_id,
        config=_conn_config(conn),
    )
    mirror = reader.mirror_info()
    if mirror is not None:
        result["mirror"] = mirror
    return result


async def handle_close(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    connection_id = args["connection_id"]
    info = state.close_connection(connection_id)
    return _ok(message=f"Closed {info['port']}.", **info)


async def handle_connection_status(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    is_open = conn.ser.is_open
    result: dict[str, Any] = {
        "connection_id": conn.connection_id,
        "is_open": is_open,
        "config": _conn_config(conn),
        "opened_at": conn.opened_at,
        "last_seen_ts": conn.last_seen_ts,
        "buffered_bytes": conn.buffer.available,
    }
    if conn.reader is not None:
        mirror = conn.reader.mirror_info()
        if mirror is not None:
            result["mirror"] = mirror
    return _ok(message=f"{conn.port} is {'open' if is_open else 'closed'}.", **result)


async def handle_read(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    nbytes = min(args.get("nbytes", 256), MAX_READ_BYTES)
    fmt = args.get("as", "text")
    timeout_ms = args.get("timeout_ms")
    timeout_s = timeout_ms / 1000.0 if timeout_ms is not None else conn.timeout

    raw = await asyncio.to_thread(conn.buffer.read, nbytes, timeout_s)

    conn.last_seen_ts = time.time()
    formatted = _format_data(raw, fmt, conn.encoding)
    return _ok(
        message=f"Read {len(raw)} byte(s) from {conn.port}.",
        n_read=len(raw),
        **formatted,
    )


async def handle_write(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    data_str = args["data"]
    fmt = args.get("as", "text")
    encoding = args.get("encoding", conn.encoding)
    append_newline = args.get("append_newline", False)
    newline = args.get("newline", conn.newline)

    # Convert to bytes based on format
    if fmt == "hex":
        try:
            payload = bytes.fromhex(data_str)
        except ValueError:
            return _err("invalid_value", "data is not valid hex.")
    elif fmt == "base64":
        try:
            payload = base64.b64decode(data_str)
        except Exception:
            return _err("invalid_value", "data is not valid base64.")
    else:
        payload = data_str.encode(encoding, errors="replace")

    if append_newline:
        payload += newline.encode(encoding, errors="replace")

    # Use the reader's write_lock to prevent interleaving with PTY→serial
    # forwarding in rw mirror mode.  Acquire via to_thread to avoid blocking
    # the event loop if the mirror thread is mid-write.
    lock = conn.reader.write_lock if conn.reader is not None else None

    def _locked_write() -> int:
        if lock is not None:
            lock.acquire()
        try:
            n = conn.ser.write(payload)
            conn.ser.flush()
            return n
        finally:
            if lock is not None:
                lock.release()

    n_written = await asyncio.to_thread(_locked_write)

    conn.last_seen_ts = time.time()
    return _ok(
        message=f"Wrote {n_written} byte(s) to {conn.port}.",
        bytes_written=n_written,
    )


async def handle_readline(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    max_bytes = min(args.get("max_bytes", 4096), MAX_READ_BYTES)
    fmt = args.get("as", "text")
    timeout_ms = args.get("timeout_ms")
    newline = args.get("newline", conn.newline)
    expected = newline.encode(conn.encoding, errors="replace")
    timeout_s = timeout_ms / 1000.0 if timeout_ms is not None else conn.timeout

    raw = await asyncio.to_thread(conn.buffer.read_until, expected, max_bytes, timeout_s)

    conn.last_seen_ts = time.time()
    formatted = _format_data(raw, fmt, conn.encoding)
    return _ok(
        message=f"Read {len(raw)} byte(s) from {conn.port}.",
        n_read=len(raw),
        **formatted,
    )


async def handle_read_until(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    delimiter = args.get("delimiter", "\n")
    max_bytes = min(args.get("max_bytes", 4096), MAX_READ_BYTES)
    fmt = args.get("as", "text")
    timeout_ms = args.get("timeout_ms")
    expected = delimiter.encode(conn.encoding, errors="replace")
    timeout_s = timeout_ms / 1000.0 if timeout_ms is not None else conn.timeout

    raw = await asyncio.to_thread(conn.buffer.read_until, expected, max_bytes, timeout_s)

    conn.last_seen_ts = time.time()
    formatted = _format_data(raw, fmt, conn.encoding)
    return _ok(
        message=f"Read {len(raw)} byte(s) from {conn.port}.",
        n_read=len(raw),
        **formatted,
    )


async def handle_flush(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    what = args.get("what", "both")

    if what in ("input", "both"):
        await asyncio.to_thread(conn.ser.reset_input_buffer)
        conn.buffer.clear()
    if what in ("output", "both"):
        await asyncio.to_thread(conn.ser.reset_output_buffer)

    conn.last_seen_ts = time.time()
    return _ok(message=f"Flushed {what} buffer(s) on {conn.port}.")


async def handle_set_dtr(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    value = bool(args["value"])
    conn.ser.dtr = value
    conn.last_seen_ts = time.time()
    return _ok(
        message=f"DTR {'high' if value else 'low'} on {conn.port}.",
        dtr=value,
    )


async def handle_set_rts(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    value = bool(args["value"])
    conn.ser.rts = value
    conn.last_seen_ts = time.time()
    return _ok(
        message=f"RTS {'high' if value else 'low'} on {conn.port}.",
        rts=value,
    )


_MAX_PULSE_MS = 10_000


async def handle_pulse_dtr(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    duration_ms = min(args.get("duration_ms", 100), _MAX_PULSE_MS)
    conn.ser.dtr = False
    await asyncio.sleep(duration_ms / 1000.0)
    conn.ser.dtr = True
    conn.last_seen_ts = time.time()
    return _ok(message=f"Pulsed DTR low for {duration_ms}ms on {conn.port}.", duration_ms=duration_ms)


async def handle_pulse_rts(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    conn = state.get_connection(args["connection_id"])
    duration_ms = min(args.get("duration_ms", 100), _MAX_PULSE_MS)
    conn.ser.rts = False
    await asyncio.sleep(duration_ms / 1000.0)
    conn.ser.rts = True
    conn.last_seen_ts = time.time()
    return _ok(message=f"Pulsed RTS low for {duration_ms}ms on {conn.port}.", duration_ms=duration_ms)


# ---------------------------------------------------------------------------
# Handler map
# ---------------------------------------------------------------------------

HANDLERS: dict[str, Any] = {
    "serial.list_ports": handle_list_ports,
    "serial.open": handle_open,
    "serial.close": handle_close,
    "serial.connection_status": handle_connection_status,
    "serial.read": handle_read,
    "serial.write": handle_write,
    "serial.readline": handle_readline,
    "serial.read_until": handle_read_until,
    "serial.flush": handle_flush,
    "serial.set_dtr": handle_set_dtr,
    "serial.set_rts": handle_set_rts,
    "serial.pulse_dtr": handle_pulse_dtr,
    "serial.pulse_rts": handle_pulse_rts,
}
