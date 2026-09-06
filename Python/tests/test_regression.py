"""Tests for the offline regression self-check and the error-rate counting
logic. No serial port or hardware involved - measure_error_rate is tested
against ReplayTransport-backed Links, which is the honest limit of what can
be verified without a bench; see regression.py's module docstring.
"""

import json

import pytest

from logic_analyzer.link import Link
from logic_analyzer.protocol import FrameType, encode_frame
from logic_analyzer.regression import (
    REFERENCE_EXPECTED,
    REFERENCE_FRAMES,
    check_reference_capture,
    measure_error_rate,
)
from logic_analyzer.replay import ReplayTransport


def test_reference_fixture_files_exist():
    assert REFERENCE_FRAMES.exists()
    assert REFERENCE_EXPECTED.exists()


def test_check_reference_capture_passes_against_bundled_fixture():
    result = check_reference_capture()
    assert result.passed, result.mismatches
    assert result.mismatches == []


def test_check_reference_capture_detects_sample_mismatch(tmp_path):
    expected = json.loads(REFERENCE_EXPECTED.read_text())
    expected["raw_hex"] = "00" * (len(expected["raw_hex"]) // 2)
    bad_expected = tmp_path / "bad_expected.json"
    bad_expected.write_text(json.dumps(expected))

    result = check_reference_capture(
        frames_path=REFERENCE_FRAMES, expected_path=bad_expected
    )
    assert not result.passed
    assert any("raw sample bits" in m for m in result.mismatches)


def test_check_reference_capture_detects_timing_mismatch(tmp_path):
    expected = json.loads(REFERENCE_EXPECTED.read_text())
    expected["trigger_latency_ns"] += 1
    bad_expected = tmp_path / "bad_expected.json"
    bad_expected.write_text(json.dumps(expected))

    result = check_reference_capture(
        frames_path=REFERENCE_FRAMES, expected_path=bad_expected
    )
    assert not result.passed
    assert any("trigger_latency_ns" in m for m in result.mismatches)


def _successful_stream() -> bytes:
    return encode_frame(FrameType.ACK, 0, b"") + encode_frame(
        FrameType.CAPTURE_INFO, 1, bytes(9)
    ) + encode_frame(FrameType.DATA, 2, b"\x00")


def test_measure_error_rate_all_successful_runs():
    def link_factory():
        return Link(ReplayTransport(_successful_stream()), command_timeout=0.5)

    result = measure_error_rate(link_factory, runs=10, capture_timeout=0.5)
    assert result.runs == 10
    assert result.failures == 0
    assert result.error_rate == 0.0


def test_measure_error_rate_counts_failures_independently_per_run():
    streams = [
        _successful_stream(),
        b"",  # times out -> LinkTimeoutError
        _successful_stream(),
        encode_frame(FrameType.NAK, 0, b""),  # ARM rejected -> RemoteError
    ]
    calls = iter(streams)

    def link_factory():
        return Link(ReplayTransport(next(calls)), command_timeout=0.3)

    result = measure_error_rate(link_factory, runs=4, capture_timeout=0.3)
    assert result.runs == 4
    assert result.failures == 2
    assert result.error_rate == 0.5
    assert len(result.errors) == 2


def test_measure_error_rate_one_bad_run_does_not_wedge_the_next():
    """Each run gets its own Link - a failure shouldn't leave stale queued
    events that corrupt the next run's read.
    """
    streams = [b"", _successful_stream()]
    calls = iter(streams)

    def link_factory():
        return Link(ReplayTransport(next(calls)), command_timeout=0.3)

    result = measure_error_rate(link_factory, runs=2, capture_timeout=0.3)
    assert result.failures == 1
    assert result.runs == 2
