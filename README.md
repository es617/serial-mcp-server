# Serial MCP Server

![MCP](https://img.shields.io/badge/MCP-compatible-blue)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Serial](https://img.shields.io/badge/Serial-RS232%2FUART-green)

A stateful serial port Model Context Protocol (MCP) server for developer tooling and AI agents.
Works out of the box with Claude Code and any MCP-compatible runtime. Communicates over **stdio** (no HTTP, no open ports) and uses [pyserial](https://github.com/pyserial/pyserial) for cross-platform serial on macOS, Windows, and Linux.

> **Example:** Let Claude Code list available serial ports, open a connection to your device, send commands, and read responses from real hardware.

---

## Why this exists

You have a serial device. You want an AI agent to talk to it — open a port, send commands, read responses, debug protocols. This server makes that possible.

It gives any MCP-compatible agent a full set of serial tools: listing ports, opening connections, reading, writing, line-oriented I/O, control line manipulation — plus protocol specs and device plugins, so the agent can reason about higher-level device behavior instead of just raw bytes.

The agent calls these tools, gets structured JSON back, and reasons about what to do next — no human in the loop for each serial operation.

**What agents can do with it:**

- **Develop and debug** — connect to your device, send commands, read responses, and diagnose issues conversationally. "Why is this sensor returning zeros?" becomes a question you can ask.
- **Iterate on new hardware** — building a serial device? Attach a protocol spec so the agent understands your commands and data formats as you evolve them.
- **Automate testing** — write device-specific plugins that expose high-level actions (e.g., `device.start_stream`, `device.run_self_test`), then let the agent run test sequences.
- **Explore** — point the agent at a device you've never seen. It sends commands, observes responses, and builds up protocol documentation from scratch.
- **Build serial automation** — agents controlling real hardware: reading sensors, managing device fleets, triggering actuators based on conditions.

---

## Who is this for?

- **Embedded engineers** — faster iteration on serial protocols, conversational debugging, automated test sequences
- **Hobbyists and makers** — interact with serial devices without writing boilerplate; let the agent help reverse-engineer simple protocols
- **QA and test engineers** — build repeatable serial test suites with plugin tools
- **Support and field engineers** — diagnose serial device issues interactively without specialized tooling
- **Researchers** — automate data collection from serial devices, explore device capabilities systematically

---

## Quickstart (Claude Code)

```bash
pip install serial-mcp-server

# Register the MCP server with Claude Code
claude mcp add serial -- serial_mcp
```

Then in Claude Code, try:

> "List available serial ports and connect to the one on /dev/ttyUSB0 at 115200 baud."

---

## What the agent can do

Once connected, the agent has full serial capabilities:

- **List ports** to find available serial devices
- **Open and close** connections with configurable baud rate, parity, stop bits, and encoding
- **Read and write** data in text, hex, or base64 format
- **Line-oriented I/O** — readline and read-until-delimiter for text protocols
- **Control lines** — set or pulse DTR and RTS for hardware reset and boot mode entry
- **Flush** input and output buffers
- **Attach protocol specs** to understand device-specific commands and data formats
- **Use plugins** for high-level device operations instead of raw reads/writes
- **Create specs and plugins** for new devices, building up reusable knowledge across sessions

The agent handles multi-step flows automatically. For example, "reset the microcontroller and read the boot banner" might involve pulsing DTR, waiting, then reading until a prompt — without you specifying each step.

At a high level:

**Raw Serial → Protocol Spec → Plugin**

You can start with raw serial tools, then move up the stack as your device protocol becomes understood and repeatable.

---

## Install (development)

```bash
# Editable install from repo root
pip install -e .

# Or with uv
uv pip install -e .
```

## Add to Claude Code

```bash
# Standard setup
claude mcp add serial -- serial_mcp

# Or run as a module
claude mcp add serial -- python -m serial_mcp_server

# Enable all plugins
claude mcp add serial -e SERIAL_MCP_PLUGINS=all -- serial_mcp

# Enable specific plugins only
claude mcp add serial -e SERIAL_MCP_PLUGINS=mydevice,ota -- serial_mcp

# Debug logging
claude mcp add serial -e SERIAL_MCP_LOG_LEVEL=DEBUG -- serial_mcp
```

> MCP is a protocol. Claude Code is one MCP client; other agent runtimes can also connect to this server.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SERIAL_MCP_MAX_CONNECTIONS` | `10` | Maximum simultaneous open serial connections. |
| `SERIAL_MCP_PLUGINS` | disabled | Plugin policy: `all` to allow all, or `name1,name2` to allow specific plugins. Unset = disabled. |
| `SERIAL_MCP_LOG_LEVEL` | `WARNING` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Logs go to stderr. |
| `SERIAL_MCP_TRACE` | enabled | JSONL tracing of every tool call. Set to `0`, `false`, or `no` to disable. |
| `SERIAL_MCP_TRACE_PAYLOADS` | disabled | Include write `data` in traced args (stripped by default). |
| `SERIAL_MCP_TRACE_MAX_BYTES` | `16384` | Max payload chars before truncation (only applies when `TRACE_PAYLOADS` is on). |

---

## Tools

| Category | Tools |
|---|---|
| **Serial Core** | `serial.list_ports`, `serial.open`, `serial.close`, `serial.connection_status`, `serial.read`, `serial.write`, `serial.readline`, `serial.read_until`, `serial.flush`, `serial.set_dtr`, `serial.set_rts`, `serial.pulse_dtr`, `serial.pulse_rts` |
| **Introspection** | `serial.connections.list` |
| **Protocol Specs** | `serial.spec.template`, `serial.spec.register`, `serial.spec.list`, `serial.spec.attach`, `serial.spec.get`, `serial.spec.read`, `serial.spec.search` |
| **Tracing** | `serial.trace.status`, `serial.trace.tail` |
| **Plugins** | `serial.plugin.template`, `serial.plugin.list`, `serial.plugin.reload`, `serial.plugin.load` |

---

## Protocol Specs

Specs are markdown files that describe a serial device's protocol — connection settings, message format, commands, and multi-step flows. They live in `.serial_mcp/specs/` and teach the agent what a device can do beyond raw bytes.

Without a spec, the agent can still open a port and exchange data. With a spec, it knows what commands to send, what responses to expect, and what the data means.

You can create specs by telling the agent about your device — paste a datasheet, describe the protocol, or just let it explore and document what it finds. The agent generates the spec file, registers it, and references it in future sessions. You can also write specs by hand.

---

## Plugins

Plugins add device-specific shortcut tools to the server. Instead of the agent composing raw read/write sequences, a plugin provides high-level operations like `mydevice.read_temp` or `ota.upload_firmware`.

The agent can also **create** plugins (with your approval). It explores a device, writes a plugin based on what it learns, and future sessions get shortcut tools — no manual coding required.

To enable plugins:

```bash
# Enable all plugins
claude mcp add serial -e SERIAL_MCP_PLUGINS=all -- serial_mcp

# Enable specific plugins only
claude mcp add serial -e SERIAL_MCP_PLUGINS=mydevice,ota -- serial_mcp
```

Editing an already-loaded plugin only requires `serial.plugin.reload` — no restart needed.

---

## Tracing

Every tool call is traced to `.serial_mcp/traces/trace.jsonl` and an in-memory ring buffer (last 2000 events). Tracing is **on by default** — set `SERIAL_MCP_TRACE=0` to disable.

### Event format

Two events per tool call:

```jsonl
{"ts":"2025-01-01T00:00:00.000Z","event":"tool_call_start","tool":"serial.read","args":{"connection_id":"s1"},"connection_id":"s1"}
{"ts":"2025-01-01T00:00:00.050Z","event":"tool_call_end","tool":"serial.read","ok":true,"error_code":null,"duration_ms":50,"connection_id":"s1"}
```

- `connection_id` is extracted from args when present
- Write `data` is stripped from traced args by default (enable with `SERIAL_MCP_TRACE_PAYLOADS=1`)

### Inspecting the trace

Use `serial.trace.status` to check config and event count, and `serial.trace.tail` to retrieve recent events — no need to read the file directly.

---

## Try without an agent

You can test the server interactively using the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) — no Claude or other agent needed:

```bash
npx @modelcontextprotocol/inspector python -m serial_mcp_server
```

Open the URL with the auth token from the terminal output. The Inspector gives you a web UI to call any tool and see responses in real time.

---

## Architecture

- **stdio MCP transport** — no HTTP, no network ports
- **Stateful** — connections persist in memory across tool calls
- **Agent-friendly** — structured JSON outputs with human-readable messages
- **Graceful shutdown** — closes all serial ports on exit

---

## Known limitations

- **Single-client only.** The server handles one MCP session at a time (stdio transport). Multi-client transports (HTTP/SSE) may be added later.

---

## Safety

This server connects an AI agent to real hardware. That's the point — and it means the stakes are higher than pure-software tools.

**Plugins execute arbitrary code.** When plugins are enabled, the agent can create and run Python code on your machine with full server privileges. Review agent-generated plugins before loading them. Use `SERIAL_MCP_PLUGINS=name1,name2` to allow only specific plugins rather than `all`.

**Writes affect real devices.** A bad command sent to a serial device can trigger unintended behavior, disrupt other connected systems, or cause hardware damage. Consider what the agent can reach.

**Use tool approval deliberately.** When your MCP client prompts you to approve a tool call, consider whether you want to allow it once or always. "Always allow" is convenient but means the agent can repeat that action without further confirmation.

This software is provided as-is under the MIT License. You are responsible for what the agent does with your hardware.

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgements

This project is built on top of the excellent [pyserial](https://github.com/pyserial/pyserial) library for cross-platform serial communication in Python.
