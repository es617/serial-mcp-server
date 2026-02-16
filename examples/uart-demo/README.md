# UART Demo Device

A simulated serial device that runs on a real UART port. Designed for Raspberry Pi but works with any serial port.

## Requirements

- Python 3.11+
- pyserial: `pip install pyserial`
- A serial port (Raspberry Pi UART, USB-to-serial adapter, etc.)

## Raspberry Pi setup

### 1. Enable UART

```bash
sudo raspi-config
```

Navigate to: **Interface Options** → **Serial Port** → **No** (login shell) → **Yes** (hardware enabled).

Reboot after changing settings.

### 2. Wiring

Connect the Pi to your dev machine using a USB-to-serial adapter:

```
Raspberry Pi                  USB-to-Serial Adapter
─────────────                 ─────────────────────
TX  (GPIO14, pin 8)  ──────► RX
RX  (GPIO15, pin 10) ◄────── TX
GND (pin 6)          ──────── GND
```

**Do not connect VCC/5V** unless you know the adapter expects it. Most USB adapters are self-powered.

### 3. Run the demo device

```bash
python3 uart_server.py
```

Default port is `/dev/serial0` at 115200 baud.

### 4. Connect from your dev machine

The USB-to-serial adapter appears as `/dev/ttyUSB0` (Linux) or `/dev/tty.usbserial-*` (macOS):

```
serial.open  →  { "port": "/dev/ttyUSB0" }
serial.write →  { "connection_id": "...", "data": "ping", "append_newline": true }
serial.readline → { "connection_id": "..." }
```

## Usage

```bash
# Default: /dev/serial0 at 115200 baud
python3 uart_server.py

# Custom port and baud rate
python3 uart_server.py --port /dev/ttyAMA0
python3 uart_server.py --port /dev/ttyUSB0 --baud 9600
```

## Protocol

See [uart-demo-spec.md](uart-demo-spec.md) for the full protocol spec. Register it with the MCP server:

```
serial.spec.register  →  { "path": "examples/uart-demo/uart-demo-spec.md" }
```
