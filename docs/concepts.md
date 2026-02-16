# Concepts

How the Serial MCP server works, and how the pieces fit together.

---

## How the agent interacts with devices

The server gives an AI agent (like Claude) a set of serial tools over the MCP protocol. The agent uses these tools to talk to real hardware — listing ports, opening connections, sending commands, and reading responses.

Everything is **stateful**: connections persist across tool calls. The agent doesn't have to re-open the port between each operation.

```
┌─────────────┐       stdio/MCP        ┌──────────────────┐      serial       ┌──────────┐
│  AI Agent   │ ◄────────────────────► │ Serial MCP Server │ ◄──────────────► │  Device  │
│ (Claude etc)│   structured JSON      │  (this project)   │    pyserial      │          │
└─────────────┘                        └──────────────────┘                   └──────────┘
```

The agent sees tools like `serial.open`, `serial.write`, `serial.readline`. It calls them, gets structured JSON back, and reasons about what to do next.

---

## Security model

Plugins can execute arbitrary code, so they are opt-in:

| `SERIAL_MCP_PLUGINS` | Effect |
|---|---|
| *(unset)* | Plugins disabled — no loading, no discovery |
| `all` | All plugins in `.serial_mcp/plugins/` are loaded |
| `name1,name2` | Only named plugins are loaded |

The agent cannot bypass these flags. It can only use the tools the server exposes, and the server enforces the policy.

Path containment is enforced for all filesystem operations:
- **Plugins** must be inside `.serial_mcp/plugins/`
- **Specs** must be inside the project directory (parent of `.serial_mcp/`)
- **Traces** always write to `.serial_mcp/traces/trace.jsonl` (not configurable)

---

## Protocol specs — teaching the agent about your device

Specs are markdown files that describe a serial device's protocol: connection settings, message format, commands, and multi-step flows.

```
.serial_mcp/
  specs/
    my-device.md      # protocol documentation
```

The agent reads specs to understand what a device can do. Without a spec, the agent can still open a port and exchange data, but it won't know what commands to send or what responses mean.

### How specs help the agent

```
Without spec:                         With spec:
  "I opened /dev/ttyUSB0 at 115200.    "This is the GPS module. It uses
   I can send bytes but I don't          9600 baud, NMEA 0183 format.
   know what the device expects."        $GPGGA sentences contain lat/lon.
                                         Send $PMTK314,0,1,0,0,0,0*29
                                         to enable RMC-only output."
```

### Creating a spec

Tell the agent about your device's protocol — paste a datasheet, a link to docs, or just describe the commands in chat. The agent will create the spec file, register it, and use it in future sessions.

You can also write specs by hand. They're just markdown files with a small YAML header.

### How the agent uses specs

After opening a connection, the agent checks for registered specs, attaches a matching one, and references it throughout the session — looking up commands, expected responses, and multi-step flows as needed.

Specs are freeform markdown. The agent reads and reasons about them — there's no rigid schema to fight, so specs can evolve naturally with your protocol.

### Beyond the agent

Specs aren't just for the agent — they're structured protocol documentation that lives in your repo. If you're designing a new serial protocol, specs created during agent sessions become the foundation for official protocol docs. They capture what was discovered, tested, and verified through real device interaction.

---

## Plugins — giving the agent shortcut tools

Plugins add device-specific tools to the server. Instead of the agent manually composing write/read sequences, a plugin provides high-level operations like `gps.get_position` or `sensor.read_temp`.

```
.serial_mcp/
  plugins/
    gps.py           # adds gps.* tools
    sensor.py        # adds sensor.* tools
```

### What a plugin provides

```python
TOOLS = [...]       # Tool definitions the agent can call
HANDLERS = {...}    # Implementation for each tool
META = {...}        # Optional: matching hints (device name patterns, description)
```

### How the agent uses plugins

After opening a connection, the agent checks `serial.plugin.list`. Each plugin includes metadata that helps the agent decide if it fits:

```json
{
  "name": "gps",
  "tools": ["gps.get_position", "gps.configure_output"],
  "meta": {
    "description": "NMEA GPS module plugin",
    "device_name_contains": "GPS"
  }
}
```

### AI-authored plugins

The agent can also **create** plugins. Using `serial.plugin.template`, it generates a skeleton, fills in the implementation based on the device spec, and saves it to `.serial_mcp/plugins/`. After a server restart (or hot-reload), the new tools are available. Review generated plugins before enabling them in sensitive environments.

This is the core loop: the agent explores a device, writes a plugin for it, and future sessions get shortcut tools.

### Beyond the agent

Plugin code is real Python that talks to real hardware. It can serve as a starting point for standalone test scripts, CLI tools, or production libraries. The agent writes the first draft based on the device spec, and you refine it into whatever you need.

---

## How specs and plugins connect

Specs and plugins serve different roles:

| | Spec | Plugin |
|---|---|---|
| **What** | Documentation | Code |
| **Purpose** | Teach the agent what the device can do | Give the agent shortcut tools |
| **Format** | Freeform markdown | Python module |
| **Required?** | No — agent can still explore with raw tools | No — agent can use raw serial tools |
| **Bound to** | A connection (via `serial.spec.attach`) | Global (all connections) |

They work together:

```
                    ┌──────────────────┐
                    │  Protocol Spec   │──── "What can this device do?"
                    │  (markdown)      │     Agent reads and reasons
                    └────────┬─────────┘
                             │
                     agent reasons about
                     the spec, or creates
                             │
                    ┌────────▼─────────┐
                    │     Plugin       │──── "Shortcut tools for this device"
                    │  (Python module) │     Agent calls directly
                    └──────────────────┘
```

A plugin doesn't require a spec, and a spec doesn't require a plugin. But when both exist for a device, the agent gets the best of both: deep protocol knowledge from the spec, and fast operations from the plugin.

---

## The agent's decision flow

After opening a connection, the agent follows this flow:

```
Open serial port
       │
       ▼
Check serial.spec.list ──── matching spec? ──── yes ──► serial.spec.attach
       │                                                       │
       │ no                                                    │
       ▼                                                       ▼
Check serial.plugin.list ◄──────────────────────── Check serial.plugin.list
       │                                                       │
       │                                                       ▼
       ▼                                             Present options:
  matching plugin? ─── yes ──► use plugin tools       • use plugin tools
       │                                              • follow spec manually
       │ no                                           • extend plugin
       ▼                                              • create new plugin
  Ask user / explore
  with raw serial tools
```

The agent handles this automatically. The tool descriptions guide it through each step.
