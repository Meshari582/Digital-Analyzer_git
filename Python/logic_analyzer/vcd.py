"""VCD (Value Change Dump) export for a Capture.

Follows the traditional VCD grammar (IEEE 1364-2005 sec. 18.2) that
GTKWave/sigrok/vcdvcd all read: one $timescale, one $scope/$var for the
single-bit probe, $enddefinitions, then $dumpvars for the initial value and
one value-change line per timestamp where the signal actually changes.
Emitting a line for every sample regardless of whether it changed would
still be valid VCD, but defeats the entire point of the format (and would
make a 16384-sample capture needlessly large) - so this only writes
transitions.

Timestamps are Capture.time_of_sample(n) in nanoseconds - see that
docstring for the +/-20ns trigger-latency uncertainty this file format has
no way to represent; the ns values written here are Capture's best
estimate, not an exact measurement.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO, Union

from .capture import Capture

_SIGNAL_ID = "!"  # single VCD identifier char - arbitrary, just has to be unique
_SIGNAL_NAME = "probe"


def write_vcd(capture: Capture, out: Union[str, Path, IO[str]]) -> None:
    """Write `capture` as a VCD file. `out` is a path or an already-open
    text-mode file/stream.
    """
    if isinstance(out, (str, Path)):
        with open(out, "w", newline="\n") as f:
            _write(capture, f)
    else:
        _write(capture, out)


def _write(capture: Capture, f: IO[str]) -> None:
    f.write("$date\n\t(unknown)\n$end\n")
    f.write("$version\n\tlogic_analyzer.vcd\n$end\n")
    f.write("$timescale 1ns $end\n")
    f.write("$scope module logic_analyzer $end\n")
    f.write(f"$var wire 1 {_SIGNAL_ID} {_SIGNAL_NAME} $end\n")
    f.write("$upscope $end\n")
    f.write("$enddefinitions $end\n")

    samples = capture.samples()
    if not samples:
        # Declared but never captured - dump as unknown rather than
        # emitting a file with a $var no $dumpvars ever assigns.
        f.write("#0\n$dumpvars\nx!\n$end\n")
        return

    f.write(f"#{capture.time_of_sample(0)}\n")
    f.write("$dumpvars\n")
    f.write(f"{samples[0]}{_SIGNAL_ID}\n")
    f.write("$end\n")

    last_value = samples[0]
    for n in range(1, len(samples)):
        if samples[n] != last_value:
            f.write(f"#{capture.time_of_sample(n)}\n")
            f.write(f"{samples[n]}{_SIGNAL_ID}\n")
            last_value = samples[n]
