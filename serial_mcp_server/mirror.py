"""Serial port buffering and PTY mirroring.

Provides:
- ``SerialBuffer``: thread-safe byte buffer with blocking reads
- ``ReaderThread``: background thread that reads from serial into buffer
- ``MirrorSession``: extends ReaderThread with PTY tee (Unix only)
- ``create_reader``: factory that picks the right reader based on config
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any

logger = logging.getLogger("serial_mcp_server")

_IS_UNIX = sys.platform != "win32"

if _IS_UNIX:
    import select
    import termios
    import tty


# ---------------------------------------------------------------------------
# SerialBuffer — thread-safe byte buffer
# ---------------------------------------------------------------------------


class SerialBuffer:
    """Thread-safe byte buffer with blocking reads.

    The background reader writes into this buffer. MCP tool handlers
    read from it.
    """

    def __init__(self, max_size: int = 1_048_576) -> None:
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._max_size = max_size

    def write(self, data: bytes) -> None:
        """Append data to the buffer and wake any waiting readers."""
        if not data:
            return
        with self._cond:
            self._buf.extend(data)
            # Trim from the front if we exceed max size (drop oldest data).
            if len(self._buf) > self._max_size:
                excess = len(self._buf) - self._max_size
                del self._buf[:excess]
            self._cond.notify_all()

    def read(self, nbytes: int, timeout: float) -> bytes:
        """Read up to *nbytes*, blocking until data arrives or *timeout* expires."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while not self._buf:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self._cond.wait(timeout=remaining)
            n = min(nbytes, len(self._buf))
            result = bytes(self._buf[:n])
            del self._buf[:n]
            return result

    def read_until(self, delimiter: bytes, max_bytes: int, timeout: float) -> bytes:
        """Read until *delimiter* is found, *max_bytes* reached, or *timeout* expires."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                idx = self._buf.find(delimiter)
                if idx != -1:
                    end = min(idx + len(delimiter), max_bytes)
                    result = bytes(self._buf[:end])
                    del self._buf[:end]
                    return result
                if len(self._buf) >= max_bytes:
                    result = bytes(self._buf[:max_bytes])
                    del self._buf[:max_bytes]
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Return whatever we have.
                    n = min(len(self._buf), max_bytes)
                    result = bytes(self._buf[:n])
                    del self._buf[:n]
                    return result
                self._cond.wait(timeout=remaining)

    def clear(self) -> None:
        """Discard all buffered data."""
        with self._lock:
            self._buf.clear()

    @property
    def available(self) -> int:
        """Number of bytes currently in the buffer."""
        with self._lock:
            return len(self._buf)


# ---------------------------------------------------------------------------
# ReaderThread — background serial reader (cross-platform)
# ---------------------------------------------------------------------------


class ReaderThread:
    """Background thread that continuously reads from a serial port into a buffer."""

    def __init__(self, ser: Any, buffer: SerialBuffer) -> None:
        self.ser = ser
        self.buffer = buffer
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.write_lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="serial-reader")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    _MAX_CONSECUTIVE_ERRORS = 10

    def _run(self) -> None:
        errors = 0
        while not self._stop.is_set():
            try:
                waiting = self.ser.in_waiting
                if waiting:
                    data = self.ser.read(waiting)
                    if data:
                        self._on_data(data)
                else:
                    # Block for up to 1 byte with the serial port's own timeout.
                    data = self.ser.read(1)
                    if data:
                        self._on_data(data)
                errors = 0
            except Exception:
                if self._stop.is_set():
                    break
                errors += 1
                if errors >= self._MAX_CONSECUTIVE_ERRORS:
                    logger.warning(
                        "Reader thread for %s stopping after %d consecutive errors.", self.ser.port, errors
                    )
                    break
                time.sleep(0.1)

    def _on_data(self, data: bytes) -> None:
        """Called when data arrives from the serial port. Override to tee."""
        self.buffer.write(data)

    def mirror_info(self) -> dict[str, Any] | None:
        """Return mirror metadata, or None if this is a plain reader."""
        return None


# ---------------------------------------------------------------------------
# MirrorSession — PTY tee on top of ReaderThread (Unix only)
# ---------------------------------------------------------------------------


class MirrorSession(ReaderThread):
    """Background reader that also tees serial data to a PTY.

    In rw mode, data written to the PTY slave by an external tool
    is forwarded to the real serial port.
    """

    def __init__(
        self,
        ser: Any,
        buffer: SerialBuffer,
        mode: str,
        link_path: str | None = None,
    ) -> None:
        super().__init__(ser, buffer)
        self.mode = mode  # "ro" or "rw"
        self.link_path = link_path

        # Create PTY pair.
        self._master_fd, self._slave_fd = os.openpty()

        # Put slave in raw mode and set baud rate.
        try:
            tty.setraw(self._slave_fd)
            attrs = termios.tcgetattr(self._slave_fd)
            baud = getattr(termios, f"B{ser.baudrate}", termios.B115200)
            attrs[4] = baud  # ispeed
            attrs[5] = baud  # ospeed
            termios.tcsetattr(self._slave_fd, termios.TCSANOW, attrs)
        except Exception:
            pass  # Best-effort baud config.

        self.pty_slave_path: str = os.ttyname(self._slave_fd)
        self._mirror_index: int | None = None  # Set by create_reader if link is used.

        # Create symlink if requested.
        self._link_created = False
        if self.link_path:
            try:
                if os.path.islink(self.link_path) or os.path.exists(self.link_path):
                    os.unlink(self.link_path)
                os.symlink(self.pty_slave_path, self.link_path)
                self._link_created = True
            except OSError as exc:
                logger.warning("Failed to create mirror symlink %s: %s", self.link_path, exc)

    def stop(self) -> None:
        super().stop()
        # Clean up PTY and symlink.
        try:
            os.close(self._master_fd)
        except OSError:
            pass
        try:
            os.close(self._slave_fd)
        except OSError:
            pass
        if self._link_created and self.link_path:
            try:
                os.unlink(self.link_path)
                self._link_created = False
            except OSError:
                pass
        if self._mirror_index is not None:
            _release_mirror_index(self._mirror_index)
            self._mirror_index = None

    def _run(self) -> None:
        ser_fd = self.ser.fileno()
        read_fds = [ser_fd, self._master_fd] if self.mode == "rw" else [ser_fd]

        while not self._stop.is_set():
            try:
                readable, _, _ = select.select(read_fds, [], [], 0.05)
            except (OSError, ValueError):
                if self._stop.is_set():
                    break
                time.sleep(0.1)
                continue

            for fd in readable:
                if fd == ser_fd:
                    try:
                        waiting = self.ser.in_waiting
                        data = self.ser.read(waiting or 1)
                        if data:
                            self._on_data(data)
                    except Exception:
                        if self._stop.is_set():
                            return
                        time.sleep(0.1)

                elif fd == self._master_fd:
                    try:
                        pty_data = os.read(self._master_fd, 4096)
                        if pty_data:
                            with self.write_lock:
                                self.ser.write(pty_data)
                    except OSError:
                        pass  # PTY client disconnected.

    def _on_data(self, data: bytes) -> None:
        """Write to both the buffer and the PTY master."""
        self.buffer.write(data)
        try:
            os.write(self._master_fd, data)
        except OSError:
            pass  # PTY client not connected.

    def mirror_info(self) -> dict[str, Any] | None:
        return {
            "pty_path": self.pty_slave_path,
            "link": self.link_path,
            "mode": self.mode,
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_mirror_indices_lock = threading.Lock()
_mirror_indices_in_use: set[int] = set()


def _acquire_mirror_index() -> int:
    """Return the lowest available mirror index."""
    with _mirror_indices_lock:
        idx = 0
        while idx in _mirror_indices_in_use:
            idx += 1
        _mirror_indices_in_use.add(idx)
        return idx


def _release_mirror_index(idx: int) -> None:
    """Return a mirror index to the pool."""
    with _mirror_indices_lock:
        _mirror_indices_in_use.discard(idx)


def create_reader(
    ser: Any,
    buffer: SerialBuffer,
    mirror_mode: str,
    mirror_link_base: str | None,
) -> ReaderThread:
    """Create the appropriate reader for a serial connection.

    *mirror_mode*: ``"off"``, ``"ro"``, or ``"rw"``.
    """
    if mirror_mode == "off" or not _IS_UNIX:
        return ReaderThread(ser, buffer)

    link_path: str | None = None
    mirror_index: int | None = None
    if mirror_link_base:
        mirror_index = _acquire_mirror_index()
        link_path = f"{mirror_link_base}{mirror_index}"

    session = MirrorSession(ser, buffer, mode=mirror_mode, link_path=link_path)
    session._mirror_index = mirror_index
    return session
