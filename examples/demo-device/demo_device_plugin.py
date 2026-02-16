"""Plugin for DemoDevice device."""

import json

from mcp.types import Tool

from serial_mcp_server.handlers_serial import (
    handle_read_until,
    handle_write,
)
from serial_mcp_server.helpers import _ok
from serial_mcp_server.state import SerialState

META = {
    "description": "DemoDevice device plugin — version, status, config, echo, ping, sampling, logging, auth",
    "device_name_contains": "DemoDevice",
}


async def _send_cmd(state: SerialState, connection_id: str, cmd: str, timeout_ms: int = 2000) -> str:
    """Send a command and read until the '> ' prompt. Returns the response text (without prompt)."""
    await handle_write(
        state,
        {
            "connection_id": connection_id,
            "data": cmd,
            "append_newline": True,
        },
    )
    resp = await handle_read_until(
        state,
        {
            "connection_id": connection_id,
            "delimiter": "> ",
            "timeout_ms": timeout_ms,
        },
    )
    text = resp.get("data", "")
    # Strip trailing prompt
    if text.endswith("> "):
        text = text[:-2]
    return text.strip()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="demo.version",
        description="Get DemoDevice firmware version.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.status",
        description="Get device status (state, temp, uptime, logs_enabled, authenticated) as JSON.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.ping",
        description="Ping the device (expects 'pong').",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.echo",
        description="Echo text back from the device.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "text": {"type": "string", "description": "Text to echo."},
            },
            "required": ["connection_id", "text"],
        },
    ),
    Tool(
        name="demo.uptime",
        description="Get device uptime.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.config_get",
        description="Get device configuration. Optionally pass a key to get a single value.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "key": {
                    "type": "string",
                    "description": "Optional config key (log_interval_ms, sample_rate_hz, device_name).",
                },
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.config_set",
        description="Set a device configuration value.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "key": {"type": "string", "description": "Config key to set."},
                "value": {"type": "string", "description": "Value to set."},
            },
            "required": ["connection_id", "key", "value"],
        },
    ),
    Tool(
        name="demo.sample",
        description="Collect sensor samples from the device.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "count": {"type": "integer", "description": "Number of samples to collect."},
            },
            "required": ["connection_id", "count"],
        },
    ),
    Tool(
        name="demo.log_start",
        description="Start periodic logging. Optionally specify interval in milliseconds.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "interval_ms": {
                    "type": "integer",
                    "description": "Log interval in ms (default from device config).",
                },
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.log_stop",
        description="Stop periodic logging.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.auth",
        description="Authenticate for privileged commands (secret, factory-reset).",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "password": {"type": "string", "description": "Authentication password."},
            },
            "required": ["connection_id", "password"],
        },
    ),
    Tool(
        name="demo.secret",
        description="Show secret data (requires prior authentication).",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="demo.reboot",
        description="Reboot the device.",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_version(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], "version")
    return _ok(version=text)


async def handle_status(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], "status")
    try:
        data = json.loads(text)
        return _ok(**data)
    except json.JSONDecodeError:
        return _ok(raw=text)


async def handle_ping(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], "ping")
    return _ok(response=text)


async def handle_echo(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], f"echo {args['text']}")
    return _ok(echo=text)


async def handle_uptime(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], "uptime")
    return _ok(uptime=text)


async def handle_config_get(state: SerialState, args: dict) -> dict:
    key = args.get("key", "")
    cmd = f"config get {key}".strip()
    text = await _send_cmd(state, args["connection_id"], cmd)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _ok(**data)
        return _ok(value=data)
    except json.JSONDecodeError:
        return _ok(raw=text)


async def handle_config_set(state: SerialState, args: dict) -> dict:
    cmd = f"config set {args['key']} {args['value']}"
    text = await _send_cmd(state, args["connection_id"], cmd)
    return _ok(response=text)


async def handle_sample(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], f"sample {args['count']}", timeout_ms=10000)
    return _ok(raw=text)


async def handle_log_start(state: SerialState, args: dict) -> dict:
    interval = args.get("interval_ms")
    cmd = f"log start {interval}" if interval else "log start"
    text = await _send_cmd(state, args["connection_id"], cmd)
    return _ok(response=text)


async def handle_log_stop(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], "log stop")
    return _ok(response=text)


async def handle_auth(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], f"auth {args['password']}")
    return _ok(response=text)


async def handle_secret(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], "secret")
    return _ok(secret=text)


async def handle_reboot(state: SerialState, args: dict) -> dict:
    text = await _send_cmd(state, args["connection_id"], "reboot")
    return _ok(response=text)


HANDLERS = {
    "demo.version": handle_version,
    "demo.status": handle_status,
    "demo.ping": handle_ping,
    "demo.echo": handle_echo,
    "demo.uptime": handle_uptime,
    "demo.config_get": handle_config_get,
    "demo.config_set": handle_config_set,
    "demo.sample": handle_sample,
    "demo.log_start": handle_log_start,
    "demo.log_stop": handle_log_stop,
    "demo.auth": handle_auth,
    "demo.secret": handle_secret,
    "demo.reboot": handle_reboot,
}
