"""Spec tool definitions and handlers — template, register, list, attach, read, search."""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from serial_mcp_server import specs
from serial_mcp_server.helpers import _err, _ok
from serial_mcp_server.state import SerialState

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="serial.spec.template",
        description=(
            "Return a markdown template for a new serial protocol spec. Optionally pre-fill with a device name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Device name to pre-fill in the template.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="serial.spec.register",
        description=(
            "Register a spec file in the index. Validates YAML front-matter "
            "(requires kind: serial-protocol and name). The file path can be "
            "absolute or relative to CWD."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the spec markdown file.",
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="serial.spec.list",
        description="List all registered specs with their metadata and matching hints.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="serial.spec.attach",
        description=(
            "Attach a registered spec to a connection session (in-memory only). "
            "The spec will be available via serial.spec.get for the duration of this connection. "
            "After attaching, check serial.plugin.list for a matching plugin, then present "
            "the user with their options: "
            "interact with the device using the spec (send commands, execute flows), "
            "use plugin shortcut tools if a plugin is loaded, "
            "extend an existing plugin with new tools, "
            "or create a new plugin using serial.plugin.template."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "spec_id": {"type": "string", "description": "The spec_id from serial.spec.register."},
            },
            "required": ["connection_id", "spec_id"],
        },
    ),
    Tool(
        name="serial.spec.get",
        description="Get the attached spec for a connection (returns null if none attached).",
        inputSchema={
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
            },
            "required": ["connection_id"],
        },
    ),
    Tool(
        name="serial.spec.read",
        description="Read full spec content, file path, and metadata by spec_id.",
        inputSchema={
            "type": "object",
            "properties": {
                "spec_id": {"type": "string"},
            },
            "required": ["spec_id"],
        },
    ),
    Tool(
        name="serial.spec.search",
        description=(
            "Full-text search over a spec's content. Returns matching snippets "
            "with line numbers and surrounding context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "spec_id": {"type": "string"},
                "query": {"type": "string", "description": "Search terms (space-separated)."},
                "k": {
                    "type": ["integer", "string"],
                    "description": "Max results to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["spec_id", "query"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_spec_template(_state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    device_name: str | None = args.get("device_name")
    template = specs.get_template(device_name)
    suggested_path = specs.suggest_spec_path(device_name)
    return _ok(template=template, suggested_path=str(suggested_path))


async def handle_spec_register(_state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    path = args["path"]
    try:
        entry = specs.register_spec(path)
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    except ValueError as exc:
        return _err("invalid_spec", str(exc))
    return _ok(**entry)


async def handle_spec_list(_state: SerialState, _args: dict[str, Any]) -> dict[str, Any]:
    entries = specs.list_specs()
    return _ok(specs=entries, count=len(entries))


async def handle_spec_attach(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    cid = args["connection_id"]
    spec_id = args["spec_id"]
    entry = state.get_connection(cid)
    try:
        spec_data = specs.read_spec(spec_id)
    except KeyError as exc:
        return _err("not_found", str(exc))
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    entry.spec = {
        "spec_id": spec_data["spec_id"],
        "path": spec_data["path"],
        "meta": spec_data["meta"],
    }
    return _ok(
        spec_id=spec_id,
        path=spec_data["path"],
    )


async def handle_spec_get(state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    cid = args["connection_id"]
    entry = state.get_connection(cid)
    if entry.spec is None:
        return _ok(spec=None)
    return _ok(spec=entry.spec)


async def handle_spec_read(_state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    spec_id = args["spec_id"]
    try:
        data = specs.read_spec(spec_id)
    except KeyError as exc:
        return _err("not_found", str(exc))
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    return _ok(**data)


async def handle_spec_search(_state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
    spec_id = args["spec_id"]
    query = args["query"]
    k = int(args.get("k", 10))
    try:
        results = specs.search_spec(spec_id, query, k=k)
    except KeyError as exc:
        return _err("not_found", str(exc))
    except FileNotFoundError as exc:
        return _err("not_found", str(exc))
    return _ok(results=results, count=len(results))


HANDLERS: dict[str, Any] = {
    "serial.spec.template": handle_spec_template,
    "serial.spec.register": handle_spec_register,
    "serial.spec.list": handle_spec_list,
    "serial.spec.attach": handle_spec_attach,
    "serial.spec.get": handle_spec_get,
    "serial.spec.read": handle_spec_read,
    "serial.spec.search": handle_spec_search,
}
