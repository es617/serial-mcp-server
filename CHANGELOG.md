# Changelog

## 0.1.0

Initial release.

### Serial Core
- List available serial ports with device metadata (VID, PID, manufacturer, serial number)
- Open connections with configurable baud rate, byte size, parity, stop bits, timeout, and encoding
- Close connections, query connection status
- Read data with configurable byte count and timeout override
- Write data in text, hex, or base64 format, with optional newline append
- Line-oriented I/O: `serial.readline` and `serial.read_until` with custom delimiters
- Flush input/output buffers (or both)
- Control lines: set and pulse DTR/RTS (useful for hardware reset and boot mode entry)
- Duplicate port detection (rejects opening the same port twice)
- Graceful shutdown (closes all serial ports on exit)

### Introspection
- `serial.connections.list` for recovering connection IDs and inspecting state

### Protocol Specs
- Markdown specs with YAML front-matter (`kind: serial-protocol`, `name`)
- Template generation, registration, indexing
- Attach specs to connections for agent reference
- Full-text search over spec content

### Tracing
- JSONL tracing of every tool call (in-memory ring buffer + file sink)
- Configurable payload logging with truncation
- `serial.trace.status` and `serial.trace.tail` for inspection

### Plugins
- User plugins in `.serial_mcp/plugins/` (single files or packages)
- Plugin contract: `TOOLS`, `HANDLERS`, optional `META` for device matching
- `SERIAL_MCP_PLUGINS` env var: `all` or comma-separated allowlist
- `serial.plugin.template` for generating plugin skeletons
- `serial.plugin.list` with metadata, `serial.plugin.load`, `serial.plugin.reload`
- Hot-reload without server restart

### Security
- Plugin path containment: `serial.plugin.load` rejects paths outside `.serial_mcp/plugins/`
- Spec path containment: `serial.spec.register` rejects paths outside the project directory
- Trace file always writes to `.serial_mcp/traces/trace.jsonl` (no configurable path)
- Symlink check on trace file path
- Input validation for hex/base64 write payloads
