"""Tests for plot.py against the headless Agg backend - no display needed.
Click/key handlers are exercised directly with small stand-in event objects
rather than a real GUI event loop, since that's what's actually reachable
without a display in this environment.
"""

from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")

import pytest

from logic_analyzer.capture import Capture
from logic_analyzer.plot import CaptureViewer


def _click(viewer: CaptureViewer, xdata: float) -> None:
    viewer._on_click(SimpleNamespace(inaxes=viewer.ax, xdata=xdata))


def _key(viewer: CaptureViewer, key: str) -> None:
    viewer._on_key(SimpleNamespace(key=key))


def make_capture() -> Capture:
    raw = bytes([0b10110010, 0b01001101])  # 16 samples, rate=1 -> 1000ns period
    return Capture(rate=1, sample_count=16, trigger_latency_ns=1040, raw=raw)


def test_viewer_builds_headless_without_a_display():
    viewer = CaptureViewer(make_capture())
    assert viewer.ax.lines  # the step plot itself drew something


def test_click_snaps_to_nearest_sample_and_sets_active_cursor():
    viewer = CaptureViewer(make_capture())
    _click(viewer, 2100)  # nearest to time_of_sample(1)=2040
    assert viewer._cursor_idx[0] == 1
    assert viewer._cursor_idx[1] is None


def test_second_click_sets_the_other_cursor_and_reports_delta_t():
    viewer = CaptureViewer(make_capture())
    _click(viewer, 1040)  # sample 0
    _key(viewer, "tab")
    _click(viewer, 10040)  # sample 9
    assert viewer._cursor_idx == [0, 9]
    assert viewer._readout_text() == "delta-t = 9000 ns"


def test_delta_t_is_exact_regardless_of_trigger_latency_value():
    """trigger_latency_ns should cancel out of the cursor delta entirely -
    two captures differing only in that field must report the same delta-t
    for the same pair of sample indices.
    """
    raw = bytes([0b10110010, 0b01001101])
    low_latency = Capture(rate=1, sample_count=16, trigger_latency_ns=20, raw=raw)
    high_latency = Capture(rate=1, sample_count=16, trigger_latency_ns=99_999, raw=raw)

    v1, v2 = CaptureViewer(low_latency), CaptureViewer(high_latency)
    for v in (v1, v2):
        _click(v, v._times[2])
        _key(v, "tab")
        _click(v, v._times[9])

    assert v1._readout_text() == v2._readout_text() == "delta-t = 7000 ns"


def test_tab_switches_active_cursor_without_moving_existing_one():
    viewer = CaptureViewer(make_capture())
    _click(viewer, viewer._times[3])
    _key(viewer, "tab")
    assert viewer._active == 1
    assert viewer._cursor_idx == [3, None]


def test_arrow_keys_nudge_active_cursor_by_one_sample():
    viewer = CaptureViewer(make_capture())
    _click(viewer, viewer._times[5])
    _key(viewer, "right")
    assert viewer._cursor_idx[0] == 6
    _key(viewer, "left")
    _key(viewer, "left")
    assert viewer._cursor_idx[0] == 4


def test_cursor_index_is_clamped_to_valid_range():
    viewer = CaptureViewer(make_capture())
    _click(viewer, viewer._times[0])
    _key(viewer, "left")  # would go to -1
    assert viewer._cursor_idx[0] == 0

    _click(viewer, viewer._times[-1])
    _key(viewer, "right")  # would go past the last sample
    assert viewer._cursor_idx[0] == len(viewer._times) - 1


def test_empty_capture_does_not_crash_on_click_or_key():
    empty = Capture(rate=0, sample_count=0, trigger_latency_ns=0, raw=b"")
    viewer = CaptureViewer(empty)
    _click(viewer, 0)
    _key(viewer, "tab")
    _key(viewer, "right")
    assert viewer._cursor_idx == [None, None]


def test_readout_prompts_until_both_cursors_are_placed():
    viewer = CaptureViewer(make_capture())
    assert "click" in viewer._readout_text().lower()
    _click(viewer, viewer._times[0])
    assert "click" in viewer._readout_text().lower()
