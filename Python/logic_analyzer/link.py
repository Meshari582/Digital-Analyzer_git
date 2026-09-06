"""Serial transport and capture orchestration for the logic analyzer link.

Owns the connection to the MCU: the background reader thread that feeds
incoming bytes into a protocol.FrameParser, the CONFIG/ARM/STATUS/REREAD
request/response exchanges, and the CRC/SEQ bookkeeping that decides when a
capture push needs to be re-requested with REREAD. protocol.py only knows
about bytes; this module is where "what a CONFIG/ARM/DATA exchange means as
a capture" lives - see its module docstring for the division of labour.

Two things intentionally live here rather than in protocol.py: checking a
received frame's VER against PROTOCOL_VERSION, and tracking SEQ continuity
across a capture's CAPTURE_INFO + DATA frames. Neither is a property of one
frame in isolation - both only make sense in the context of a whole
exchange, which is what this module models and protocol.py doesn't.
"""

from __future__ import annotations

import queue
import threading
import time
from enum import IntEnum
from typing import Protocol

from .capture import Capture
from .protocol import (
    CRCError,
    Frame,
    FrameParser,
    FrameType,
    ParseEvent,
    PROTOCOL_VERSION,
    ConfigPayload,
    CaptureInfoPayload,
    encode_config_payload,
    encode_frame,
    parse_capture_info_payload,
)


class Transport(Protocol):
    """Minimum shape Link needs from a serial connection - satisfied by
    serial.Serial, and by the in-memory fakes tests use instead of touching
    real hardware.
    """

    in_waiting: int

    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


class Status(IntEnum):
    """Decoded STATUS reply payload."""

    IDLE = 0
    ARMED = 1
    CAPTURED = 2


class LinkError(Exception):
    """Base class for errors this module raises."""


class RemoteError(LinkError):
    """The MCU rejected a request: an ERROR frame (reason is its ASCII
    payload) or a NAK (no reason text on the wire, so callers supply
    context - see NAK's row in the handoff type table for what it can mean
    for the request in question).
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ProtocolError(LinkError):
    """The frame stream desynced in a way REREAD retries didn't fix: a
    version mismatch, an unexpected frame type, or repeated CRC/SEQ failure
    on a capture push.
    """


class LinkTimeoutError(LinkError):
    """No frame arrived from the MCU within the expected window."""


class _CaptureDesync(Exception):
    """Internal signal: the DATA stream for the capture being drained broke
    (CRC error or SEQ gap). Caught by _receive_capture, which is the only
    thing that knows whether a REREAD retry is still available.
    """


class Link:
    """One connection to the MCU. Not thread-safe for concurrent callers -
    commands are serialized with an internal lock, but two threads calling
    e.g. arm() and status() at once will simply block on each other, which
    matches the MCU only ever having one exchange in flight at a time.

    Polarity is a physical switch on the board (see the CONFIG row of the
    handoff type table) - nothing on the PC side can change it, and this
    class doesn't pretend otherwise: configure() has no polarity parameter,
    it always tells the MCU to leave the switch alone.
    """

    _MAX_REREAD_RETRIES = 3

    def __init__(self, transport: Transport, *, command_timeout: float = 2.0):
        self._transport = transport
        self._command_timeout = command_timeout
        self._parser = FrameParser()
        self._events: "queue.Queue[ParseEvent]" = queue.Queue()
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    @classmethod
    def open_serial(cls, port: str, baudrate: int, **kwargs) -> "Link":
        """Convenience constructor for real hardware. Import is local so
        nothing in this module requires pyserial to be installed just to
        run against a fake transport in tests.
        """
        import serial

        return cls(serial.Serial(port, baudrate=baudrate, timeout=0.05), **kwargs)

    def close(self) -> None:
        """Stop the reader thread and close the transport.

        Transport closed before the join, not after: a transport whose
        read() genuinely blocks (no bounded timeout) only unblocks when the
        underlying port goes away out from under it - joining first would
        wait out the full timeout while the thread sits there regardless.
        open_serial's 0.05s pyserial read timeout means this rarely matters
        in practice, but a custom Transport isn't guaranteed to have one.
        """
        self._stop.set()
        self._transport.close()
        self._reader.join(timeout=1.0)

    def __enter__(self) -> "Link":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- transport -----------------------------------------------------

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._transport.read(self._transport.in_waiting or 1)
            except Exception:
                return
            if chunk:
                for event in self._parser.feed(chunk):
                    self._events.put(event)
            else:
                time.sleep(0.001)

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFFFF
        return seq

    def _send(self, frame_type: FrameType, payload: bytes = b"") -> int:
        seq = self._next_seq()
        self._transport.write(encode_frame(frame_type, seq, payload))
        return seq

    def _next_event(self, timeout: float) -> ParseEvent:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            raise LinkTimeoutError(f"no frame received within {timeout}s") from None

    def _next_frame(self, timeout: float) -> Frame:
        """Pull the next structurally-valid frame, checking VER along the
        way - PROTOCOL_VERSION enforcement against incoming frames lives
        here, not in protocol.py (protocol.py only knows about the bytes of
        one frame, not which version this session negotiated).
        """
        event = self._next_event(timeout)
        if isinstance(event, CRCError):
            raise ProtocolError(f"CRC error receiving frame: {event}")
        if event.version != PROTOCOL_VERSION:
            raise ProtocolError(
                f"MCU sent VER={event.version}, expected {PROTOCOL_VERSION}"
            )
        return event

    def _decode_error(self, frame: Frame) -> RemoteError:
        return RemoteError(frame.payload.decode("ascii", errors="replace"))

    def _expect(self, frame: Frame, *expected: FrameType) -> Frame:
        if frame.type is FrameType.ERROR:
            raise self._decode_error(frame)
        if frame.type not in expected:
            names = [t.name for t in expected]
            raise ProtocolError(f"expected {names}, got {frame.type.name}")
        return frame

    def _require_ack(self, frame: Frame, nak_message: str) -> None:
        if frame.type is FrameType.ERROR:
            raise self._decode_error(frame)
        if frame.type is FrameType.NAK:
            raise RemoteError(nak_message)
        if frame.type is not FrameType.ACK:
            raise ProtocolError(f"expected ACK, got {frame.type.name}")

    # -- commands --------------------------------------------------------

    def configure(self, rate: int) -> None:
        """Set the sample rate. There is no way to set polarity from here -
        it's a board switch, so this always sends polarity_request=leave-alone.
        """
        with self._lock:
            payload = encode_config_payload(ConfigPayload(rate=rate))
            self._send(FrameType.CONFIG, payload)
            frame = self._next_frame(self._command_timeout)
            self._require_ack(frame, f"MCU rejected rate={rate}")

    def status(self) -> Status:
        with self._lock:
            self._send(FrameType.STATUS)
            frame = self._expect(
                self._next_frame(self._command_timeout), FrameType.STATUS
            )
        if len(frame.payload) != 1:
            raise ProtocolError(f"STATUS reply must be 1 byte, got {len(frame.payload)}")
        return Status(frame.payload[0])

    def abort(self) -> None:
        """No hardware abort exists on the MCU - per the handoff type table
        this always comes back as an ERROR. Provided so that "can I abort a
        capture" has an honest answer (no, and here's why) rather than a
        silently-ignored no-op.
        """
        with self._lock:
            self._send(FrameType.ABORT)
            frame = self._next_frame(self._command_timeout)
            self._require_ack(frame, "MCU rejected ABORT")

    def arm(self, capture_timeout: float = 30.0) -> Capture:
        """Arm, then block until the MCU auto-pushes the completed capture.

        capture_timeout bounds the wait for that push (trigger + FPGA drain
        time), separate from _command_timeout which only bounds the initial
        ACK/NAK.
        """
        with self._lock:
            self._send(FrameType.ARM)
            frame = self._next_frame(self._command_timeout)
            self._require_ack(frame, "MCU rejected ARM")
            return self._receive_capture(capture_timeout)

    def reread(self, capture_timeout: float = 30.0) -> Capture:
        """Re-fetch the last capture without re-arming (e.g. after a DATA
        frame got dropped downstream of this module). NAKs if nothing has
        been captured since the last ARM.
        """
        with self._lock:
            self._send(FrameType.REREAD)
            return self._receive_capture(capture_timeout, allow_nak=True)

    # -- capture reception -------------------------------------------------

    def _receive_capture(self, timeout: float, allow_nak: bool = False) -> Capture:
        """Wait for CAPTURE_INFO + N*DATA and assemble a Capture.

        The handoff note doesn't say whether the push is preceded by a bare
        ACK (distinct from ARM's own command ACK) or starts directly with
        CAPTURE_INFO, so a leading ACK is tolerated either way.
        """
        frame = self._next_frame(timeout)
        if frame.type is FrameType.ERROR:
            raise self._decode_error(frame)
        if allow_nak and frame.type is FrameType.NAK:
            raise RemoteError("nothing captured yet")

        for attempt in range(self._MAX_REREAD_RETRIES + 1):
            if frame.type is FrameType.ACK:
                frame = self._next_frame(timeout)
            info_frame = self._expect(frame, FrameType.CAPTURE_INFO)
            try:
                return self._drain_data_frames(info_frame, timeout)
            except _CaptureDesync as desync:
                if attempt == self._MAX_REREAD_RETRIES:
                    raise ProtocolError(
                        f"capture desynced ({desync}) and REREAD retries exhausted"
                    ) from desync
                self._send(FrameType.REREAD)
                frame = self._next_frame(timeout)
        raise AssertionError("unreachable")  # loop always returns or raises

    def _drain_data_frames(self, info_frame: Frame, timeout: float) -> Capture:
        info: CaptureInfoPayload = parse_capture_info_payload(info_frame.payload)
        total_bytes = (info.sample_count + 7) // 8
        expected_seq = (info_frame.seq + 1) & 0xFFFF
        buf = bytearray()

        while len(buf) < total_bytes:
            event = self._next_event(timeout)
            if isinstance(event, CRCError):
                raise _CaptureDesync(f"CRC error mid-capture: {event}")
            if event.version != PROTOCOL_VERSION:
                raise ProtocolError(
                    f"MCU sent VER={event.version}, expected {PROTOCOL_VERSION}"
                )
            if event.type is FrameType.ERROR:
                raise self._decode_error(event)
            if event.type is not FrameType.DATA:
                raise _CaptureDesync(f"expected DATA, got {event.type.name}")
            if event.seq != expected_seq:
                raise _CaptureDesync(
                    f"SEQ gap: expected {expected_seq}, got {event.seq}"
                )
            buf.extend(event.payload)
            expected_seq = (expected_seq + 1) & 0xFFFF

        return Capture(
            rate=info.rate,
            sample_count=info.sample_count,
            trigger_latency_ns=info.trigger_latency_ns,
            raw=bytes(buf[:total_bytes]),
        )
