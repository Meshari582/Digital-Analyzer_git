"""Waveform viewer for a Capture.

The only module in this package that imports matplotlib - everything else
(protocol, link, capture, vcd, replay, the regression/replay CLI paths)
stays usable in a headless environment (CI, a bench script with no
display) precisely because it never has to import this one.
"""

from __future__ import annotations

import bisect

from .capture import Capture

_CURSOR_COLORS = ("tab:red", "tab:orange")


def show_capture(capture: Capture, block: bool = True) -> "CaptureViewer":
    """Build and show a CaptureViewer in one call."""
    viewer = CaptureViewer(capture)
    viewer.show(block=block)
    return viewer


class CaptureViewer:
    """Step-plot of one Capture, with two cursors for measuring delta-t.

    Cursors are placed by clicking (moves whichever cursor is "active") and
    adjusted with the keyboard: Tab switches the active cursor, Left/Right
    nudge it by one sample. Both always snap to an actual sample time
    rather than an arbitrary pixel position, since "the time of the click"
    isn't a meaningful value here - only sample times are.
    """

    def __init__(self, capture: Capture):
        import matplotlib.pyplot as plt  # local: see module docstring

        self.capture = capture
        self._samples = capture.samples()
        self._times = [capture.time_of_sample(n) for n in range(len(self._samples))]

        self._active = 0
        self._cursor_idx: list[int | None] = [None, None]
        self._cursor_lines = [None, None]

        self.fig, self.ax = plt.subplots()
        if self._samples:
            self.ax.step(self._times, self._samples, where="post")
        self.ax.set_xlabel(
            "time since trigger (ns) - trigger alignment itself is only "
            "known to +/-20ns; see Capture.time_of_sample()"
        )
        self.ax.set_ylabel("probe")
        self.ax.set_yticks([0, 1])
        self.ax.set_ylim(-0.2, 1.2)
        self._title = self.ax.set_title(self._readout_text())

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

    # -- cursor placement --------------------------------------------------

    def _nearest_sample_index(self, x: float) -> int:
        idx = bisect.bisect_left(self._times, x)
        if idx <= 0:
            return 0
        if idx >= len(self._times):
            return len(self._times) - 1
        before, after = self._times[idx - 1], self._times[idx]
        return idx - 1 if (x - before) <= (after - x) else idx

    def _set_cursor(self, which: int, sample_idx: int) -> None:
        sample_idx = max(0, min(sample_idx, len(self._times) - 1))
        if self._cursor_lines[which] is not None:
            self._cursor_lines[which].remove()
        self._cursor_lines[which] = self.ax.axvline(
            self._times[sample_idx], color=_CURSOR_COLORS[which], linestyle="--"
        )
        self._cursor_idx[which] = sample_idx
        self._title.set_text(self._readout_text())
        self.fig.canvas.draw_idle()

    def _on_click(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None or not self._times:
            return
        self._set_cursor(self._active, self._nearest_sample_index(event.xdata))

    def _on_key(self, event) -> None:
        if not self._times:
            return
        if event.key == "tab":
            self._active = 1 - self._active
            return
        if event.key not in ("left", "right"):
            return
        current = self._cursor_idx[self._active]
        if current is None:
            current = 0
        step = -1 if event.key == "left" else 1
        self._set_cursor(self._active, current + step)

    def _readout_text(self) -> str:
        a, b = self._cursor_idx
        if a is None or b is None:
            return "click (or Tab + arrow keys) to place two cursors"
        # trigger_latency_ns cancels exactly in this subtraction - both
        # cursor times share the same additive constant - so unlike an
        # absolute time_of_sample() value, this delta carries none of the
        # +/-20ns trigger-alignment uncertainty.
        dt = abs(self._times[b] - self._times[a])
        return f"delta-t = {dt} ns"

    def show(self, block: bool = True) -> None:
        import matplotlib.pyplot as plt

        plt.show(block=block)
