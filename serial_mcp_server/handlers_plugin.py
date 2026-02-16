"""Plugin management tool definitions and handler factory.

No module-level globals for manager/server — ``make_handlers`` returns
closures that capture them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import Tool

from serial_mcp_server.helpers import _err, _ok
from serial_mcp_server.plugins import PluginManager
from serial_mcp_server.state import SerialState


def _plugin_template(device_name: str | None = None) -> str:
    name = device_name or "my_device"
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f'''"""Plugin for {name}."""

from mcp.types import Tool

from serial_mcp_server.helpers import _ok, _err  # _ok(key=val) / _err("code", "message")
from serial_mcp_server.state import SerialState

# Import core handlers to interact with the device.
# IMPORTANT: always use these instead of conn.ser directly — a background
# thread owns the serial port for reads, and writes need a lock.
from serial_mcp_server.handlers_serial import (
    handle_write,      # send data to the device
    handle_read,       # read raw bytes
    handle_readline,   # read one line (up to newline)
    handle_read_until, # read until a delimiter string
)

# Optional metadata — helps the agent match this plugin to a device.
# All fields are optional. Use what makes sense for your device.
META = {{
    "description": "{name} plugin",
    # "device_name_contains": "{name}",
}}

TOOLS = [
    Tool(
        name="{slug}.example",
        description="Example tool — replace with real functionality.",
        inputSchema={{
            "type": "object",
            "properties": {{
                "connection_id": {{"type": "string"}},
            }},
            "required": ["connection_id"],
        }},
    ),
]


async def handle_example(state: SerialState, args: dict) -> dict:
    connection_id = args["connection_id"]
    # Send a command using handle_write + handle_read_until:
    #   await handle_write(state, {{
    #       "connection_id": connection_id,
    #       "data": "COMMAND",
    #       "append_newline": True,
    #   }})
    #   resp = await handle_read_until(state, {{
    #       "connection_id": connection_id,
    #       "delimiter": "> ",
    #       "timeout_ms": 2000,
    #   }})
    #   text = resp["data"]
    #
    # Return errors with: return _err("error_code", "Human-readable message")
    # Return success with: return _ok(key1=val1, key2=val2)
    return _ok(message="Hello from {slug} plugin!")


HANDLERS = {{
    "{slug}.example": handle_example,
}}
'''


def _suggest_plugin_path(plugins_dir: Path, device_name: str | None = None) -> Path:
    name = device_name or "my_device"
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return plugins_dir / f"{slug}.py"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="serial.plugin.list",
        description=(
            "List loaded plugins with their tool names and metadata. "
            "Each plugin may include a 'meta' dict with matching hints like "
            "device_name_contains or description — use these to determine "
            "which plugin fits the connected device. "
            "Also returns whether plugins are enabled and the current policy. "
            "Plugins require SERIAL_MCP_PLUGINS env var — set to 'all' for all or 'name1,name2' to allow specific plugins. "
            "If disabled, tell the user to set this variable when adding the MCP server."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="serial.plugin.reload",
        description=(
            "Hot-reload a plugin by name. Re-imports the module and refreshes tools. "
            "Requires SERIAL_MCP_PLUGINS env var to be set."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the loaded plugin to reload.",
                },
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="serial.plugin.template",
        description=(
            "Return a Python plugin template. Use this when creating a new plugin. "
            "Optionally pre-fill with a device name. Save the result to "
            ".serial_mcp/plugins/<name>.py, fill in the tools and handlers, "
            "then load with serial.plugin.load."
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
        name="serial.plugin.load",
        description=(
            "Load a new plugin from a file or directory path. Requires SERIAL_MCP_PLUGINS env var to be set."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to a .py file or directory containing __init__.py.",
                },
            },
            "required": ["path"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Handler factory
# ---------------------------------------------------------------------------


def make_handlers(manager: PluginManager, server: Server) -> dict[str, Any]:
    """Return handler closures that capture *manager* and *server*."""

    async def handle_plugin_template(_state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
        device_name = args.get("device_name")
        template = _plugin_template(device_name)
        suggested_path = _suggest_plugin_path(manager.plugins_dir, device_name)
        return _ok(template=template, suggested_path=str(suggested_path))

    async def handle_plugin_list(_state: SerialState, _args: dict[str, Any]) -> dict[str, Any]:
        plugins = [
            {"name": info.name, "path": str(info.path), "tools": info.tool_names, "meta": info.meta}
            for info in manager.loaded.values()
        ]
        return _ok(
            plugins=plugins,
            count=len(plugins),
            plugins_dir=str(manager.plugins_dir),
            enabled=manager.enabled,
            policy=manager.policy,
        )

    async def handle_plugin_reload(_state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name", "")
        if not name:
            return _err("invalid_params", "name is required")
        try:
            info = manager.reload(name)
        except KeyError as exc:
            return _err("not_found", str(exc))
        except PermissionError as exc:
            return _err("plugins_disabled", str(exc))
        except ValueError as exc:
            return _err("plugin_error", str(exc))

        notified = False
        try:
            await server.request_context.session.send_tool_list_changed()
            notified = True
        except Exception:
            pass

        return _ok(
            name=info.name,
            tools=info.tool_names,
            notified=notified,
        )

    async def handle_plugin_load(_state: SerialState, args: dict[str, Any]) -> dict[str, Any]:
        raw_path = args.get("path", "")
        if not raw_path:
            return _err("invalid_params", "path is required")
        try:
            info = manager.load(Path(raw_path))
        except PermissionError as exc:
            return _err("plugins_disabled", str(exc))
        except ValueError as exc:
            return _err("plugin_error", str(exc))

        notified = False
        try:
            await server.request_context.session.send_tool_list_changed()
            notified = True
        except Exception:
            pass

        return _ok(
            name=info.name,
            tools=info.tool_names,
            notified=notified,
            hint="Plugin loaded on the server. The client may need a restart to call the new tools.",
        )

    return {
        "serial.plugin.template": handle_plugin_template,
        "serial.plugin.list": handle_plugin_list,
        "serial.plugin.reload": handle_plugin_reload,
        "serial.plugin.load": handle_plugin_load,
    }
