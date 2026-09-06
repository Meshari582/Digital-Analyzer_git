"""Capture value object: the fully-received result of one ARM/REREAD
exchange. Plotting and VCD export are meant to sit on top of this, not on
raw frame payloads pulled out of link.py directly.

Sample-rate table: CONFIG/CAPTURE_INFO frames only ever carry the rate
*index* (0-3), never the actual clock divider or period - the PC has no way
to derive one from the other over the wire, so this table has to be kept in
sync with the firmware by hand. It will silently drift if the FPGA side
ever changes its dividers without a matching update here.

Sourced from cmd_rate()'s usage string in Src/cli.c and confirmed against
the rate_div instantiations in logic_analyzer_top.v (FPGA clock is 50 MHz,
so sample period = N * 20 ns):

    rate  N     period      sample rate
    0     5     100 ns      10 MS/s
    1     50    1 us        1 MS/s
    2     500   10 us       100 kS/s
    3     5000  100 us      10 kS/s
"""

from __future__ import annotations

from dataclasses import dataclass

from .protocol import unpack_bits_msb_first

FPGA_CLOCK_HZ = 50_000_000

# Keyed by the CONFIG/CAPTURE_INFO rate byte. Matches TRIGGER_DIVIDER_N[] in
# the firmware - derive periods from N rather than hard-coding all four
# periods redundantly, so there's exactly one place this can go wrong.
TRIGGER_DIVIDER_N = {0: 5, 1: 50, 2: 500, 3: 5000}

# The probe edge that starts a capture is asynchronous to the FPGA's 50 MHz
# sample clock, so trigger_latency_ns (see below) carries this much
# quantization uncertainty in both directions. Per the firmware handoff:
# don't present time_of_sample()'s return value as exact.
TRIGGER_LATENCY_UNCERTAINTY_NS = 20


def sample_period_ns(rate: int) -> int:
    try:
        n = TRIGGER_DIVIDER_N[rate]
    except KeyError:
        raise ValueError(f"unknown rate byte {rate}") from None
    return n * (1_000_000_000 // FPGA_CLOCK_HZ)


@dataclass(frozen=True)
class Capture:
    """One fully-received, SEQ/CRC-verified capture."""

    rate: int
    sample_count: int
    trigger_latency_ns: int
    """Straight from CAPTURE_INFO's own wire field - the firmware computes
    this (currently (N+2)*20 ns, after several correction rounds on that
    side), so the PC deliberately never recomputes it locally. Only
    period_ns is derived from TRIGGER_DIVIDER_N; latency always comes from
    the wire.
    """
    raw: bytes
    """Packed sample bits, MSB-first - see protocol.unpack_bits_msb_first."""

    def samples(self) -> list[int]:
        return unpack_bits_msb_first(self.raw, self.sample_count)

    def time_of_sample(self, n: int) -> int:
        """Nanoseconds from trigger to sample n (0-indexed).

        Accurate to +/-TRIGGER_LATENCY_UNCERTAINTY_NS: the trigger edge is
        asynchronous to the sample clock, so treat this as "about this many
        ns", not an exact value, anywhere it's displayed.
        """
        if not 0 <= n < self.sample_count:
            raise IndexError(
                f"sample {n} out of range for {self.sample_count} samples"
            )
        return self.trigger_latency_ns + n * sample_period_ns(self.rate)

    def decode(self) -> list:
        """Placeholder for future protocol decoders (I2C/SPI/UART overlays
        on top of the raw bit trace). No decoders exist yet, so this always
        returns an empty list - callers should treat that as "not decoded",
        not "decoded, nothing found".
        """
        return []
