"""CLI tests exercised entirely offline via replay/export-vcd/regression -
`capture` needs a real serial port and isn't invoked here (Link itself is
already covered by tests/test_link.py); `plot` is smoke-tested under the
headless Agg backend since it never blocks there.
"""

import pickle
import warnings

import pytest

from logic_analyzer.__main__ import main
from logic_analyzer.capture import Capture
from logic_analyzer.protocol import FrameType, encode_frame


def _write_frames(path, sample_bytes=b"\xa5"):
    sample_count = len(sample_bytes) * 8
    stream = (
        encode_frame(FrameType.ACK, 0, b"")
        + encode_frame(
            FrameType.CAPTURE_INFO,
            1,
            bytes([1]) + sample_count.to_bytes(4, "little") + (1040).to_bytes(4, "little"),
        )
        + encode_frame(FrameType.DATA, 2, sample_bytes)
    )
    path.write_bytes(stream)


def test_replay_prints_summary_without_out(tmp_path, capsys):
    frames = tmp_path / "capture.frames"
    _write_frames(frames)

    rc = main(["replay", str(frames)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "8 samples" in out
    assert "rate=1" in out


def test_replay_saves_capture_to_out(tmp_path):
    frames = tmp_path / "capture.frames"
    out = tmp_path / "capture.pkl"
    _write_frames(frames)

    rc = main(["replay", str(frames), "--out", str(out)])

    assert rc == 0
    with open(out, "rb") as f:
        capture = pickle.load(f)
    assert isinstance(capture, Capture)
    assert capture.sample_count == 8
    assert capture.trigger_latency_ns == 1040


def test_replay_reports_failure_on_bad_stream(tmp_path, capsys):
    frames = tmp_path / "bad.frames"
    frames.write_bytes(encode_frame(FrameType.NAK, 0, b""))

    rc = main(["replay", str(frames)])

    assert rc == 1
    assert "replay failed" in capsys.readouterr().err


def test_export_vcd_round_trips_a_saved_capture(tmp_path):
    capture = Capture(rate=1, sample_count=16, trigger_latency_ns=1040, raw=bytes([0b10110010, 0b01001101]))
    capture_file = tmp_path / "capture.pkl"
    with open(capture_file, "wb") as f:
        pickle.dump(capture, f)
    vcd_out = tmp_path / "out.vcd"

    rc = main(["export-vcd", str(capture_file), str(vcd_out)])

    assert rc == 0
    text = vcd_out.read_text()
    assert "$enddefinitions $end" in text
    assert "#1040" in text  # capture.time_of_sample(0)


def test_regression_passes_against_bundled_reference(capsys):
    rc = main(["regression"])

    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_regression_error_rate_requires_port(capsys):
    rc = main(["regression", "--error-rate"])

    assert rc == 2
    assert "requires --port" in capsys.readouterr().err


def test_plot_command_does_not_crash_headless(tmp_path):
    import matplotlib

    matplotlib.use("Agg")

    capture = Capture(rate=1, sample_count=16, trigger_latency_ns=1040, raw=bytes([0b10110010, 0b01001101]))
    capture_file = tmp_path / "capture.pkl"
    with open(capture_file, "wb") as f:
        pickle.dump(capture, f)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        rc = main(["plot", str(capture_file)])

    assert rc == 0


def test_no_subcommand_exits_nonzero():
    with pytest.raises(SystemExit):
        main([])
