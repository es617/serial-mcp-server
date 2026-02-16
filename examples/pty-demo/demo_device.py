#!/usr/bin/env python3
"""Demo serial device using a pty pair.

Creates a virtual serial port for local testing on macOS/Linux.
No external dependencies — pure stdlib.

Usage:
    python3 demo_device.py

Then connect the Serial MCP server (or screen/minicom) to the
printed slave path.
"""

from __future__ import annotations

import json
import os
import random
import select
import termios
import time
import tty

# ---------------------------------------------------------------------------
# Device simulator
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
PASSWORD = "demo1234"

DEFAULT_CONFIG = {
    "log_interval_ms": 1000,
    "sample_rate_hz": 10,
    "device_name": "DemoDevice",
}

CONFIG_VALIDATORS: dict[str, tuple[type, int | None, int | None]] = {
    "log_interval_ms": (int, 100, 10000),
    "sample_rate_hz": (int, 1, 100),
    "device_name": (str, None, None),
}


class DemoDevice:
    """Simulated serial device with a CLI command interface."""

    def __init__(self, send_fn):
        self._send = send_fn
        self._buf = b""
        self._authenticated = False
        self._logging = False
        self._last_log_ts = 0.0
        self._sampling = False
        self._sample_count = 0
        self._samples_sent = 0
        self._last_sample_ts = 0.0
        self._start_time = time.time()
        self._config = dict(DEFAULT_CONFIG)

    # -- I/O helpers --------------------------------------------------------

    def _write(self, text: str) -> None:
        self._send((text + "\r\n").encode())

    def _prompt(self) -> None:
        self._send(b"> ")

    # -- Public interface ---------------------------------------------------

    def boot(self) -> None:
        self._write(f"[BOOT] DemoDevice v{VERSION}")
        self._write("[BOOT] Ready.")
        self._prompt()

    def feed(self, data: bytes) -> None:
        """Feed raw bytes from the serial port. Buffers until a line terminator."""
        self._buf += data
        while True:
            # Accept \r\n, \n, or bare \r as line terminators.
            idx_rn = self._buf.find(b"\r\n")
            idx_n = self._buf.find(b"\n")
            idx_r = self._buf.find(b"\r")

            candidates = []
            if idx_rn != -1:
                candidates.append((idx_rn, 2))
            if idx_n != -1 and (idx_rn == -1 or idx_n < idx_rn):
                candidates.append((idx_n, 1))
            if idx_r != -1 and idx_rn != idx_r and (idx_rn == -1 or idx_r < idx_rn):
                candidates.append((idx_r, 1))

            if not candidates:
                break

            idx, sep_len = min(candidates, key=lambda c: c[0])
            # If we found a bare \r and the next byte could be \n, wait for more data.
            if sep_len == 1 and self._buf[idx : idx + 1] == b"\r" and idx + 1 == len(self._buf):
                break

            line = self._buf[:idx].decode(errors="replace").strip()
            self._buf = self._buf[idx + sep_len :]

            if line:
                self._handle_command(line)
            else:
                self._prompt()

    def tick(self) -> None:
        """Called periodically from the main loop."""
        now = time.time()

        if self._logging:
            interval = self._config["log_interval_ms"] / 1000.0
            if now - self._last_log_ts >= interval:
                self._last_log_ts = now
                self._emit_log()

        if self._sampling and self._samples_sent < self._sample_count:
            interval = 1.0 / self._config["sample_rate_hz"]
            if now - self._last_sample_ts >= interval:
                self._last_sample_ts = now
                self._samples_sent += 1
                temp = 42.0 + random.uniform(-0.5, 0.5)
                humidity = 65.0 + random.uniform(-1.0, 1.0)
                self._write(
                    f"[SAMPLE] {self._samples_sent}/{self._sample_count} "
                    f"temp={temp:.1f} humidity={humidity:.1f}"
                )
                if self._samples_sent >= self._sample_count:
                    self._sampling = False
                    self._write("[SAMPLE] DONE")
                    self._prompt()

    # -- Sensor simulation --------------------------------------------------

    def _emit_log(self) -> None:
        ts = time.strftime("%H:%M:%S")
        temp = 42.0 + random.uniform(-0.5, 0.5)
        humidity = 65.0 + random.uniform(-1.0, 1.0)
        pressure = 1013.0 + random.uniform(-0.5, 0.5)
        self._write(f"[LOG] {ts} temp={temp:.1f} humidity={humidity:.1f} pressure={pressure:.1f}")

    # -- Command dispatch ---------------------------------------------------

    def _handle_command(self, line: str) -> None:
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        commands = {
            "help": self._cmd_help,
            "version": self._cmd_version,
            "uptime": self._cmd_uptime,
            "ping": self._cmd_ping,
            "echo": self._cmd_echo,
            "status": self._cmd_status,
            "config": self._cmd_config,
            "log": self._cmd_log,
            "sample": self._cmd_sample,
            "auth": self._cmd_auth,
            "secret": self._cmd_secret,
            "factory-reset": self._cmd_factory_reset,
            "reboot": self._cmd_reboot,
        }

        handler = commands.get(cmd)
        if handler:
            handler(rest)
        else:
            self._write(f"ERROR: unknown command '{cmd}'. Type 'help' for available commands.")
            self._prompt()

    # -- Command implementations --------------------------------------------

    def _cmd_help(self, _args: str) -> None:
        self._write("Available commands:")
        self._write("  help                 Show this help message")
        self._write("  version              Show firmware version")
        self._write("  uptime               Show device uptime")
        self._write("  ping                 Respond with 'pong'")
        self._write("  echo <text>          Echo text back")
        self._write("  status               Show device status (JSON)")
        self._write("  config get [key]     Get configuration")
        self._write("  config set <k> <v>   Set configuration value")
        self._write("  log start [ms]       Start periodic logging")
        self._write("  log stop             Stop logging")
        self._write("  sample <count>       Collect sensor samples")
        self._write("  auth <password>      Authenticate for privileged commands")
        self._write("  secret               Show secret (requires auth)")
        self._write("  factory-reset        Factory reset (requires auth)")
        self._write("  reboot               Reboot device")
        self._prompt()

    def _cmd_version(self, _args: str) -> None:
        self._write(f"DemoDevice v{VERSION}")
        self._prompt()

    def _cmd_uptime(self, _args: str) -> None:
        self._write(f"{int(time.time() - self._start_time)}s")
        self._prompt()

    def _cmd_ping(self, _args: str) -> None:
        self._write("pong")
        self._prompt()

    def _cmd_echo(self, args: str) -> None:
        self._write(args)
        self._prompt()

    def _cmd_status(self, _args: str) -> None:
        status = {
            "state": "sampling" if self._sampling else ("logging" if self._logging else "idle"),
            "temp": round(42.0 + random.uniform(-0.5, 0.5), 1),
            "uptime": int(time.time() - self._start_time),
            "logs_enabled": self._logging,
            "authenticated": self._authenticated,
        }
        self._write(json.dumps(status))
        self._prompt()

    def _cmd_config(self, args: str) -> None:
        parts = args.split(None, 2)
        if not parts:
            self._write("ERROR: usage: config get [key] | config set <key> <value>")
            self._prompt()
            return

        subcmd = parts[0].lower()

        if subcmd == "get":
            if len(parts) == 1:
                self._write(json.dumps(self._config))
            elif parts[1] in self._config:
                self._write(json.dumps({parts[1]: self._config[parts[1]]}))
            else:
                self._write(f"ERROR: unknown key '{parts[1]}'")
            self._prompt()

        elif subcmd == "set":
            if len(parts) < 3:
                self._write("ERROR: usage: config set <key> <value>")
                self._prompt()
                return

            key = parts[1]
            raw_value = parts[2]

            if key not in CONFIG_VALIDATORS:
                self._write(f"ERROR: unknown key '{key}'. Valid keys: {', '.join(CONFIG_VALIDATORS)}")
                self._prompt()
                return

            vtype, vmin, vmax = CONFIG_VALIDATORS[key]
            try:
                value = vtype(raw_value)
            except (ValueError, TypeError):
                self._write(f"ERROR: invalid value '{raw_value}' for {key} (expected {vtype.__name__})")
                self._prompt()
                return

            if vmin is not None and value < vmin:
                self._write(f"ERROR: {key} must be >= {vmin}")
                self._prompt()
                return
            if vmax is not None and value > vmax:
                self._write(f"ERROR: {key} must be <= {vmax}")
                self._prompt()
                return

            self._config[key] = value
            self._write(f"OK {key}={value}")
            self._prompt()

        else:
            self._write("ERROR: usage: config get [key] | config set <key> <value>")
            self._prompt()

    def _cmd_log(self, args: str) -> None:
        parts = args.split()
        if not parts:
            self._write("ERROR: usage: log start [interval_ms] | log stop")
            self._prompt()
            return

        subcmd = parts[0].lower()

        if subcmd == "start":
            if len(parts) > 1:
                try:
                    ms = int(parts[1])
                    if 100 <= ms <= 10000:
                        self._config["log_interval_ms"] = ms
                    else:
                        self._write("ERROR: interval must be 100-10000 ms")
                        self._prompt()
                        return
                except ValueError:
                    self._write(f"ERROR: invalid interval '{parts[1]}'")
                    self._prompt()
                    return
            self._logging = True
            self._last_log_ts = time.time()
            self._write(f"OK logs started (interval={self._config['log_interval_ms']}ms)")
            self._prompt()

        elif subcmd == "stop":
            self._logging = False
            self._write("OK logs stopped")
            self._prompt()

        else:
            self._write("ERROR: usage: log start [interval_ms] | log stop")
            self._prompt()

    def _cmd_sample(self, args: str) -> None:
        parts = args.split()
        if not parts:
            self._write("ERROR: usage: sample <count>")
            self._prompt()
            return
        try:
            count = int(parts[0])
            if count < 1 or count > 1000:
                self._write("ERROR: count must be 1-1000")
                self._prompt()
                return
        except ValueError:
            self._write(f"ERROR: invalid count '{parts[0]}'")
            self._prompt()
            return

        self._sampling = True
        self._sample_count = count
        self._samples_sent = 0
        self._last_sample_ts = time.time()
        self._write(f"OK sampling {count} at {self._config['sample_rate_hz']}Hz")

    def _cmd_auth(self, args: str) -> None:
        password = args.strip()
        if not password:
            self._write("ERROR: usage: auth <password>")
            self._prompt()
            return
        if password == PASSWORD:
            self._authenticated = True
            self._write("OK authenticated")
        else:
            self._write("ERROR: wrong password")
        self._prompt()

    def _cmd_secret(self, _args: str) -> None:
        if not self._authenticated:
            self._write("ERROR: not authenticated")
        else:
            self._write("The answer is 42.")
        self._prompt()

    def _cmd_factory_reset(self, _args: str) -> None:
        if not self._authenticated:
            self._write("ERROR: not authenticated")
            self._prompt()
            return
        self._write("OK factory reset")
        self._authenticated = False
        self._logging = False
        self._sampling = False
        self._config = dict(DEFAULT_CONFIG)
        self._start_time = time.time()
        self.boot()

    def _cmd_reboot(self, _args: str) -> None:
        self._write("Rebooting...")
        self._logging = False
        self._sampling = False
        self._authenticated = False
        self._start_time = time.time()
        # Flush "Rebooting..." before the pause.
        time.sleep(1)
        self.boot()


# ---------------------------------------------------------------------------
# PTY transport
# ---------------------------------------------------------------------------


def main() -> None:
    master_fd, slave_fd = os.openpty()
    slave_path = os.ttyname(slave_fd)

    # Put the slave side in raw mode and set baud rate.
    tty.setraw(slave_fd)
    # Restore baud to 115200 (B115200 = 0x1002 on macOS, termios has it).
    baud = termios.B115200
    attrs_raw = termios.tcgetattr(slave_fd)
    attrs_raw[4] = baud  # ispeed
    attrs_raw[5] = baud  # ospeed
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs_raw)

    print("DemoDevice pty ready.", flush=True)
    print(f"Connect to: {slave_path}", flush=True)
    print(f"  screen {slave_path} 115200", flush=True)
    print("  or point the Serial MCP server at this path.", flush=True)
    print(flush=True)

    def send(data: bytes) -> None:
        try:
            os.write(master_fd, data)
        except OSError:
            pass

    device = DemoDevice(send)
    device.boot()

    try:
        while True:
            readable, _, _ = select.select([master_fd], [], [], 0.05)
            if readable:
                try:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    device.feed(data)
                except OSError:
                    break
            device.tick()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        os.close(master_fd)
        os.close(slave_fd)


if __name__ == "__main__":
    main()
