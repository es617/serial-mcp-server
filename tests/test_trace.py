"""Tests for serial_mcp_server.trace — no serial hardware required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from serial_mcp_server.trace import TraceBuffer, sanitize_args

# ---------------------------------------------------------------------------
# TraceBuffer basics
# ---------------------------------------------------------------------------


class TestTraceBuffer:
    def test_emit_and_tail(self):
        buf = TraceBuffer()
        buf.emit({"event": "test", "data": 1})
        buf.emit({"event": "test", "data": 2})
        events = buf.tail()
        assert len(events) == 2
        assert events[0]["data"] == 1
        assert events[1]["data"] == 2
        # Each event gets a timestamp
        assert "ts" in events[0]
        assert "ts" in events[1]

    def test_tail_limit(self):
        buf = TraceBuffer()
        for i in range(10):
            buf.emit({"event": "test", "data": i})
        events = buf.tail(3)
        assert len(events) == 3
        assert events[0]["data"] == 7
        assert events[2]["data"] == 9

    def test_status(self):
        buf = TraceBuffer()
        buf.emit({"event": "test"})
        status = buf.status()
        assert status["enabled"] is True
        assert status["event_count"] == 1
        assert status["file_path"] is None

    def test_ring_buffer_eviction(self):
        buf = TraceBuffer(max_items=5)
        for i in range(10):
            buf.emit({"event": "test", "data": i})
        events = buf.tail(10)
        assert len(events) == 5
        assert events[0]["data"] == 5
        assert events[4]["data"] == 9

    def test_rejects_symlink_path(self, tmp_path: Path):
        real_file = tmp_path / "real.jsonl"
        real_file.touch()
        link = tmp_path / "link.jsonl"
        link.symlink_to(real_file)
        # On POSIX: os.open with O_NOFOLLOW raises OSError
        # On Windows (no O_NOFOLLOW): falls back to check-then-open raising ValueError
        with pytest.raises((OSError, ValueError)):
            TraceBuffer(file_path=str(link))

    def test_file_sink(self, tmp_path: Path):
        trace_file = tmp_path / "trace.jsonl"
        buf = TraceBuffer(file_path=str(trace_file))
        buf.emit({"event": "test", "data": "hello"})
        buf.emit({"event": "test", "data": "world"})
        buf.close()

        lines = trace_file.read_text().strip().splitlines()
        assert len(lines) == 2
        parsed = json.loads(lines[0])
        assert parsed["event"] == "test"
        assert parsed["data"] == "hello"
        assert "ts" in parsed
        parsed2 = json.loads(lines[1])
        assert parsed2["data"] == "world"

    def test_close_idempotent(self, tmp_path: Path):
        trace_file = tmp_path / "trace.jsonl"
        buf = TraceBuffer(file_path=str(trace_file))
        buf.close()
        buf.close()  # Should not raise


# ---------------------------------------------------------------------------
# sanitize_args
# ---------------------------------------------------------------------------


class TestSanitizeArgs:
    def test_strips_payloads_when_disabled(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_PAYLOADS", False)
        args = {"connection_id": "c1", "data": "hello world", "as": "text"}
        result = sanitize_args(args)
        assert "data" not in result
        assert result["connection_id"] == "c1"
        assert result["as"] == "text"

    def test_passes_through_non_payload_args(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_PAYLOADS", False)
        args = {"connection_id": "c1", "timeout_ms": 500}
        result = sanitize_args(args)
        assert result == args

    def test_truncates_when_payloads_enabled(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_PAYLOADS", True)
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_MAX_BYTES", 10)
        args = {"data": "A" * 20}
        result = sanitize_args(args)
        assert result["data"] == "A" * 10 + "\u2026"

    def test_no_truncation_when_under_limit(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_PAYLOADS", True)
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_MAX_BYTES", 100)
        args = {"data": "0102"}
        result = sanitize_args(args)
        assert result["data"] == "0102"

    def test_deep_copy(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_PAYLOADS", False)
        args = {"connection_id": "c1", "nested": {"a": 1}}
        result = sanitize_args(args)
        result["nested"]["a"] = 999
        assert args["nested"]["a"] == 1  # Original not mutated


# ---------------------------------------------------------------------------
# init_trace
# ---------------------------------------------------------------------------


class TestInitTrace:
    def test_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_ENABLED", False)
        monkeypatch.setattr("serial_mcp_server.trace._buffer", None)
        from serial_mcp_server.trace import init_trace

        result = init_trace()
        assert result is None

    def test_creates_buffer_when_enabled(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("serial_mcp_server.trace.TRACE_ENABLED", True)
        monkeypatch.setattr("serial_mcp_server.trace._buffer", None)
        spec_root = tmp_path / ".serial_mcp"
        monkeypatch.setenv("SERIAL_MCP_SPEC_ROOT", str(spec_root))
        from serial_mcp_server.trace import get_trace_buffer, init_trace

        buf = init_trace()
        assert buf is not None
        assert buf is get_trace_buffer()
        trace_file = spec_root / "traces" / "trace.jsonl"
        assert trace_file.parent.is_dir()
        buf.close()
        # Reset global
        monkeypatch.setattr("serial_mcp_server.trace._buffer", None)


# ---------------------------------------------------------------------------
# Handler returns enabled=False when tracing off
# ---------------------------------------------------------------------------


class TestHandlersTraceDisabled:
    @pytest.mark.asyncio
    async def test_status_disabled(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace._buffer", None)
        from serial_mcp_server.handlers_trace import handle_trace_status

        result = await handle_trace_status(None, {})
        assert result["ok"] is True
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_tail_disabled(self, monkeypatch):
        monkeypatch.setattr("serial_mcp_server.trace._buffer", None)
        from serial_mcp_server.handlers_trace import handle_trace_tail

        result = await handle_trace_tail(None, {})
        assert result["ok"] is True
        assert result["enabled"] is False


class TestHandlersTraceEnabled:
    @pytest.mark.asyncio
    async def test_status_enabled(self, monkeypatch):
        buf = TraceBuffer()
        buf.emit({"event": "test"})
        monkeypatch.setattr("serial_mcp_server.trace._buffer", buf)
        from serial_mcp_server.handlers_trace import handle_trace_status

        result = await handle_trace_status(None, {})
        assert result["ok"] is True
        assert result["enabled"] is True
        assert result["event_count"] == 1

    @pytest.mark.asyncio
    async def test_tail_enabled(self, monkeypatch):
        buf = TraceBuffer()
        buf.emit({"event": "test", "data": 42})
        monkeypatch.setattr("serial_mcp_server.trace._buffer", buf)
        from serial_mcp_server.handlers_trace import handle_trace_tail

        result = await handle_trace_tail(None, {"n": 10})
        assert result["ok"] is True
        assert len(result["events"]) == 1
        assert result["events"][0]["data"] == 42
