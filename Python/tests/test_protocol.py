import pytest

from logic_analyzer.protocol import (
    CAPTURE_INFO_PAYLOAD_LEN,
    CONFIG_PAYLOAD_LEN,
    POLARITY_LEAVE_ALONE,
    CaptureInfoPayload,
    ConfigPayload,
    FrameType,
    encode_capture_info_payload,
    encode_config_payload,
    encode_frame,
    parse_all,
    parse_capture_info_payload,
    parse_config_payload,
)


def test_payload_length_constants_are_distinct():
    assert CONFIG_PAYLOAD_LEN == 2
    assert CAPTURE_INFO_PAYLOAD_LEN == 9
    assert CONFIG_PAYLOAD_LEN != CAPTURE_INFO_PAYLOAD_LEN


def test_config_payload_round_trip():
    cfg = ConfigPayload(rate=2, polarity_request=0x03)
    encoded = encode_config_payload(cfg)
    assert len(encoded) == CONFIG_PAYLOAD_LEN
    assert parse_config_payload(encoded) == cfg


def test_config_payload_polarity_leave_alone_survives_round_trip():
    cfg = ConfigPayload(rate=1, polarity_request=POLARITY_LEAVE_ALONE)
    encoded = encode_config_payload(cfg)
    decoded = parse_config_payload(encoded)
    assert decoded.polarity_request == POLARITY_LEAVE_ALONE
    assert decoded == cfg


def test_config_payload_default_polarity_is_leave_alone():
    assert ConfigPayload(rate=0).polarity_request == POLARITY_LEAVE_ALONE


@pytest.mark.parametrize("bad_payload", [b"", b"\x02", b"\x02\xff\x00"])
def test_parse_config_payload_rejects_wrong_length(bad_payload):
    with pytest.raises(ValueError):
        parse_config_payload(bad_payload)


def test_capture_info_payload_round_trip():
    info = CaptureInfoPayload(rate=3, sample_count=16384, trigger_latency_ns=123456)
    encoded = encode_capture_info_payload(info)
    assert len(encoded) == CAPTURE_INFO_PAYLOAD_LEN
    assert parse_capture_info_payload(encoded) == info


@pytest.mark.parametrize(
    "bad_payload",
    [b"", b"\x03\x00\x40\x00", b"\x03" + b"\x00" * 7, b"\x03" + b"\x00" * 10],
)
def test_parse_capture_info_payload_rejects_wrong_length(bad_payload):
    with pytest.raises(ValueError):
        parse_capture_info_payload(bad_payload)


def test_config_frame_round_trip_through_wire_bytes():
    cfg = ConfigPayload(rate=1, polarity_request=POLARITY_LEAVE_ALONE)
    wire = encode_frame(FrameType.CONFIG, seq=7, payload=encode_config_payload(cfg))
    (frame,) = parse_all(wire)
    assert frame.type is FrameType.CONFIG
    assert parse_config_payload(frame.payload) == cfg


def test_capture_info_frame_round_trip_through_wire_bytes():
    info = CaptureInfoPayload(rate=2, sample_count=16384, trigger_latency_ns=999)
    wire = encode_frame(
        FrameType.CAPTURE_INFO, seq=8, payload=encode_capture_info_payload(info)
    )
    (frame,) = parse_all(wire)
    assert frame.type is FrameType.CAPTURE_INFO
    assert parse_capture_info_payload(frame.payload) == info
