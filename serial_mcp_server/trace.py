"""JSONL tracing for Serial MCP tool calls.

In-memory ring buffer with optional file sink. Tracing is on by default;
set ``SERIAL_MCP_TRACE=0`` to disable.  No serial imports.
"""

from __future__ import annotations

import collections
import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration (read at import time, same pattern as helpers.py)
# ---------------------------------------------------------------------------

TRACE_ENABLED = os.environ.get("SERIAL_MCP_TRACE", "1").lower() not in ("0", "false", "no")
TRACE_PAYLOADS = os.environ.get("SERIAL_MCP_TRACE_PAYLOADS", "").lower() in ("1", "true", "yes")
TRACE_MAX_BYTES = int(os.environ.get("SERIAL_MCP_TRACE_MAX_BYTES", "16384"))

# ---------------------------------------------------------------------------
# Sanitize args
# ---------------------------------------------------------------------------

_PAYLOAD_KEYS = {"data"}


def sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *args* with payload values stripped or truncated."""
    out = copy.deepcopy(args)
    for key in _PAYLOAD_KEYS:
        if key not in out:
            continue
        if not TRACE_PAYLOADS:
            del out[key]
        else:
            val = out[key]
            if isinstance(val, str) and len(val) > TRACE_MAX_BYTES:
                out[key] = val[:TRACE_MAX_BYTES] + "\u2026"
    return out


# ---------------------------------------------------------------------------
# TraceBuffer
# ---------------------------------------------------------------------------


class TraceBuffer:
    """Ring buffer of trace events with optional JSONL file sink."""

    def __init__(self, max_items: int = 2000, file_path: str | None = None) -> None:
        self._deque: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_items)
        self._file_path = file_path
        self._fh = None
        if file_path:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            # Open atomically without following symlinks (TOCTOU-safe)
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            if nofollow:
                fd = os.open(file_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | nofollow, 0o644)
                self._fh = os.fdopen(fd, "a", encoding="utf-8")
            else:
                # O_NOFOLLOW unavailable (Windows) — fall back to check-then-open
                if p.is_symlink():
                    raise ValueError(f"Trace path is a symlink (refusing to follow): {file_path}")
                self._fh = open(file_path, "a", encoding="utf-8")  # noqa: SIM115

    def emit(self, event: dict[str, Any]) -> None:
        event["ts"] = datetime.now(UTC).isoformat()
        self._deque.append(event)
        if self._fh:
            self._fh.write(json.dumps(event, default=str) + "\n")
            self._fh.flush()

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        items = list(self._deque)
        return items[-n:]

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "event_count": len(self._deque),
            "file_path": self._file_path,
            "payloads_logged": TRACE_PAYLOADS,
            "max_payload_bytes": TRACE_MAX_BYTES,
        }

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def __del__(self) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_buffer: TraceBuffer | None = None


def get_trace_buffer() -> TraceBuffer | None:
    return _buffer


def init_trace() -> TraceBuffer | None:
    """Called once at startup. Returns buffer if tracing enabled, else None."""
    global _buffer
    if not TRACE_ENABLED:
        return None
    from serial_mcp_server.specs import resolve_spec_root

    path = str(resolve_spec_root() / "traces" / "trace.jsonl")
    _buffer = TraceBuffer(file_path=path)
    return _buffer
