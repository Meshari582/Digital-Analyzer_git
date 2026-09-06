"""Tests for link.py against ReplayTransport - no real serial port or
hardware involved. Each test pre-loads the exact bytes a real MCU would
have sent for a given scenario (including corrupted or version-mismatched
frames), then asserts on what Link does with them and what it wrote back.

ReplayTransport is the same transport the CLI's `replay`/`regression`
commands use against a recorded capture file - using it here too means
these tests exercise the real offline path, not a test-only stand-in.
"""

import time

import pytest

from logic_analyzer.capture import Capture
from logic_analyzer.link import (
    Link,
    LinkTimeoutError,
    ProtocolError,
    RemoteError,
    Status,
)
from logic_analyzer.protocol import (
    CaptureInfoPayload,
    ConfigPayload,
    FrameType,
    POLARITY_LEAVE_ALONE,
    encode_capture_info_payload,
    encode_config_payload,
    encode_frame,
    parse_all,
    parse_config_payload,
)
from logic_analyzer.replay import ReplayTransport


def make_link(incoming: bytes = b"", command_timeout: float = 1.0):
    transport = ReplayTransport(incoming)
    link = Link(transport, command_timeout=command_timeout)
    return link, transport


def sent_frames(transport: ReplayTransport):
    return [f for f in parse_all(bytes(transport.sent)) if hasattr(f, "type")]


# -- CONFIG ---------------------------------------------------------------


def test_configure_always_sends_polarity_leave_alone():
    link, transport = make_link(encode_frame(FrameType.ACK, seq=0, payload=b""))
    try:
        link.configure(rate=2)
    finally:
        link.close()

    (frame,) = sent_frames(transport)
    assert frame.type is FrameType.CONFIG
    cfg = parse_config_payload(frame.payload)
    assert cfg == ConfigPayload(rate=2, polarity_request=POLARITY_LEAVE_ALONE)


def test_configure_bad_rate_raises_remote_error_on_nak():
    link, _ = make_link(encode_frame(FrameType.NAK, seq=0, payload=b""))
    try:
        with pytest.raises(RemoteError):
            link.configure(rate=99)
    finally:
        link.close()


# -- STATUS -----------------------------------------------------------------


def test_status_decodes_payload():
    link, _ = make_link(
        encode_frame(FrameType.STATUS, seq=0, payload=bytes([Status.CAPTURED]))
    )
    try:
        assert link.status() is Status.CAPTURED
    finally:
        link.close()


def test_status_rejects_version_mismatch():
    link, _ = make_link(
        encode_frame(FrameType.STATUS, seq=0, payload=bytes([0]), version=99)
    )
    try:
        with pytest.raises(ProtocolError):
            link.status()
    finally:
        link.close()


def test_no_reply_times_out():
    link, _ = make_link(b"", command_timeout=0.2)
    try:
        with pytest.raises(LinkTimeoutError):
            link.status()
    finally:
        link.close()


# -- ABORT --------------------------------------------------------------------


def test_abort_always_raises_remote_error_with_mcu_reason():
    link, _ = make_link(
        encode_frame(FrameType.ERROR, seq=0, payload=b"no hardware abort")
    )
    try:
        with pytest.raises(RemoteError) as exc_info:
            link.abort()
        assert exc_info.value.reason == "no hardware abort"
    finally:
        link.close()


# -- ARM / capture reception --------------------------------------------------


def _capture_info(seq: int, rate=2, sample_count=16, trigger_latency_ns=1000) -> bytes:
    info = CaptureInfoPayload(rate, sample_count, trigger_latency_ns)
    return encode_frame(FrameType.CAPTURE_INFO, seq, encode_capture_info_payload(info))


def test_arm_receives_full_capture():
    raw = bytes([0b10110010, 0b01001101])  # 16 bits
    stream = (
        encode_frame(FrameType.ACK, seq=0, payload=b"")
        + _capture_info(seq=1, sample_count=16)
        + encode_frame(FrameType.DATA, seq=2, payload=raw)
    )
    link, _ = make_link(stream)
    try:
        capture = link.arm(capture_timeout=1.0)
    finally:
        link.close()

    assert capture == Capture(
        rate=2, sample_count=16, trigger_latency_ns=1000, raw=raw
    )
    assert capture.samples()[:8] == [1, 0, 1, 1, 0, 0, 1, 0]


def test_arm_assembles_multiple_data_frames_in_order():
    raw = bytes(range(1, 6))  # 5 bytes -> needs sample_count that rounds to 5 bytes
    stream = (
        encode_frame(FrameType.ACK, seq=0, payload=b"")
        + _capture_info(seq=5, sample_count=40)
        + encode_frame(FrameType.DATA, seq=6, payload=raw[:3])
        + encode_frame(FrameType.DATA, seq=7, payload=raw[3:])
    )
    link, _ = make_link(stream)
    try:
        capture = link.arm(capture_timeout=1.0)
    finally:
        link.close()

    assert capture.raw == raw
    assert capture.sample_count == 40


def test_arm_recovers_via_reread_after_crc_corruption():
    good_raw = bytes([0xAB])
    corrupt_data = bytearray(encode_frame(FrameType.DATA, seq=2, payload=b"\x00"))
    corrupt_data[-1] ^= 0xFF  # flip a CRC byte so it fails verification

    stream = (
        encode_frame(FrameType.ACK, seq=0, payload=b"")
        + _capture_info(seq=1, sample_count=8)
        + bytes(corrupt_data)
        + _capture_info(seq=10, sample_count=8)
        + encode_frame(FrameType.DATA, seq=11, payload=good_raw)
    )
    link, transport = make_link(stream, command_timeout=1.0)
    try:
        capture = link.arm(capture_timeout=1.0)
    finally:
        link.close()

    assert capture.raw == good_raw
    reread_sent = [f for f in sent_frames(transport) if f.type is FrameType.REREAD]
    assert len(reread_sent) == 1


def test_arm_gives_up_after_exhausting_reread_retries():
    def corrupted_data_frame(seq: int) -> bytes:
        bad = bytearray(encode_frame(FrameType.DATA, seq=seq, payload=b"\x00"))
        bad[-1] ^= 0xFF
        return bytes(bad)

    stream = encode_frame(FrameType.ACK, seq=0, payload=b"")
    seq = 1
    for _ in range(Link._MAX_REREAD_RETRIES + 1):
        stream += _capture_info(seq=seq, sample_count=8)
        stream += corrupted_data_frame(seq + 1)
        seq += 2

    link, _ = make_link(stream, command_timeout=1.0)
    try:
        with pytest.raises(ProtocolError):
            link.arm(capture_timeout=1.0)
    finally:
        link.close()


def test_arm_detects_seq_gap_and_rereads():
    good_raw = bytes([0x5A])
    stream = (
        encode_frame(FrameType.ACK, seq=0, payload=b"")
        + _capture_info(seq=1, sample_count=8)
        + encode_frame(FrameType.DATA, seq=99, payload=b"\x00")  # seq gap, valid CRC
        + _capture_info(seq=20, sample_count=8)
        + encode_frame(FrameType.DATA, seq=21, payload=good_raw)
    )
    link, transport = make_link(stream, command_timeout=1.0)
    try:
        capture = link.arm(capture_timeout=1.0)
    finally:
        link.close()

    assert capture.raw == good_raw
    reread_sent = [f for f in sent_frames(transport) if f.type is FrameType.REREAD]
    assert len(reread_sent) == 1


# -- REREAD -------------------------------------------------------------------


def test_reread_raises_remote_error_when_nothing_captured():
    link, _ = make_link(encode_frame(FrameType.NAK, seq=0, payload=b""))
    try:
        with pytest.raises(RemoteError):
            link.reread(capture_timeout=1.0)
    finally:
        link.close()


def test_reread_replays_last_capture():
    raw = bytes([0x42])
    stream = _capture_info(seq=0, sample_count=8) + encode_frame(
        FrameType.DATA, seq=1, payload=raw
    )
    link, _ = make_link(stream)
    try:
        capture = link.reread(capture_timeout=1.0)
    finally:
        link.close()

    assert capture.raw == raw


# -- SEQ anchoring --------------------------------------------------------


def test_arm_seq_continuity_anchors_on_capture_info_not_absolute_zero():
    """The MCU's frame_seq is one global counter shared by every outbound
    frame type - ACKs, STATUS replies, CAPTURE_INFO, DATA. By the time the
    first real capture happens, prior STATUS/CONFIG round-trips have already
    pushed it well past 0. If _drain_data_frames anchored SEQ continuity on
    anything but "CAPTURE_INFO's own SEQ, then +1 per DATA frame", this
    would falsely detect a gap and trigger a spurious REREAD.
    """
    raw = bytes([0x77])
    stream = (
        encode_frame(FrameType.STATUS, seq=5, payload=bytes([Status.IDLE]))
        + encode_frame(FrameType.ACK, seq=6, payload=b"")  # CONFIG ack
        + encode_frame(FrameType.ACK, seq=7, payload=b"")  # ARM ack
        + _capture_info(seq=8, sample_count=8)
        + encode_frame(FrameType.DATA, seq=9, payload=raw)
    )
    link, transport = make_link(stream, command_timeout=1.0)
    try:
        assert link.status() is Status.IDLE
        link.configure(rate=1)
        capture = link.arm(capture_timeout=1.0)
    finally:
        link.close()

    assert capture.raw == raw
    assert not [f for f in sent_frames(transport) if f.type is FrameType.REREAD]


# -- thread lifecycle -------------------------------------------------------


def test_close_stops_reader_thread_and_closes_transport():
    link, transport = make_link(b"")
    assert link._reader.is_alive()

    link.close()

    assert not link._reader.is_alive()
    assert transport.closed


def test_close_does_not_hang():
    link, _ = make_link(b"")
    started = time.monotonic()
    link.close()
    elapsed = time.monotonic() - started
    assert elapsed < 0.5


def test_context_manager_stops_reader_thread_on_exit():
    transport = ReplayTransport(b"")
    with Link(transport) as link:
        assert link._reader.is_alive()
    assert not link._reader.is_alive()
    assert transport.closed
