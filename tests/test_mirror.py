"""Tests for serial_mcp_server.mirror — SerialBuffer, ReaderThread, MirrorSession."""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from serial_mcp_server.mirror import (
    ReaderThread,
    SerialBuffer,
    create_reader,
)

# MirrorSession is Unix-only
_IS_UNIX = sys.platform != "win32"
if _IS_UNIX:
    from serial_mcp_server.mirror import MirrorSession


# ---------------------------------------------------------------------------
# SerialBuffer
# ---------------------------------------------------------------------------


class TestSerialBuffer:
    def test_write_and_read(self):
        buf = SerialBuffer()
        buf.write(b"hello")
        result = buf.read(10, timeout=1.0)
        assert result == b"hello"

    def test_read_returns_up_to_nbytes(self):
        buf = SerialBuffer()
        buf.write(b"hello world")
        result = buf.read(5, timeout=1.0)
        assert result == b"hello"
        # Remainder stays in buffer
        result2 = buf.read(100, timeout=0.01)
        assert result2 == b" world"

    def test_read_timeout_empty(self):
        buf = SerialBuffer()
        start = time.monotonic()
        result = buf.read(10, timeout=0.05)
        elapsed = time.monotonic() - start
        assert result == b""
        assert elapsed >= 0.04

    def test_read_blocks_until_data(self):
        buf = SerialBuffer()

        def delayed_write():
            time.sleep(0.05)
            buf.write(b"data")

        t = threading.Thread(target=delayed_write)
        t.start()
        result = buf.read(10, timeout=1.0)
        t.join()
        assert result == b"data"

    def test_read_until_delimiter(self):
        buf = SerialBuffer()
        buf.write(b"line1\r\nline2\r\n")
        result = buf.read_until(b"\r\n", max_bytes=100, timeout=1.0)
        assert result == b"line1\r\n"

    def test_read_until_max_bytes(self):
        buf = SerialBuffer()
        buf.write(b"a very long line without newline")
        result = buf.read_until(b"\n", max_bytes=10, timeout=0.05)
        assert result == b"a very lon"
        assert len(result) == 10

    def test_read_until_timeout(self):
        buf = SerialBuffer()
        buf.write(b"no newline here")
        result = buf.read_until(b"\n", max_bytes=1000, timeout=0.05)
        assert result == b"no newline here"

    def test_read_until_blocks_until_delimiter(self):
        buf = SerialBuffer()

        def delayed_write():
            time.sleep(0.05)
            buf.write(b"hello\n")

        t = threading.Thread(target=delayed_write)
        t.start()
        result = buf.read_until(b"\n", max_bytes=100, timeout=1.0)
        t.join()
        assert result == b"hello\n"

    def test_clear(self):
        buf = SerialBuffer()
        buf.write(b"data")
        assert buf.available == 4
        buf.clear()
        assert buf.available == 0

    def test_available(self):
        buf = SerialBuffer()
        assert buf.available == 0
        buf.write(b"abc")
        assert buf.available == 3

    def test_max_size_trims_oldest(self):
        buf = SerialBuffer(max_size=10)
        buf.write(b"0123456789")
        assert buf.available == 10
        buf.write(b"AB")
        assert buf.available == 10
        result = buf.read(10, timeout=0.01)
        assert result == b"23456789AB"

    def test_write_empty_noop(self):
        buf = SerialBuffer()
        buf.write(b"")
        assert buf.available == 0

    def test_concurrent_write_read(self):
        """Multiple writers + one reader, no crashes."""
        buf = SerialBuffer()
        total_written = 0
        lock = threading.Lock()

        def writer(chunk: bytes, count: int):
            nonlocal total_written
            for _ in range(count):
                buf.write(chunk)
                with lock:
                    total_written += len(chunk)
                time.sleep(0.001)

        threads = [
            threading.Thread(target=writer, args=(b"A" * 10, 50)),
            threading.Thread(target=writer, args=(b"B" * 10, 50)),
        ]
        for t in threads:
            t.start()

        read_total = 0
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            data = buf.read(100, timeout=0.01)
            read_total += len(data)
            if read_total >= 1000:
                break

        for t in threads:
            t.join()

        # Drain remaining
        remaining = buf.read(10000, timeout=0.01)
        read_total += len(remaining)
        assert read_total == total_written


# ---------------------------------------------------------------------------
# ReaderThread
# ---------------------------------------------------------------------------


class TestReaderThread:
    def test_data_flows_to_buffer(self):
        buf = SerialBuffer()
        ser = MagicMock()
        type(ser).in_waiting = PropertyMock(side_effect=[5, 0, 0, 0])
        ser.read.side_effect = [b"hello", b"", b"", b""]

        reader = ReaderThread(ser, buf)
        reader.start()
        time.sleep(0.1)
        reader.stop()

        assert buf.available >= 5
        assert buf.read(5, timeout=0.01) == b"hello"

    def test_start_stop(self):
        buf = SerialBuffer()
        ser = MagicMock()
        type(ser).in_waiting = PropertyMock(return_value=0)
        ser.read.return_value = b""

        reader = ReaderThread(ser, buf)
        reader.start()
        assert reader.alive
        reader.stop()
        assert not reader.alive

    def test_mirror_info_returns_none(self):
        buf = SerialBuffer()
        ser = MagicMock()
        reader = ReaderThread(ser, buf)
        assert reader.mirror_info() is None

    def test_has_write_lock(self):
        buf = SerialBuffer()
        ser = MagicMock()
        reader = ReaderThread(ser, buf)
        assert hasattr(reader, "write_lock")
        assert isinstance(reader.write_lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# MirrorSession (Unix only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _IS_UNIX, reason="PTY mirror requires Unix")
class TestMirrorSession:
    def test_creates_pty(self):
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        mirror = MirrorSession(ser, buf, mode="ro")
        try:
            assert mirror.pty_slave_path
            assert os.path.exists(mirror.pty_slave_path)
            assert mirror.mode == "ro"
        finally:
            mirror.stop()

    def test_mirror_info(self):
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        mirror = MirrorSession(ser, buf, mode="rw")
        try:
            info = mirror.mirror_info()
            assert info is not None
            assert "pty_path" in info
            assert info["mode"] == "rw"
            assert info["link"] is None
        finally:
            mirror.stop()

    def test_symlink_creation(self, tmp_path):
        link = str(tmp_path / "testlink")
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        mirror = MirrorSession(ser, buf, mode="ro", link_path=link)
        try:
            assert os.path.islink(link)
            assert os.readlink(link) == mirror.pty_slave_path
        finally:
            mirror.stop()
        # Symlink cleaned up on stop
        assert not os.path.exists(link)

    def test_data_to_buffer_and_pty(self):
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        mirror = MirrorSession(ser, buf, mode="ro")
        try:
            # Simulate data arriving via _on_data
            mirror._on_data(b"test data")
            assert buf.read(100, timeout=0.01) == b"test data"
        finally:
            mirror.stop()

    def test_stop_cleans_up(self):
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        mirror = MirrorSession(ser, buf, mode="ro")
        mirror.stop()
        # PTY fds are closed, no error expected
        assert not mirror.alive


# ---------------------------------------------------------------------------
# create_reader factory
# ---------------------------------------------------------------------------


class TestCreateReader:
    def test_off_returns_reader_thread(self):
        ser = MagicMock()
        buf = SerialBuffer()
        reader = create_reader(ser, buf, "off", None)
        assert isinstance(reader, ReaderThread)
        assert not isinstance(reader, MirrorSession) if _IS_UNIX else True

    @pytest.mark.skipif(not _IS_UNIX, reason="PTY mirror requires Unix")
    def test_ro_returns_mirror_session(self):
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        reader = create_reader(ser, buf, "ro", None)
        try:
            assert isinstance(reader, MirrorSession)
            assert reader.mode == "ro"
        finally:
            reader.stop()

    @pytest.mark.skipif(not _IS_UNIX, reason="PTY mirror requires Unix")
    def test_rw_returns_mirror_session(self):
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        reader = create_reader(ser, buf, "rw", None)
        try:
            assert isinstance(reader, MirrorSession)
            assert reader.mode == "rw"
        finally:
            reader.stop()

    @pytest.mark.skipif(not _IS_UNIX, reason="PTY mirror requires Unix")
    def test_link_base_appends_index(self, tmp_path):
        ser = MagicMock()
        ser.baudrate = 115200
        buf = SerialBuffer()
        link_base = str(tmp_path / "ttyMCP")
        reader = create_reader(ser, buf, "ro", link_base)
        try:
            info = reader.mirror_info()
            assert info is not None
            assert info["link"].startswith(link_base)
        finally:
            reader.stop()

    def test_non_unix_always_returns_reader_thread(self):
        ser = MagicMock()
        buf = SerialBuffer()
        with patch("serial_mcp_server.mirror._IS_UNIX", False):
            reader = create_reader(ser, buf, "rw", None)
        assert type(reader) is ReaderThread
