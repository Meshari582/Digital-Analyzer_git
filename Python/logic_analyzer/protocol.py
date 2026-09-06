"""Wire-format framing for the logic analyzer link.

Pure bytes in, frames out. No serial or plotting imports here, and no
knowledge of what CONFIG/DATA frames mean as a capture - that assembly lives
in link.py. This module only has to agree with the firmware's
Src/uart_frame.c on: SOF bytes, header layout, CRC, and payload lengths.

Frame layout on the wire (SOF is framing only, not covered by the CRC):

    0x55 0xAA  TYPE  VER  SEQ_LO SEQ_HI  LEN_LO LEN_HI  payload...  CRC_LO CRC_HI
    \\__ SOF __/ \\_____________ CRC'd over this span ______________/
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Sequence, Union

SOF0 = 0x55
SOF1 = 0xAA
_SOF = bytes([SOF0, SOF1])

PROTOCOL_VERSION = 2

# TYPE, VER, SEQ_LO, SEQ_HI, LEN_LO, LEN_HI
HEADER_LEN = 6

# Matches FRAME_MAX_PAYLOAD in Src/uart_frame.c (also used as a sanity bound
# when resyncing: a header claiming a longer payload than the firmware could
# ever send is treated as a coincidental SOF match in noise, not a frame).
MAX_PAYLOAD_LEN = 256

# CONFIG (PC->MCU): [rate:1][polarity_request:1]
CONFIG_PAYLOAD_LEN = 2

# CAPTURE_INFO (MCU->PC): [rate:1][sample_count:4 LE][trigger_latency_ns:4 LE].
# This is what v1 sent as CONFIG (type 0) - v2 split it out under its own type
# because CONFIG is now PC->MCU-only.
CAPTURE_INFO_PAYLOAD_LEN = 9

# CONFIG.polarity_request sentinel meaning "leave the polarity switch alone".
# Any other value is a request to change a board switch, so the MCU ERRORs on it.
POLARITY_LEAVE_ALONE = 0xFF


class FrameType(IntEnum):
    CONFIG = 0
    ARM = 1
    ABORT = 2
    STATUS = 3
    DATA = 4
    ACK = 5
    NAK = 6
    ERROR = 7
    CAPTURE_INFO = 8
    REREAD = 9


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: init 0xFFFF, poly 0x1021, MSB-first, no reflection,
    no final XOR. Line-for-line match of crc16_ccitt() in Src/uart_frame.c -
    keep it that way rather than switching to a table without re-checking
    against the firmware.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True)
class Frame:
    """A structurally complete, CRC-valid frame as received."""

    type: FrameType
    version: int
    seq: int
    payload: bytes
    crc: int


@dataclass(frozen=True)
class CRCError:
    """A structurally complete frame whose CRC didn't match.

    ``type``/``seq`` come from the header and are only as trustworthy as the
    header itself (unverified by any CRC), but the header passed the
    type/length sanity check that gates resync, so they're worth surfacing
    for logging even though the frame is being discarded.
    """

    type: FrameType
    seq: int
    expected_crc: int
    actual_crc: int
    raw: bytes


ParseEvent = Union[Frame, CRCError]


def encode_frame(
    frame_type: FrameType, seq: int, payload: bytes, version: int = PROTOCOL_VERSION
) -> bytes:
    """Build complete wire bytes (SOF through CRC) for one frame."""
    if len(payload) > MAX_PAYLOAD_LEN:
        raise ValueError(
            f"payload of {len(payload)} bytes exceeds MAX_PAYLOAD_LEN={MAX_PAYLOAD_LEN}"
        )
    header = bytes(
        [
            int(frame_type),
            version,
            seq & 0xFF,
            (seq >> 8) & 0xFF,
            len(payload) & 0xFF,
            (len(payload) >> 8) & 0xFF,
        ]
    )
    body = header + payload
    crc = crc16_ccitt_false(body)
    return _SOF + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


_NEED_MORE = object()


class FrameParser:
    """Streaming frame parser: feed it arbitrary byte chunks, get frames back.

    Resync strategy: scan for the next 0x55 0xAA whenever we're not
    mid-frame. A header whose TYPE is out of range or whose LEN exceeds
    MAX_PAYLOAD_LEN can't have come from the firmware, so it's treated as a
    coincidental SOF match (e.g. inside a DATA payload) rather than a real
    frame - drop one byte and keep scanning. A header that looks plausible
    but fails CRC is reported (so callers can count it) but its LEN is not
    trusted for resync; only the two SOF bytes are dropped before rescanning,
    since a corrupted frame's own header may be the corrupted part.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[ParseEvent]:
        self._buf.extend(data)
        events: list[ParseEvent] = []
        while True:
            result = self._try_parse_one()
            if result is _NEED_MORE:
                break
            if result is not None:
                events.append(result)
        return events

    def _try_parse_one(self):
        buf = self._buf

        sof = buf.find(_SOF)
        if sof == -1:
            # Keep a lone trailing 0x55 in case 0xAA arrives in the next chunk.
            if buf and buf[-1] == SOF0:
                del buf[:-1]
            else:
                buf.clear()
            return _NEED_MORE
        if sof > 0:
            del buf[:sof]

        if len(buf) < 2 + HEADER_LEN:
            return _NEED_MORE

        type_byte = buf[2]
        version = buf[3]
        seq = buf[4] | (buf[5] << 8)
        length = buf[6] | (buf[7] << 8)

        if type_byte > 9 or length > MAX_PAYLOAD_LEN:
            del buf[0:1]
            return None

        frame_len = 2 + HEADER_LEN + length + 2
        if len(buf) < frame_len:
            return _NEED_MORE

        body = bytes(buf[2 : 2 + HEADER_LEN + length])
        crc_offset = 2 + HEADER_LEN + length
        recv_crc = buf[crc_offset] | (buf[crc_offset + 1] << 8)
        calc_crc = crc16_ccitt_false(body)

        if calc_crc == recv_crc:
            frame = Frame(
                type=FrameType(type_byte),
                version=version,
                seq=seq,
                payload=bytes(buf[2 + HEADER_LEN : 2 + HEADER_LEN + length]),
                crc=recv_crc,
            )
            del buf[0:frame_len]
            return frame

        error = CRCError(
            type=FrameType(type_byte),
            seq=seq,
            expected_crc=recv_crc,
            actual_crc=calc_crc,
            raw=bytes(buf[0:frame_len]),
        )
        del buf[0:2]
        return error


def parse_all(data: bytes) -> list[ParseEvent]:
    """One-shot parse of a complete buffer. Convenience for tests."""
    return FrameParser().feed(data)


@dataclass(frozen=True)
class ConfigPayload:
    """PC->MCU CONFIG request. polarity_request must be POLARITY_LEAVE_ALONE
    unless the caller actually wants to flip the polarity switch.
    """

    rate: int
    polarity_request: int = POLARITY_LEAVE_ALONE


def parse_config_payload(payload: bytes) -> ConfigPayload:
    if len(payload) != CONFIG_PAYLOAD_LEN:
        raise ValueError(
            f"CONFIG payload must be {CONFIG_PAYLOAD_LEN} bytes, got {len(payload)}"
        )
    return ConfigPayload(rate=payload[0], polarity_request=payload[1])


def encode_config_payload(cfg: ConfigPayload) -> bytes:
    return bytes([cfg.rate, cfg.polarity_request])


@dataclass(frozen=True)
class CaptureInfoPayload:
    rate: int
    sample_count: int
    trigger_latency_ns: int


def parse_capture_info_payload(payload: bytes) -> CaptureInfoPayload:
    if len(payload) != CAPTURE_INFO_PAYLOAD_LEN:
        raise ValueError(
            f"CAPTURE_INFO payload must be {CAPTURE_INFO_PAYLOAD_LEN} bytes, "
            f"got {len(payload)}"
        )
    return CaptureInfoPayload(
        rate=payload[0],
        sample_count=int.from_bytes(payload[1:5], "little"),
        trigger_latency_ns=int.from_bytes(payload[5:9], "little"),
    )


def encode_capture_info_payload(info: CaptureInfoPayload) -> bytes:
    return (
        bytes([info.rate])
        + info.sample_count.to_bytes(4, "little")
        + info.trigger_latency_ns.to_bytes(4, "little")
    )


def unpack_bits_msb_first(data: bytes, count: int) -> list[int]:
    """Earliest sample is bit 7 of byte 0. Matches drain_loop_run()'s
    ``byte = (byte << 1) | data_read()`` packing bit-for-bit.
    """
    if count > len(data) * 8:
        raise ValueError("count exceeds available bits")
    return [(data[i >> 3] >> (7 - (i & 7))) & 1 for i in range(count)]


def pack_bits_msb_first(bits: Sequence[int]) -> bytes:
    """Inverse of unpack_bits_msb_first, for synthesising test/replay captures."""
    out = bytearray((len(bits) + 7) // 8)
    for i, bit in enumerate(bits):
        if bit:
            out[i >> 3] |= 1 << (7 - (i & 7))
    return bytes(out)
