"""Regression / self-check support.

check_reference_capture() replays a known-good, bundled byte stream through
a real Link and diffs the resulting Capture against a stored expected
result - the "one command that runs a known capture and compares it
against a stored reference" self-check, fast enough to run after every
change since it never touches a serial port.

measure_error_rate() is the repeated-live-capture error-rate mode: the
counting logic is real and exercised in tests via ReplayTransport, but an
actual error rate can only be produced by pointing it at a real port at the
bench - this environment has none, so this module cannot report one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .link import Link, LinkError
from .replay import ReplayTransport

DATA_DIR = Path(__file__).parent / "testdata"
REFERENCE_FRAMES = DATA_DIR / "reference_capture.frames"
REFERENCE_EXPECTED = DATA_DIR / "reference_capture.expected.json"


@dataclass(frozen=True)
class RegressionResult:
    passed: bool
    mismatches: list[str] = field(default_factory=list)


def check_reference_capture(
    frames_path: Path = REFERENCE_FRAMES,
    expected_path: Path = REFERENCE_EXPECTED,
) -> RegressionResult:
    transport = ReplayTransport.from_file(frames_path)
    link = Link(transport)
    try:
        capture = link.arm(capture_timeout=5.0)
    finally:
        link.close()

    expected = json.loads(Path(expected_path).read_text())
    mismatches = []

    if capture.rate != expected["rate"]:
        mismatches.append(f"rate: got {capture.rate}, expected {expected['rate']}")
    if capture.sample_count != expected["sample_count"]:
        mismatches.append(
            f"sample_count: got {capture.sample_count}, "
            f"expected {expected['sample_count']}"
        )
    if capture.trigger_latency_ns != expected["trigger_latency_ns"]:
        mismatches.append(
            f"trigger_latency_ns: got {capture.trigger_latency_ns}, "
            f"expected {expected['trigger_latency_ns']}"
        )
    if capture.raw.hex() != expected["raw_hex"]:
        mismatches.append("raw sample bits do not match the stored reference")

    return RegressionResult(passed=not mismatches, mismatches=mismatches)


@dataclass(frozen=True)
class ErrorRateResult:
    runs: int
    failures: int
    errors: list[str] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        return self.failures / self.runs if self.runs else 0.0


def measure_error_rate(
    link_factory: Callable[[], Link], runs: int = 100, capture_timeout: float = 5.0
) -> ErrorRateResult:
    """Call link_factory() and arm() it `runs` times, counting failures.

    link_factory takes no arguments and returns a fresh, already-connected
    Link - e.g. `lambda: Link.open_serial(port, baudrate)` at the bench, or
    a ReplayTransport-backed Link in tests. Each run gets its own Link so
    one bad exchange can't wedge every subsequent run.
    """
    failures = 0
    errors: list[str] = []
    for i in range(runs):
        link = link_factory()
        try:
            link.arm(capture_timeout=capture_timeout)
        except LinkError as exc:
            failures += 1
            errors.append(f"run {i}: {exc}")
        finally:
            link.close()
    return ErrorRateResult(runs=runs, failures=failures, errors=errors)
