"""Serial MCP server – stdio transport, stateful serial tools via pyserial."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any

import anyio
import serial as pyserial
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from serial_mcp_server import (
    handlers_introspection,
    handlers_plugin,
    handlers_serial,
    handlers_spec,
    handlers_trace,
)
from serial_mcp_server.helpers import (
    MAX_CONNECTIONS,
    _err,
    _result_text,
)
from serial_mcp_server.plugins import PluginManager, parse_plugin_policy
from serial_mcp_server.specs import resolve_spec_root
from serial_mcp_server.state import SerialState
from serial_mcp_server.trace import get_trace_buffer, init_trace, sanitize_args

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_LEVEL = os.environ.get("SERIAL_MCP_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("serial_mcp_server")

# ---------------------------------------------------------------------------
# Server construction
# ---------------------------------------------------------------------------


def build_server() -> tuple[Server, SerialState]:
    state = SerialState(max_connections=MAX_CONNECTIONS)
    server = Server("serial-mcp-server")

    tools: list[Tool] = (
        handlers_serial.TOOLS
        + handlers_introspection.TOOLS
        + handlers_spec.TOOLS
        + handlers_trace.TOOLS
        + handlers_plugin.TOOLS
    )
    handlers: dict[str, Any] = {
        **handlers_serial.HANDLERS,
        **handlers_introspection.HANDLERS,
        **handlers_spec.HANDLERS,
        **handlers_trace.HANDLERS,
    }

    # --- Plugin system ---
    plugins_dir = resolve_spec_root() / "plugins"
    plugins_enabled, plugins_allowlist = parse_plugin_policy()
    manager = PluginManager(
        plugins_dir,
        tools,
        handlers,
        enabled=plugins_enabled,
        allowlist=plugins_allowlist,
    )
    manager.load_all()
    handlers.update(handlers_plugin.make_handlers(manager, server))

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        arguments = arguments or {}

        buf = get_trace_buffer()
        if buf:
            cid = arguments.get("connection_id")
            safe_args = sanitize_args(arguments)
            buf.emit({"event": "tool_call_start", "tool": name, "args": safe_args, "connection_id": cid})
            t0 = time.monotonic()

        handler = handlers.get(name)
        if handler is None:
            return _result_text(_err("unknown_tool", f"No tool named {name}"))

        try:
            result = await handler(state, arguments)
        except KeyError as exc:
            result = _err("not_found", str(exc))
        except (ValueError, TypeError) as exc:
            result = _err("invalid_params", str(exc))
        except RuntimeError as exc:
            result = _err("limit_reached", str(exc))
        except pyserial.SerialException as exc:
            result = _err("io_error", str(exc))
        except ConnectionError as exc:
            result = _err("disconnected", str(exc))
        except TimeoutError:
            result = _err("timeout", "Serial operation timed out.")
        except Exception as exc:
            logger.error("Unhandled error in %s: %s", name, exc, exc_info=True)
            result = _err("internal", f"Internal error in {name}. Check server logs for details.")

        if result.get("ok") and "connection_id" in arguments:
            conn = state.connections.get(arguments["connection_id"])
            if conn:
                conn.last_seen_ts = time.time()

        if buf:
            duration_ms = round((time.monotonic() - t0) * 1000, 1)
            buf.emit(
                {
                    "event": "tool_call_end",
                    "tool": name,
                    "ok": result.get("ok"),
                    "error_code": result.get("error", {}).get("code")
                    if isinstance(result.get("error"), dict)
                    else None,
                    "duration_ms": duration_ms,
                    "connection_id": cid,
                }
            )

        return _result_text(result)

    init_trace()
    return server, state


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run() -> None:
    server, state = build_server()

    logger.info("Starting Serial MCP server (max_connections=%s)", MAX_CONNECTIONS)

    _BENIGN_ASYNC = (EOFError, BrokenPipeError, anyio.ClosedResourceError, anyio.BrokenResourceError)

    try:
        async with stdio_server() as (read_stream, write_stream):
            init_options = server.create_initialization_options(
                notification_options=NotificationOptions(tools_changed=True),
            )
            await server.run(read_stream, write_stream, init_options)
    except _BENIGN_ASYNC:
        # Normal termination — client closed stdin / streams broke.
        pass
    except BaseExceptionGroup as eg:
        # anyio wraps stream-closure errors in ExceptionGroup on Python 3.11+.
        if not all(isinstance(e, _BENIGN_ASYNC) for e in eg.exceptions):
            raise
    finally:
        try:
            await asyncio.wait_for(asyncio.shield(state.shutdown()), timeout=0.25)
        except (TimeoutError, asyncio.CancelledError, Exception):
            pass
        buf = get_trace_buffer()
        if buf:
            try:
                buf.close()
            except Exception:
                pass


_BENIGN_SYNC = (
    KeyboardInterrupt,
    BrokenPipeError,
    EOFError,
    ConnectionError,
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
)


def main() -> None:
    try:
        asyncio.run(_run())
    except _BENIGN_SYNC:
        pass
    except BaseExceptionGroup as eg:
        if not all(isinstance(e, _BENIGN_SYNC) for e in eg.exceptions):
            raise


if __name__ == "__main__":
    main()
