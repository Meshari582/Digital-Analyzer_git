"""CLI entry point: `python -m logic_analyzer <subcommand> ...`

Subcommands:
  capture      arm real hardware over --port, save the resulting Capture
  replay       run a saved raw frame byte stream through Link exactly as a
               live capture would - the offline path that makes bench-free
               testing (and `regression`) possible
  plot         load a saved Capture and view it (plot.py, matplotlib)
  export-vcd   load a saved Capture and write it as a VCD file
  regression   fast offline self-check against the bundled reference
               capture, or an error-rate-over-N-runs mode against real
               hardware (see regression.py)
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path
from typing import Optional, Sequence

from .capture import Capture
from .link import Link, LinkError
from .regression import check_reference_capture, measure_error_rate
from .replay import ReplayTransport
from .vcd import write_vcd


def _save_capture(capture: Capture, path: Path) -> None:
    with open(path, "wb") as f:
        pickle.dump(capture, f)


def _load_capture(path: Path) -> Capture:
    with open(path, "rb") as f:
        obj = pickle.load(f)
    if not isinstance(obj, Capture):
        raise SystemExit(f"{path} does not contain a Capture")
    return obj


def cmd_capture(args: argparse.Namespace) -> int:
    link = Link.open_serial(args.port, args.baud)
    try:
        link.configure(rate=args.rate)
        capture = link.arm(capture_timeout=args.timeout)
    except LinkError as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        return 1
    finally:
        link.close()
    _save_capture(capture, args.out)
    print(f"saved {capture.sample_count} samples to {args.out}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    transport = ReplayTransport.from_file(args.frames)
    link = Link(transport)
    try:
        capture = link.arm(capture_timeout=args.timeout)
    except LinkError as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        return 1
    finally:
        link.close()

    if args.out:
        _save_capture(capture, args.out)
        print(f"saved {capture.sample_count} samples to {args.out}")
    else:
        print(
            f"replayed {capture.sample_count} samples, rate={capture.rate}, "
            f"trigger_latency_ns={capture.trigger_latency_ns}"
        )
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    from .plot import show_capture  # local: keep matplotlib out of every other path

    show_capture(_load_capture(args.file))
    return 0


def cmd_export_vcd(args: argparse.Namespace) -> int:
    write_vcd(_load_capture(args.file), args.out)
    print(f"wrote {args.out}")
    return 0


def cmd_regression(args: argparse.Namespace) -> int:
    if args.error_rate:
        if not args.port:
            print(
                "regression --error-rate requires --port pointing at real "
                "hardware; none is available in this environment",
                file=sys.stderr,
            )
            return 2

        def link_factory() -> Link:
            return Link.open_serial(args.port, args.baud)

        result = measure_error_rate(
            link_factory, runs=args.runs, capture_timeout=args.timeout
        )
        print(
            f"{result.failures}/{result.runs} runs failed "
            f"({result.error_rate:.2%} error rate)"
        )
        for err in result.errors:
            print(f"  {err}")
        return 0 if result.failures == 0 else 1

    result = check_reference_capture()
    if result.passed:
        print("regression: PASS (reference capture matched)")
        return 0
    print("regression: FAIL")
    for mismatch in result.mismatches:
        print(f"  {mismatch}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m logic_analyzer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_capture = sub.add_parser("capture", help="arm real hardware and save the capture")
    p_capture.add_argument("--port", required=True, help="serial port, e.g. COM5 or /dev/ttyACM0")
    p_capture.add_argument("--baud", type=int, default=921600)
    p_capture.add_argument("--rate", type=int, default=1, choices=[0, 1, 2, 3])
    p_capture.add_argument("--timeout", type=float, default=30.0, help="capture wait timeout, seconds")
    p_capture.add_argument("--out", type=Path, required=True)
    p_capture.set_defaults(func=cmd_capture)

    p_replay = sub.add_parser(
        "replay", help="run a saved raw frame stream through Link offline"
    )
    p_replay.add_argument("frames", type=Path, help="raw wire bytes previously recorded from the MCU")
    p_replay.add_argument("--out", type=Path, default=None, help="save the resulting Capture here")
    p_replay.add_argument("--timeout", type=float, default=5.0)
    p_replay.set_defaults(func=cmd_replay)

    p_plot = sub.add_parser("plot", help="load a saved capture and view it")
    p_plot.add_argument("file", type=Path)
    p_plot.set_defaults(func=cmd_plot)

    p_vcd = sub.add_parser("export-vcd", help="load a saved capture and write a VCD file")
    p_vcd.add_argument("file", type=Path)
    p_vcd.add_argument("out", type=Path)
    p_vcd.set_defaults(func=cmd_export_vcd)

    p_regr = sub.add_parser(
        "regression", help="offline self-check against the bundled reference capture"
    )
    p_regr.add_argument(
        "--error-rate",
        action="store_true",
        help="run --runs live captures against --port and report a failure rate",
    )
    p_regr.add_argument("--runs", type=int, default=100)
    p_regr.add_argument("--port", help="required with --error-rate")
    p_regr.add_argument("--baud", type=int, default=921600)
    p_regr.add_argument("--timeout", type=float, default=30.0)
    p_regr.set_defaults(func=cmd_regression)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
