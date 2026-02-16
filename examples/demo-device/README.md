# Demo Device

A simulated serial device for testing the Serial MCP server. Same protocol, two ways to run it:

- **`pty_server.py`** — virtual serial port using a PTY pair. Local testing on macOS/Linux, no hardware needed, pure stdlib.
- **`uart_server.py`** — real UART port. Designed for Raspberry Pi but works with any serial port. Requires pyserial.

## Quick start (PTY — local)

```bash
python3 pty_server.py
```

Output:

```
DemoDevice pty ready.
Connect to: /dev/ttys004
  screen /dev/ttys004 115200
  or point the Serial MCP server at this path.
```

## Quick start (UART — Raspberry Pi)

```bash
pip install pyserial

# Default: /dev/serial0 at 115200 baud
python3 uart_server.py

# Custom port and baud rate
python3 uart_server.py --port /dev/ttyAMA0
python3 uart_server.py --port /dev/ttyUSB0 --baud 9600
```

Connect from your dev machine using the USB-to-serial adapter port (e.g. `/dev/ttyUSB0` on Linux, `/dev/tty.usbserial-*` on macOS).

## Test with the Serial MCP server

```
serial.open  →  { "port": "/dev/ttys004" }
serial.write →  { "connection_id": "...", "data": "ping", "append_newline": true }
serial.readline → { "connection_id": "..." }
```

Type `help` to see all available commands.

## Protocol spec

See [demo-device-spec.md](demo-device-spec.md). Register it with the MCP server:

```
serial.spec.register  →  { "path": "examples/demo-device/demo-device-spec.md" }
```

## Plugin

See [demo_device_plugin.py](demo_device_plugin.py). Copy it to `.serial_mcp/plugins/` and load it:

```
serial.plugin.load  →  { "path": ".serial_mcp/plugins/demo_device_plugin.py" }
```
