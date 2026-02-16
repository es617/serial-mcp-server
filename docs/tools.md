# Tools Reference

All tools return structured JSON:
`{ "ok": true, ... }` on success,
`{ "ok": false, "error": { "code": "...", "message": "..." } }` on failure.

---

## Serial Core

### serial.list_ports

List available serial ports on the system.

```json
{}
```

Returns:

```json
{
  "ok": true,
  "message": "Found 2 serial port(s).",
  "ports": [{
    "device": "/dev/ttyUSB0",
    "name": "ttyUSB0",
    "description": "USB Serial",
    "hwid": "USB VID:PID=1234:5678",
    "vid": "0x1234",
    "pid": "0x5678",
    "serial_number": "ABC123",
    "manufacturer": "FTDI",
    "product": "FT232R"
  }],
  "count": 2
}
```

Fields like `vid`, `pid`, `serial_number`, `manufacturer`, and `product` are included when available.

### serial.open

Open a serial port connection. Returns a `connection_id` for use with other tools. Defaults are 115200 baud, 8N1, `\r\n` line terminator.

```json
{
  "port": "/dev/ttyUSB0",
  "baudrate": 115200,
  "bytesize": 8,
  "parity": "N",
  "stopbits": 1,
  "timeout_ms": 200,
  "write_timeout_ms": 200,
  "encoding": "utf-8",
  "newline": "\r\n"
}
```

Only `port` is required. All other parameters have defaults.

Returns:

```json
{
  "ok": true,
  "message": "Opened /dev/ttyUSB0 at 115200 baud.",
  "connection_id": "s1a2b3c4",
  "config": {
    "port": "/dev/ttyUSB0",
    "baudrate": 115200,
    "bytesize": 8,
    "parity": "N",
    "stopbits": 1,
    "timeout_ms": 200,
    "write_timeout_ms": 200,
    "encoding": "utf-8",
    "newline": "'\\r\\n'"
  },
  "mirror": {
    "pty_path": "/dev/ttys004",
    "link": "/tmp/serial-mcp0",
    "mode": "ro"
  }
}
```

The `mirror` field is only present when `SERIAL_MCP_MIRROR` is set to `ro` or `rw`.

### serial.close

Close a serial port connection and release the port.

```json
{ "connection_id": "s1a2b3c4" }
```

### serial.connection_status

Check whether a serial connection is still open and return its configuration.

```json
{ "connection_id": "s1a2b3c4" }
```

Returns `{ "ok": true, "is_open": true, "config": { ... }, "buffered_bytes": 0 }`. Includes `mirror` when active.

### serial.read

Read up to `nbytes` from a serial port. Returns immediately with whatever data is available within the timeout.

```json
{ "connection_id": "s1a2b3c4", "nbytes": 256, "timeout_ms": 500, "as": "text" }
```

Only `connection_id` is required. `as` can be `"text"` (default), `"hex"`, or `"base64"`.

Returns:

```json
{
  "ok": true,
  "message": "Read 12 byte(s) from /dev/ttyUSB0.",
  "n_read": 12,
  "data": "Hello world\n",
  "format": "text",
  "encoding": "utf-8"
}
```

### serial.write

Write data to a serial port.

```json
{ "connection_id": "s1a2b3c4", "data": "AT+VERSION", "append_newline": true }
```

- `as`: `"text"` (default), `"hex"`, or `"base64"` — how to interpret the `data` string
- `append_newline`: append the connection's newline (`\r\n` by default) after data

Returns `{ "ok": true, "message": "Wrote 12 byte(s) to /dev/ttyUSB0.", "bytes_written": 12 }`.

### serial.readline

Read a line from the serial port (reads until the newline character is received or `max_bytes` is reached). Uses the connection's newline setting by default.

```json
{ "connection_id": "s1a2b3c4", "timeout_ms": 1000, "max_bytes": 4096 }
```

Only `connection_id` is required. Supports `as` and `newline` overrides.

Returns `{ "ok": true, "n_read": 15, "data": "OK 200 ready\r\n", "format": "text" }`.

### serial.read_until

Read from the serial port until a delimiter string is received or `max_bytes` is reached.

```json
{ "connection_id": "s1a2b3c4", "delimiter": ">", "max_bytes": 4096 }
```

Only `connection_id` is required. Default delimiter is `\n`.

### serial.flush

Flush serial port buffers (discard pending data).

```json
{ "connection_id": "s1a2b3c4", "what": "both" }
```

`what` can be `"input"`, `"output"`, or `"both"` (default).

### serial.set_dtr

Set the DTR (Data Terminal Ready) control line. Usage is device-specific.

```json
{ "connection_id": "s1a2b3c4", "value": false }
```

### serial.set_rts

Set the RTS (Request To Send) control line. Usage is device-specific.

```json
{ "connection_id": "s1a2b3c4", "value": true }
```

### serial.pulse_dtr

Pulse the DTR line: sets low, waits `duration_ms`, then sets high. Commonly used to reset microcontrollers.

```json
{ "connection_id": "s1a2b3c4", "duration_ms": 100 }
```

Only `connection_id` is required. Default duration is 100ms.

### serial.pulse_rts

Pulse the RTS line: sets low, waits `duration_ms`, then sets high. Some devices use RTS to enter bootloader mode.

```json
{ "connection_id": "s1a2b3c4", "duration_ms": 100 }
```

---

## Introspection

### serial.connections.list

List all open serial connections with their status, port, configuration, and timestamps. Useful for recovering connection IDs after context loss.

```json
{}
```

Returns:

```json
{
  "ok": true,
  "connections": [{
    "connection_id": "s1a2b3c4",
    "port": "/dev/ttyUSB0",
    "is_open": true,
    "baudrate": 115200,
    "encoding": "utf-8",
    "opened_at": 1700000000.0,
    "last_seen_ts": 1700000050.0,
    "buffered_bytes": 0,
    "mirror": {
      "pty_path": "/dev/ttys004",
      "link": "/tmp/serial-mcp0",
      "mode": "ro"
    }
  }],
  "count": 1
}
```

The `mirror` field is only present on connections where `SERIAL_MCP_MIRROR` is `ro` or `rw`. `buffered_bytes` shows how many unread bytes are in the connection's read buffer.

---

## Protocol Specs

Tools for managing serial device protocol specs. Specs are markdown files with YAML front-matter stored in `.serial_mcp/specs/`.

### serial.spec.template

Return a markdown template for a new serial protocol spec.

```json
{ "device_name": "MyDevice" }
```

Returns `{ "ok": true, "template": "---\nkind: serial-protocol\n...", "suggested_path": ".serial_mcp/specs/mydevice.md" }`.

### serial.spec.register

Register a spec file in the index. Validates YAML front-matter (requires `kind: serial-protocol` and `name`). The path must be inside the project directory.

```json
{ "path": ".serial_mcp/specs/mydevice.md" }
```

Returns `{ "ok": true, "spec_id": "a1b2c3d4e5f67890", "name": "MyDevice Protocol", ... }`.

### serial.spec.list

List all registered specs with their metadata.

```json
{}
```

Returns `{ "ok": true, "specs": [...], "count": 2 }`.

### serial.spec.attach

Attach a registered spec to a connection session (in-memory only). The spec will be available via `serial.spec.get` for the duration of the connection.

```json
{ "connection_id": "s1a2b3c4", "spec_id": "a1b2c3d4e5f67890" }
```

### serial.spec.get

Get the attached spec for a connection (returns `null` if none attached).

```json
{ "connection_id": "s1a2b3c4" }
```

### serial.spec.read

Read full spec content, file path, and metadata by spec_id.

```json
{ "spec_id": "a1b2c3d4e5f67890" }
```

### serial.spec.search

Full-text search over a spec's content. Returns matching snippets with line numbers and context.

```json
{ "spec_id": "a1b2c3d4e5f67890", "query": "baud rate", "k": 10 }
```

---

## Tracing

Tools for inspecting the JSONL trace log. Tracing is enabled by default and records every tool call.

### serial.trace.status

Return tracing config and event count.

```json
{}
```

Returns `{ "ok": true, "enabled": true, "event_count": 42, "file_path": ".serial_mcp/traces/trace.jsonl", "payloads_logged": false, "max_payload_bytes": 16384 }`.

### serial.trace.tail

Return last N trace events (default 50).

```json
{ "n": 20 }
```

Returns `{ "ok": true, "events": [{ "ts": "...", "event": "tool_call_start", "tool": "serial.read", ... }, ...] }`.

---

## Plugins

Tools for managing user plugins. Plugins live in `.serial_mcp/plugins/` and can add device-specific tools without modifying the core server. Requires `SERIAL_MCP_PLUGINS` env var to be set.

### serial.plugin.template

Return a Python plugin template. Optionally pre-fill with a device name.

```json
{ "device_name": "MyDevice" }
```

Returns `{ "ok": true, "template": "\"\"\"Plugin for MyDevice...", "suggested_path": ".serial_mcp/plugins/mydevice.py" }`.

### serial.plugin.list

List loaded plugins with their tool names and metadata.

```json
{}
```

Returns:

```json
{
  "ok": true,
  "plugins": [{
    "name": "gps",
    "path": "/path/to/.serial_mcp/plugins/gps.py",
    "tools": ["gps.get_position"],
    "meta": {
      "description": "NMEA GPS module plugin",
      "device_name_contains": "GPS"
    }
  }],
  "count": 1,
  "plugins_dir": "/path/to/.serial_mcp/plugins",
  "enabled": true,
  "policy": "*"
}
```

The `meta` field is plugin-defined (optional). Common keys: `description`, `device_name_contains`.

### serial.plugin.reload

Hot-reload a plugin by name. Re-imports the module and refreshes tools.

```json
{ "name": "gps" }
```

Returns `{ "ok": true, "name": "gps", "tools": ["gps.get_position"], "notified": true }`.

### serial.plugin.load

Load a new plugin from a file or directory path. The path must be inside `.serial_mcp/plugins/`.

```json
{ "path": ".serial_mcp/plugins/gps.py" }
```

Returns `{ "ok": true, "name": "gps", "tools": ["gps.get_position"], "notified": true, "hint": "Plugin loaded on the server. The client may need a restart to call the new tools." }`.
