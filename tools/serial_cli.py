#!/usr/bin/env python3
"""Interactive CLI for testing the Serial MCP server over stdio.

Usage:
    python tools/serial_cli.py

Starts the MCP server as a subprocess and provides a simple REPL
for calling serial tools interactively.
"""

import json
import os
import readline  # noqa: F401 — enables arrow keys / history in input()
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# MCP client wrapper
# ---------------------------------------------------------------------------

_id_counter = 0


def _next_id():
    global _id_counter
    _id_counter += 1
    return _id_counter


class McpClient:
    def __init__(self):
        env = {**os.environ}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "serial_mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

    def send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv(self):
        """Read one JSON-RPC response (skip notifications)."""
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"  [raw] {line}")
                continue
            # Skip notifications (no "id" field)
            if "id" not in msg:
                continue
            return msg

    def call_tool(self, name, arguments=None):
        msg = {
            "jsonrpc": "2.0",
            "id": _next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        self.send(msg)
        resp = self.recv()
        if resp is None:
            print("  [error] No response from server")
            return None
        if "error" in resp:
            print(f"  [rpc error] {resp['error']}")
            return None
        # Extract the tool result text
        content = resp.get("result", {}).get("content", [])
        if content:
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return None

    def initialize(self):
        time.sleep(0.5)
        if self.proc.poll() is not None:
            stderr = self.proc.stderr.read()
            print(f"  [error] Server exited with code {self.proc.returncode}")
            if stderr:
                print(f"  [stderr] {stderr.strip()}")
            return None

        self.send(
            {
                "jsonrpc": "2.0",
                "id": _next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "serial-cli", "version": "0.1"},
                },
            }
        )
        resp = self.recv()
        if resp is None:
            stderr = self.proc.stderr.read()
            print("  [error] No response to initialize")
            if stderr:
                print(f"  [stderr] {stderr.strip()}")
            return None
        # Send initialized notification
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return resp

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------


def pp(data):
    if data is None:
        return
    print(json.dumps(data, indent=2, default=str))


def print_ports(ports):
    if not ports:
        print("  No ports found.")
        return
    for i, p in enumerate(ports):
        device = p.get("device", "?")
        desc = p.get("description", "")
        mfr = p.get("manufacturer", "")
        extra = f"  ({mfr})" if mfr else ""
        print(f"  [{i}] {device:30s}  {desc}{extra}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

# State to remember IDs between commands
last_connection_id = None
last_ports = []


def cmd_ports(client, args):
    global last_ports
    result = client.call_tool("serial.list_ports", {})
    if result and result.get("ok"):
        last_ports = result.get("ports", [])
        print_ports(last_ports)
    else:
        pp(result)


def cmd_open(client, args):
    global last_connection_id
    if not args:
        print("  Usage: open <port or index> [baudrate]")
        return

    port = args[0]
    # Allow opening by index from last ports listing
    if port.isdigit() and last_ports:
        idx = int(port)
        if 0 <= idx < len(last_ports):
            port = last_ports[idx]["device"]
        else:
            print(f"  Index {idx} out of range (0-{len(last_ports) - 1})")
            return

    params = {"port": port}
    if len(args) > 1:
        try:
            params["baudrate"] = int(args[1])
        except ValueError:
            print(f"  Invalid baudrate: {args[1]}")
            return

    print(f"  Opening {port}...")
    result = client.call_tool("serial.open", params)
    if result and result.get("ok"):
        last_connection_id = result["connection_id"]
        config = result.get("config", {})
        baud = config.get("baudrate", "?")
        print(f"  Opened: {last_connection_id}  ({port} at {baud} baud)")
    else:
        pp(result)


def cmd_close(client, args):
    global last_connection_id
    cid = args[0] if args else last_connection_id
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return
    result = client.call_tool("serial.close", {"connection_id": cid})
    if result and result.get("ok"):
        print(f"  Closed: {cid}")
        if cid == last_connection_id:
            last_connection_id = None
    else:
        pp(result)


def cmd_read(client, args):
    cid = last_connection_id
    nbytes = 256
    timeout_ms = None

    for a in args:
        if a.startswith("t="):
            timeout_ms = int(a[2:])
        elif a.isdigit():
            nbytes = int(a)
        else:
            cid = a

    if not cid:
        print("  No connection ID. Run 'open' first.")
        return

    params = {"connection_id": cid, "nbytes": nbytes}
    if timeout_ms is not None:
        params["timeout_ms"] = timeout_ms

    result = client.call_tool("serial.read", params)
    if result and result.get("ok"):
        data = result.get("data", "")
        n = result.get("n_read", 0)
        if n == 0:
            print("  (no data)")
        else:
            print(f"  [{n} bytes] {data}")
    else:
        pp(result)


def cmd_write(client, args):
    cid = last_connection_id
    if not args:
        print("  Usage: write <text> [connection_id]")
        return

    # Join all args as the text to send
    text = " ".join(args)
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return

    result = client.call_tool(
        "serial.write",
        {"connection_id": cid, "data": text, "append_newline": True},
    )
    if result and result.get("ok"):
        n = result.get("bytes_written", 0)
        print(f"  Wrote {n} bytes")
    else:
        pp(result)


def cmd_writehex(client, args):
    cid = last_connection_id
    if not args:
        print("  Usage: writehex <hex_data> [connection_id]")
        print("  Example: writehex 48656c6c6f")
        return

    hex_data = args[0]
    if len(args) > 1:
        cid = args[1]
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return

    result = client.call_tool(
        "serial.write",
        {"connection_id": cid, "data": hex_data, "as": "hex"},
    )
    if result and result.get("ok"):
        n = result.get("bytes_written", 0)
        print(f"  Wrote {n} bytes")
    else:
        pp(result)


def cmd_readline(client, args):
    cid = last_connection_id
    timeout_ms = None

    for a in args:
        if a.startswith("t="):
            timeout_ms = int(a[2:])
        else:
            cid = a

    if not cid:
        print("  No connection ID. Run 'open' first.")
        return

    params = {"connection_id": cid}
    if timeout_ms is not None:
        params["timeout_ms"] = timeout_ms

    result = client.call_tool("serial.readline", params)
    if result and result.get("ok"):
        data = result.get("data", "")
        n = result.get("n_read", 0)
        if n == 0:
            print("  (no data)")
        else:
            print(f"  {data.rstrip()}")
    else:
        pp(result)


def cmd_readuntil(client, args):
    cid = last_connection_id
    if not args:
        print("  Usage: readuntil <delimiter> [connection_id]")
        return

    delimiter = args[0]
    if len(args) > 1:
        cid = args[1]
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return

    result = client.call_tool(
        "serial.read_until",
        {"connection_id": cid, "delimiter": delimiter},
    )
    if result and result.get("ok"):
        data = result.get("data", "")
        n = result.get("n_read", 0)
        if n == 0:
            print("  (no data)")
        else:
            print(f"  [{n} bytes] {data}")
    else:
        pp(result)


def cmd_flush(client, args):
    cid = last_connection_id
    what = "both"
    for a in args:
        if a in ("input", "output", "both"):
            what = a
        else:
            cid = a
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return
    result = client.call_tool("serial.flush", {"connection_id": cid, "what": what})
    if result and result.get("ok"):
        print(f"  Flushed ({what})")
    else:
        pp(result)


def cmd_dtr(client, args):
    cid = last_connection_id
    if not args:
        print("  Usage: dtr <true|false> [connection_id]")
        return
    value = args[0].lower() in ("true", "1", "on", "high")
    if len(args) > 1:
        cid = args[1]
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return
    result = client.call_tool("serial.set_dtr", {"connection_id": cid, "value": value})
    if result and result.get("ok"):
        print(f"  DTR = {value}")
    else:
        pp(result)


def cmd_rts(client, args):
    cid = last_connection_id
    if not args:
        print("  Usage: rts <true|false> [connection_id]")
        return
    value = args[0].lower() in ("true", "1", "on", "high")
    if len(args) > 1:
        cid = args[1]
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return
    result = client.call_tool("serial.set_rts", {"connection_id": cid, "value": value})
    if result and result.get("ok"):
        print(f"  RTS = {value}")
    else:
        pp(result)


def cmd_pulse_dtr(client, args):
    cid = last_connection_id
    duration = 100
    for a in args:
        if a.isdigit():
            duration = int(a)
        else:
            cid = a
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return
    result = client.call_tool("serial.pulse_dtr", {"connection_id": cid, "duration_ms": duration})
    if result and result.get("ok"):
        print(f"  DTR pulsed ({duration}ms)")
    else:
        pp(result)


def cmd_pulse_rts(client, args):
    cid = last_connection_id
    duration = 100
    for a in args:
        if a.isdigit():
            duration = int(a)
        else:
            cid = a
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return
    result = client.call_tool("serial.pulse_rts", {"connection_id": cid, "duration_ms": duration})
    if result and result.get("ok"):
        print(f"  RTS pulsed ({duration}ms)")
    else:
        pp(result)


def cmd_status(client, args):
    cid = args[0] if args else last_connection_id
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return
    result = client.call_tool("serial.connection_status", {"connection_id": cid})
    pp(result)


def cmd_list(client, args):
    result = client.call_tool("serial.connections.list", {})
    pp(result)


def cmd_raw(client, args):
    """Send a raw tool call: raw <tool_name> <json_args>"""
    if not args:
        print("  Usage: raw <tool_name> [json_args]")
        return
    tool_name = args[0]
    arguments = {}
    if len(args) > 1:
        try:
            arguments = json.loads(" ".join(args[1:]))
        except json.JSONDecodeError as e:
            print(f"  Invalid JSON: {e}")
            return
    result = client.call_tool(tool_name, arguments)
    pp(result)


def cmd_send(client, args):
    """Write text + newline, then readline the response."""
    cid = last_connection_id
    if not args:
        print("  Usage: send <text>")
        return
    text = " ".join(args)
    if not cid:
        print("  No connection ID. Run 'open' first.")
        return

    # Write
    result = client.call_tool(
        "serial.write",
        {"connection_id": cid, "data": text, "append_newline": True},
    )
    if not result or not result.get("ok"):
        pp(result)
        return

    # Read response
    time.sleep(0.1)
    result = client.call_tool("serial.readline", {"connection_id": cid, "timeout_ms": 2000})
    if result and result.get("ok"):
        data = result.get("data", "")
        if data:
            print(f"  {data.rstrip()}")
        else:
            print("  (no response)")
    else:
        pp(result)


COMMANDS = {
    "ports": (cmd_ports, "ports — List available serial ports"),
    "open": (cmd_open, "open <port|index> [baud] — Open a serial port"),
    "close": (cmd_close, "close [connection_id] — Close connection"),
    "read": (cmd_read, "read [nbytes] [t=timeout_ms] — Read raw bytes"),
    "write": (cmd_write, "write <text> — Write text + newline"),
    "writehex": (cmd_writehex, "writehex <hex> — Write raw hex bytes"),
    "readline": (cmd_readline, "readline [t=timeout_ms] — Read one line"),
    "readuntil": (cmd_readuntil, "readuntil <delimiter> — Read until delimiter"),
    "send": (cmd_send, "send <text> — Write + readline (request/response)"),
    "flush": (cmd_flush, "flush [input|output|both] — Flush buffers"),
    "dtr": (cmd_dtr, "dtr <true|false> — Set DTR line"),
    "rts": (cmd_rts, "rts <true|false> — Set RTS line"),
    "pulse_dtr": (cmd_pulse_dtr, "pulse_dtr [duration_ms] — Pulse DTR low"),
    "pulse_rts": (cmd_pulse_rts, "pulse_rts [duration_ms] — Pulse RTS low"),
    "status": (cmd_status, "status [connection_id] — Connection status"),
    "list": (cmd_list, "list — List open connections"),
    "raw": (cmd_raw, "raw <tool_name> [json_args] — Call any tool directly"),
}


def cmd_help():
    print("\nAvailable commands:\n")
    for _name, (_, desc) in COMMANDS.items():
        print(f"  {desc}")
    print("\n  help — Show this help")
    print("  quit — Exit\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("Serial MCP CLI — interactive test client")
    print("Type 'help' for commands, 'quit' to exit.\n")

    client = McpClient()
    resp = client.initialize()
    if resp:
        print("  Server initialized.")
    else:
        print("  [error] Failed to initialize server.")
        return

    print("  Connection ID memory: auto-tracked from last open\n")

    try:
        while True:
            try:
                line = input("serial> ").strip()
            except EOFError:
                break
            if not line:
                continue

            parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                cmd_help()
            elif cmd in COMMANDS:
                try:
                    COMMANDS[cmd][0](client, args)
                except Exception as e:
                    print(f"  [error] {e}")
            else:
                print(f"  Unknown command: {cmd}. Type 'help' for commands.")
    except KeyboardInterrupt:
        print()
    finally:
        client.close()
        print("  Bye.")


if __name__ == "__main__":
    main()
