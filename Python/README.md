# logic-analyzer

PC-side tool for the FPGA/MCU logic analyzer: frame protocol, serial link,
capture, VCD export, and plotting.

## Install

```
pip install -e ".[dev]"
```

This installs `pyserial` and `matplotlib` (runtime), plus `pytest` and
`vcdvcd` (dev/test only - `vcdvcd` is used by the test suite to
independently parse exported VCD files, not by the tool itself).

## Layout

- `protocol.py` - wire framing: SOF/CRC/header, frame types, payload codecs.
- `link.py` - serial transport, CONFIG/ARM/STATUS/REREAD exchanges, CRC/SEQ
  recovery.
- `capture.py` - the `Capture` value object (samples, timing) that
  everything downstream is built on.
- `replay.py` - a `Transport` that replays a recorded byte stream instead
  of a real port. This is what lets every command below run with no
  hardware attached.
- `vcd.py`, `plot.py` - export and viewing, built only on `Capture`.
- `regression.py` - the offline self-check and error-rate-over-N-runs logic
  behind the `regression` subcommand.

## Running the tests

```
pytest
```

All 68 tests run offline - no serial port or display required. `plot.py`
is exercised under matplotlib's headless `Agg` backend.

## CLI: `python -m logic_analyzer`

### Against real hardware

```
python -m logic_analyzer capture --port COM5 --baud 921600 --rate 1 --out run1.pkl
```

`--rate` is 0-3 (10 MS/s .. 10 kS/s - see `capture.py`'s docstring for the
table). This connects, sends CONFIG, ARMs, waits for the pushed capture,
and pickles the resulting `Capture` to `run1.pkl`. There is no way to set
polarity from here - it's a physical switch on the board.

### Fully offline (no port, no hardware)

Every command past `link.py` can run against a **recorded raw byte
stream** instead of a live port - this is how the test suite and the
`regression` command work with nothing attached.

```
python -m logic_analyzer replay logic_analyzer/testdata/reference_capture.frames --out run1.pkl
```

`replay` builds a `Link` on a `ReplayTransport` loaded from the given file
and runs the real `arm()` exchange against it, exactly as if a live MCU had
sent those bytes. Omit `--out` to just print a summary instead of saving.

To make your own replay fixture from a real capture, record the raw bytes
the MCU sends after an `ARM` (ACK + CAPTURE_INFO + the DATA frames) to a
file - that file is a valid input to `replay` (and can double as a new
regression reference; see `scripts/make_reference_capture.py`).

### View a saved capture

```
python -m logic_analyzer plot run1.pkl
```

Opens a waveform window. Zoom/pan use matplotlib's own toolbar. Click to
place a cursor (moves whichever cursor is "active"); Tab switches the
active cursor; Left/Right nudge it by one sample. The title shows the
delta-t between the two cursors once both are placed.

### Export VCD

```
python -m logic_analyzer export-vcd run1.pkl run1.vcd
```

Open `run1.vcd` in GTKWave or any VCD viewer.

### Regression / self-check

```
python -m logic_analyzer regression
```

Fast, offline: replays the bundled reference capture
(`logic_analyzer/testdata/reference_capture.frames`) and diffs the result
against the stored expected values
(`logic_analyzer/testdata/reference_capture.expected.json`). Run this after
any change to `protocol.py`/`link.py`/`capture.py`.

```
python -m logic_analyzer regression --error-rate --runs 100 --port COM5
```

Arms real hardware 100 times and reports how many runs failed. Requires
`--port` - there is no synthetic fallback for this mode, since a
meaningful error rate is a hardware property; without `--port` the command
exits `2` and says so rather than fabricating a number.

## Known limitations of this pass

- No real VCD viewer (GTKWave, sigrok-cli) or serial port was available in
  the environment this was built in. VCD output was cross-checked against
  `vcdvcd` (an independent PyPI VCD parser, plus its bundled `vcdcat` CLI)
  rather than a graphical viewer - see `tests/test_vcd.py`.
- `regression --error-rate` is implemented and unit-tested against
  `ReplayTransport`-backed failures, but has never produced a real number
  against hardware - do that once a board is on the bench.
