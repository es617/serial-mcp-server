---
kind: serial-protocol
name: UartDemo Protocol
device_name_contains: UartDemo
connection:
  baudrate: 115200
  bytesize: 8
  parity: "N"
  stopbits: 1
  newline: "\r\n"
---

# UartDemo Protocol

Simulated serial device for testing the Serial MCP server.

## Connection

- **Baud rate:** 115200
- **Data bits:** 8
- **Parity:** None
- **Stop bits:** 1
- **Line terminator:** `\r\n`

## Line protocol

- Commands are single-line, terminated with `\r\n`.
- Responses are one or more lines, each terminated with `\r\n`.
- After every response, the device prints the prompt `> ` (greater-than followed by a space).
- The prompt indicates the device is ready for the next command.
- Prefixed lines (`[LOG]`, `[SAMPLE]`, `[BOOT]`) are asynchronous output — they may appear between the prompt and the next command.

## Boot sequence

On power-up (or after `reboot` / `factory-reset`), the device prints:

```
[BOOT] UartDemo v1.0.0
[BOOT] Ready.
>
```

---

## Commands

### help

List all available commands.

```
> help
Available commands:
  help                 Show this help message
  version              Show firmware version
  ...
>
```

### version

Print firmware version string.

```
> version
UartDemo v1.0.0
>
```

### uptime

Print device uptime in seconds.

```
> uptime
1234s
>
```

### ping

Simple connectivity test.

```
> ping
pong
>
```

### echo \<text\>

Echo text back verbatim. Useful for testing write + readline.

```
> echo Hello world
Hello world
>
```

### status

Print device status as a single JSON line.

```
> status
{"state":"idle","temp":42.3,"uptime":1234,"logs_enabled":false,"authenticated":false}
>
```

Fields:
- `state`: `"idle"`, `"logging"`, or `"sampling"`
- `temp`: current temperature reading (float)
- `uptime`: seconds since boot (int)
- `logs_enabled`: whether periodic logging is active (bool)
- `authenticated`: whether the session is authenticated (bool)

### config get [key]

Get all configuration values (no key) or a single key.

```
> config get
{"log_interval_ms":1000,"sample_rate_hz":10,"device_name":"UartDemo"}
> config get log_interval_ms
{"log_interval_ms":1000}
>
```

### config set \<key\> \<value\>

Set a configuration value.

```
> config set log_interval_ms 500
OK log_interval_ms=500
>
```

Valid keys and ranges:
- `log_interval_ms`: 100–10000 (int)
- `sample_rate_hz`: 1–100 (int)
- `device_name`: any string

### log start [interval_ms]

Start periodic log output. Optionally set the interval (overrides `log_interval_ms` config).

```
> log start
OK logs started (interval=1000ms)
> [LOG] 14:32:01 temp=42.1 humidity=65.3 pressure=1013.2
[LOG] 14:32:02 temp=41.8 humidity=65.5 pressure=1013.0
```

Log lines have the format:
```
[LOG] HH:MM:SS temp=<float> humidity=<float> pressure=<float>
```

Log lines are emitted asynchronously — they appear even while the device is waiting for commands. The prompt is still valid; just send a command and the device will respond.

### log stop

Stop periodic logging.

```
> log stop
OK logs stopped
>
```

### sample \<count\>

Collect a fixed number of sensor samples and then stop. The device emits one line per sample, then a `DONE` marker.

```
> sample 3
OK sampling 3 at 10Hz
[SAMPLE] 1/3 temp=42.1 humidity=65.2
[SAMPLE] 2/3 temp=41.9 humidity=65.4
[SAMPLE] 3/3 temp=42.3 humidity=65.0
[SAMPLE] DONE
>
```

Use `read_until` with delimiter `DONE` to collect all samples in one call. The sample rate is controlled by `config set sample_rate_hz`. Count must be 1–1000.

### auth \<password\>

Authenticate the session. Required for `secret` and `factory-reset`.

```
> auth demo1234
OK authenticated
> auth wrong
ERROR: wrong password
>
```

The password is `demo1234`.

### secret

Read a secret value. Requires authentication.

```
> secret
ERROR: not authenticated
> auth demo1234
OK authenticated
> secret
The answer is 42.
>
```

### factory-reset

Reset the device to defaults. Requires authentication. Resets config, clears auth, stops logging/sampling, and reboots.

```
> factory-reset
OK factory reset
[BOOT] UartDemo v1.0.0
[BOOT] Ready.
>
```

### reboot

Reboot the device. Stops all activity, pauses ~1 second, then prints the boot banner.

```
> reboot
Rebooting...
[BOOT] UartDemo v1.0.0
[BOOT] Ready.
>
```

## Error handling

Unknown commands:
```
> foo
ERROR: unknown command 'foo'. Type 'help' for available commands.
>
```

Wrong arguments:
```
> config set
ERROR: usage: config set <key> <value>
>
```

## Multi-step flows

### Authenticate and read secret

1. `auth demo1234` → `OK authenticated`
2. `secret` → `The answer is 42.`

### Configure and collect samples

1. `config set sample_rate_hz 5` → `OK sample_rate_hz=5`
2. `sample 10` → 10 sample lines + `[SAMPLE] DONE`

### Start logging, send commands, stop logging

1. `log start 2000` → `OK logs started (interval=2000ms)`
2. `ping` → `pong` (log lines may appear between prompt and response)
3. `log stop` → `OK logs stopped`
