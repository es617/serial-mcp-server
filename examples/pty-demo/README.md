# PTY Demo Device

A simulated serial device that runs locally using a pseudo-terminal pair. No hardware needed.

## Requirements

- Python 3.11+
- macOS or Linux (uses `os.openpty`)
- No external dependencies

## Quick start

```bash
python3 demo_device.py
```

Output:

```
DemoDevice pty ready.
Connect to: /dev/ttys004
  screen /dev/ttys004 115200
  or point the Serial MCP server at this path.
```

## Test with screen

```bash
screen /dev/ttys004 115200
```

Type `help` to see available commands. `Ctrl-A K` to quit screen.

## Test with the Serial MCP server

Open a connection to the printed slave path:

```
serial.open  →  { "port": "/dev/ttys004" }
serial.write →  { "connection_id": "...", "data": "ping", "append_newline": true }
serial.readline → { "connection_id": "..." }
```

## Protocol

See [demo-device.md](demo-device.md) for the full protocol spec. Register it with the MCP server:

```
serial.spec.register  →  { "path": "examples/pty-demo/demo-device.md" }
```
