import pytest

from logic_analyzer.capture import Capture, sample_period_ns


@pytest.mark.parametrize(
    "rate, expected_period_ns",
    [(0, 100), (1, 1_000), (2, 10_000), (3, 100_000)],
)
def test_sample_period_ns_matches_firmware_divider_table(rate, expected_period_ns):
    assert sample_period_ns(rate) == expected_period_ns


def test_sample_period_ns_rejects_unknown_rate():
    with pytest.raises(ValueError):
        sample_period_ns(4)


def test_time_of_sample_adds_trigger_latency_and_period():
    capture = Capture(rate=1, sample_count=4, trigger_latency_ns=500, raw=b"\xf0")
    assert capture.time_of_sample(0) == 500
    assert capture.time_of_sample(1) == 500 + 1_000
    assert capture.time_of_sample(3) == 500 + 3 * 1_000


def test_time_of_sample_rejects_out_of_range_index():
    capture = Capture(rate=0, sample_count=8, trigger_latency_ns=0, raw=b"\x00")
    with pytest.raises(IndexError):
        capture.time_of_sample(8)
    with pytest.raises(IndexError):
        capture.time_of_sample(-1)


def test_samples_unpacks_msb_first():
    capture = Capture(rate=0, sample_count=8, trigger_latency_ns=0, raw=bytes([0b10110010]))
    assert capture.samples() == [1, 0, 1, 1, 0, 0, 1, 0]


def test_decode_is_a_no_op_placeholder():
    capture = Capture(rate=0, sample_count=8, trigger_latency_ns=0, raw=b"\x00")
    assert capture.decode() == []
