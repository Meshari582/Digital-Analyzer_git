"""A Transport (see link.Transport) that replays a previously recorded byte
stream instead of talking to a real serial port.

This is what makes every layer above link.py drivable offline: `regression`
and `replay` both build a Link on top of a ReplayTransport loaded from a
file, and Link has no idea it isn't talking to real hardware - it only ever
sees bytes in, bytes out. Whatever it writes (ARM, CONFIG, ...) is not
inspected or reacted to; the recorded stream is simply what a real MCU
already said in response, replayed back in order.
"""

from __future__ import annotations

import threading
from pathlib import Path


class ReplayTransport:
    """In-memory Transport backed by a fixed byte stream, thread-safe since
    Link's reader thread and the caller's own thread both touch it.
    """

    def __init__(self, data: bytes = b""):
        self._lock = threading.Lock()
        self._incoming = bytearray(data)
        self.sent = bytearray()
        self.closed = False

    @classmethod
    def from_file(cls, path: str | Path) -> "ReplayTransport":
        return cls(Path(path).read_bytes())

    def feed(self, data: bytes) -> None:
        """Append more bytes as if the MCU had just sent them."""
        with self._lock:
            self._incoming.extend(data)

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._incoming)

    def read(self, size: int) -> bytes:
        with self._lock:
            chunk = bytes(self._incoming[:size])
            del self._incoming[: len(chunk)]
            return chunk

    def write(self, data: bytes) -> int:
        with self._lock:
            self.sent.extend(data)
        return len(data)

    def close(self) -> None:
        self.closed = True
