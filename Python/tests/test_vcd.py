"""VCD writer tests, cross-checked against vcdvcd - a PyPI VCD *parser*,
independent of vcd.py's own encoder, so a bug in the writer's understanding
of the format doesn't get validated by re-reading it with the same broken
assumptions. No real waveform viewer (GTKWave, sigrok-cli) is available in
this environment - see the module docstring note in the PR description.
"""

import itertools

import pytest

vcdvcd = pytest.importorskip("vcdvcd")

from logic_analyzer.capture import Capture
from logic_analyzer.vcd import write_vcd


def _reference_transitions(capture: Capture):
    """Expected (time, value) pairs, computed via the same public Capture
    API the writer uses but not by re-running its transition-detection
    loop - used as the ground truth the independently-parsed file is
    checked against.
    """
    samples = capture.samples()
    transitions = [(capture.time_of_sample(0), str(samples[0]))]
    for n in range(1, len(samples)):
        if samples[n] != samples[n - 1]:
            transitions.append((capture.time_of_sample(n), str(samples[n])))
    return transitions


def test_vcd_parses_and_matches_expected_transitions(tmp_path):
    raw = bytes([0b10110010, 0b01001101])  # 16 samples, several transitions
    capture = Capture(rate=1, sample_count=16, trigger_latency_ns=1040, raw=raw)
    out = tmp_path / "capture.vcd"
    write_vcd(capture, out)

    parsed = vcdvcd.VCDVCD(str(out))
    (signal_name,) = parsed.signals
    assert signal_name.endswith("probe")
    tv = parsed[signal_name].tv

    assert tv == _reference_transitions(capture)

    # Independent count of value-runs (groupby doesn't share any code with
    # vcd.py's change-detection loop) - confirms we didn't emit a line per
    # sample, which is the entire point of the format.
    samples = capture.samples()
    expected_run_count = sum(1 for _ in itertools.groupby(samples))
    assert len(tv) == expected_run_count


def test_vcd_constant_signal_has_only_initial_value(tmp_path):
    capture = Capture(rate=0, sample_count=32, trigger_latency_ns=140, raw=b"\x00\x00\x00\x00")
    out = tmp_path / "constant.vcd"
    write_vcd(capture, out)

    parsed = vcdvcd.VCDVCD(str(out))
    (signal_name,) = parsed.signals
    tv = parsed[signal_name].tv

    assert tv == [(capture.time_of_sample(0), "0")]


def test_vcd_timestamps_use_time_of_sample_not_raw_index(tmp_path):
    """rate=3 has a 100us period - if the writer used sample index instead
    of time_of_sample() for timestamps, this would be off by ~100000x.
    """
    raw = bytes([0b11000000])  # transitions after sample 0 and sample 1
    capture = Capture(rate=3, sample_count=8, trigger_latency_ns=5140, raw=raw)
    out = tmp_path / "slow.vcd"
    write_vcd(capture, out)

    parsed = vcdvcd.VCDVCD(str(out))
    (signal_name,) = parsed.signals
    tv = parsed[signal_name].tv

    assert tv == [
        (capture.time_of_sample(0), "1"),
        (capture.time_of_sample(2), "0"),
    ]
    assert tv[0][0] == 5140
    assert tv[1][0] == 5140 + 2 * 100_000


def test_vcd_empty_capture_is_still_valid_vcd(tmp_path):
    capture = Capture(rate=0, sample_count=0, trigger_latency_ns=0, raw=b"")
    out = tmp_path / "empty.vcd"
    write_vcd(capture, out)

    parsed = vcdvcd.VCDVCD(str(out))
    (signal_name,) = parsed.signals
    assert parsed[signal_name].tv == [(0, "x")]
