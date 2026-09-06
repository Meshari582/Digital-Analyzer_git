"""One-off generator for the regression fixture in logic_analyzer/testdata/.

Re-run only if the reference capture itself needs to change - the entire
point of a regression fixture is that it stays fixed across runs, so this
is not part of the normal test/build path.

Shapes the fixture exactly like a real capture: 16384 samples split across
8 DATA frames of 256 bytes each (see the DATA row of the v2 frame type
table), rate=1, and trigger_latency_ns computed with the firmware's
(N+2)*20 formula for rate 1's N=50 - only to make the fixture value
realistic; regression.py itself never recomputes this, it only compares
against whatever's stored in the expected JSON.
"""

import hashlib
import json
import random
from pathlib import Path

from logic_analyzer.protocol import (
    CaptureInfoPayload,
    FrameType,
    encode_capture_info_payload,
    encode_frame,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "logic_analyzer" / "testdata"

RATE = 1
SAMPLE_COUNT = 16384
TRIGGER_LATENCY_NS = (50 + 2) * 20
TOTAL_BYTES = SAMPLE_COUNT // 8
FRAME_PAYLOAD = 256
NUM_DATA_FRAMES = TOTAL_BYTES // FRAME_PAYLOAD
FIXED_SEED = 20260906  # date this fixture was generated - deterministic, never reroll


def main() -> None:
    assert TOTAL_BYTES % FRAME_PAYLOAD == 0
    rng = random.Random(FIXED_SEED)
    raw = bytes(rng.randrange(256) for _ in range(TOTAL_BYTES))

    seq = 0
    stream = encode_frame(FrameType.ACK, seq, b"")
    seq += 1
    info = CaptureInfoPayload(RATE, SAMPLE_COUNT, TRIGGER_LATENCY_NS)
    stream += encode_frame(FrameType.CAPTURE_INFO, seq, encode_capture_info_payload(info))
    for i in range(NUM_DATA_FRAMES):
        seq += 1
        chunk = raw[i * FRAME_PAYLOAD : (i + 1) * FRAME_PAYLOAD]
        stream += encode_frame(FrameType.DATA, seq, chunk)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "reference_capture.frames").write_bytes(stream)

    expected = {
        "rate": RATE,
        "sample_count": SAMPLE_COUNT,
        "trigger_latency_ns": TRIGGER_LATENCY_NS,
        "raw_hex": raw.hex(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
    }
    (OUT_DIR / "reference_capture.expected.json").write_text(
        json.dumps(expected, indent=2) + "\n"
    )
    print(f"wrote {OUT_DIR / 'reference_capture.frames'} ({len(stream)} bytes)")
    print(f"wrote {OUT_DIR / 'reference_capture.expected.json'}")


if __name__ == "__main__":
    main()
