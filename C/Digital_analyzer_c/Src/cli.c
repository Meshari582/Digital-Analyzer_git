#include <stdint.h>
#include "stm32f7xx_hal.h"
#include "cli.h"
#include "gpio_driver.h"
#include "drain_loop.h"
#include "uart_frame.h"
#include "spi_test.h"

/* Every selftest stage assumes rate 0 (10 MS/s) - see cmd_selftest(). */
#define SELFTEST_SAMPLE_RATE_HZ  10000000U
#define SELFTEST_BIT_RATE_HZ     100000U

#define CLI_LINE_MAX  32U

typedef enum
{
    CAP_IDLE,       /* not armed - no arm_pulse() since the last dump/reset */
    CAP_ARMED,      /* arm_pulse() sent, waiting for drain_loop_ready() */
    CAP_CAPTURED    /* drain_loop_ready() went high; buffer not yet drained */
} capture_state_t;

static capture_state_t cap_state = CAP_IDLE;

/* Which caller is waiting on the current ARMED capture, so completion
 * knows whether to print the human banner or auto-drain-and-push binary
 * frames - see service_capture_completion(). */
typedef enum
{
    CAP_SOURCE_CLI,
    CAP_SOURCE_FRAME
} capture_source_t;

static capture_source_t cap_source = CAP_SOURCE_CLI;

/* True once sample_buffer holds a completed, not-yet-superseded capture -
 * i.e. between a drain and the next arm_pulse(). Gates FRAME_TYPE_REREAD. */
static uint8_t have_captured_buffer;

/* Most recent repeat-cycle timing, for the "timing" command. Updated each
 * time cmd_repeat() completes a full drain+transfer cycle; see cmd_repeat(). */
static uint32_t drain_time_us;
static uint32_t transfer_time_us;
static uint32_t dead_time_us;
static uint8_t  have_timing_data;

/* ---------- tiny text helpers - no printf, keeps this off the hot path
 * and off the flash budget the HAL removal just bought back ---------- */

static void print_str(const char *s)
{
    while (*s)
    {
        uart_putc((uint8_t)*s++);
    }
}

static void print_nibble_hex(uint8_t nibble)
{
    uart_putc(nibble < 10U ? (uint8_t)('0' + nibble) : (uint8_t)('A' + (nibble - 10U)));
}

static void print_hex_byte(uint8_t b)
{
    print_nibble_hex(b >> 4);
    print_nibble_hex(b & 0x0FU);
}

static void print_uint(uint32_t v)
{
    char buf[10];
    int  i = 0;

    if (v == 0U)
    {
        uart_putc('0');
        return;
    }

    while (v > 0U && i < 10)
    {
        buf[i++] = (char)('0' + (v % 10U));
        v /= 10U;
    }

    while (i > 0)
    {
        uart_putc((uint8_t)buf[--i]);
    }
}

static uint8_t digit_count(uint32_t v)
{
    uint8_t n = 1;
    while (v >= 10U)
    {
        v /= 10U;
        n++;
    }
    return n;
}

/* Right-justifies value_us so its last digit lands in column 14 (label
 * inclusive), matching the brief's requested "drain:    1842 us" layout. */
static void print_timing_line(const char *label, uint8_t label_width, uint32_t value_us)
{
    print_str(label);
    int16_t pad = (int16_t)(14 - (int16_t)label_width - (int16_t)digit_count(value_us));
    if (pad < 0)
    {
        pad = 0;
    }
    while (pad-- > 0)
    {
        uart_putc(' ');
    }
    print_uint(value_us);
    print_str(" us\r\n");
}

static uint32_t cycles_to_us(uint32_t cycles)
{
    return cycles / (SystemCoreClock / 1000000U);
}

/* ---------- frame protocol dispatch ----------
 * Reused by read_line() below for every byte uart_frame_rx_feed() reports
 * as a completed frame - see uart_frame.c's file-header comment for the
 * type table and direction rules this implements. */

static void frame_reply_error(const char *reason, uint16_t reason_len)
{
    uart_frame_send_reply(FRAME_TYPE_ERROR, (const uint8_t *)reason, reason_len);
}

static void handle_frame_command(const rx_frame_t *f)
{
    if (f->version != PROTOCOL_VERSION)
    {
        static const char reason[] = "version mismatch";
        frame_reply_error(reason, (uint16_t)(sizeof(reason) - 1U));
        return;
    }

    switch (f->type)
    {
        case FRAME_TYPE_ARM:
            drain_loop_clear_ready();
            arm_pulse();
            cap_state            = CAP_ARMED;
            cap_source           = CAP_SOURCE_FRAME;
            have_captured_buffer = 0;
            uart_frame_send_reply(FRAME_TYPE_ACK, (const uint8_t *)0, 0);
            break;

        case FRAME_TYPE_CONFIG:
            if (f->len < 2U || f->payload[0] > 3U)
            {
                uart_frame_send_reply(FRAME_TYPE_NAK, (const uint8_t *)0, 0);
                break;
            }
            if (f->payload[1] != 0xFFU)
            {
                static const char reason[] = "polarity is a board switch, not settable";
                frame_reply_error(reason, (uint16_t)(sizeof(reason) - 1U));
                break;
            }
            rate_set(f->payload[0]);
            uart_frame_send_reply(FRAME_TYPE_ACK, (const uint8_t *)0, 0);
            break;

        case FRAME_TYPE_STATUS:
        {
            uint8_t state_byte = (uint8_t)cap_state;
            uart_frame_send_reply(FRAME_TYPE_STATUS, &state_byte, 1U);
            break;
        }

        case FRAME_TYPE_ABORT:
        {
            static const char reason[] = "hardware cannot abort an in-flight capture";
            frame_reply_error(reason, (uint16_t)(sizeof(reason) - 1U));
            break;
        }

        case FRAME_TYPE_REREAD:
            if (!have_captured_buffer)
            {
                uart_frame_send_reply(FRAME_TYPE_NAK, (const uint8_t *)0, 0);
                break;
            }
            /* raddr wraps exactly back to 0 after another 16384 strobes
             * (14-bit counter, 16384-deep buffer) - see uart_frame.h's
             * FRAME_TYPE_REREAD comment. No arm_pulse() here: that's what
             * makes this a re-read instead of a new capture. */
            drain_loop_run();
            uart_frame_send_config();
            uart_frame_send();
            break;

        default:
        {
            static const char reason[] = "unsupported frame type";
            frame_reply_error(reason, (uint16_t)(sizeof(reason) - 1U));
            break;
        }
    }
}

/* Shared by the ASCII CLI's "arm"/wait-for-trigger flow and the frame
 * protocol's ARM command - cap_source (set when the arm happened) decides
 * whether completion means "print a banner" (a human is watching a
 * terminal) or "drain and push binary frames" (the PC tool is waiting on
 * them, and was never going to type "dump"). */
static void service_capture_completion(void)
{
    if (cap_state != CAP_ARMED || !drain_loop_ready())
    {
        return;
    }

    cap_state = CAP_CAPTURED;

    if (cap_source == CAP_SOURCE_FRAME)
    {
        drain_loop_run();
        have_captured_buffer = 1;
        cap_state             = CAP_IDLE;
        uart_frame_send_config();
        uart_frame_send();
    }
    else
    {
        print_str("\r\n[capture complete]\r\n");
    }
}

/* ---------- line reader ---------- */

/* Blocks until a full ASCII line (terminated by \r or \n) has arrived.
 * Every byte is first offered to uart_frame_rx_feed(): bytes that are part
 * of a binary frame (including the SOF pair that starts one) are consumed
 * there and never reach the line buffer - see uart_frame.c's file-header
 * comment for how that arbitration works. A completed frame is dispatched
 * immediately, mid-line, without disturbing whatever ASCII the user has
 * typed so far. Also services capture-completion each pass, so a capture
 * finishing mid-line prints its banner (or, for a frame-sourced capture,
 * gets drained and pushed) without waiting for \r. */
static uint8_t read_line(char *buf, uint8_t max_len)
{
    uint8_t len = 0;

    for (;;)
    {
        service_capture_completion();

        if (!uart_rx_ready())
        {
            continue;
        }

        uint8_t c = uart_getc();

        rx_frame_t        frame;
        frame_rx_result_t rx_result = uart_frame_rx_feed(c, &frame);

        switch (rx_result)
        {
            case FRAME_RX_CONSUMED:
                continue;
            case FRAME_RX_COMPLETE:
                handle_frame_command(&frame);
                continue;
            case FRAME_RX_BAD_CRC:
            case FRAME_RX_OVERSIZE:
                uart_frame_send_reply(FRAME_TYPE_NAK, (const uint8_t *)0, 0);
                continue;
            case FRAME_RX_NOT_FRAME:
            default:
                break;   /* not part of a frame - fall through to ASCII handling */
        }

        if (c == '\r' || c == '\n')
        {
            buf[len] = '\0';
            print_str("\r\n");
            return 1;
        }

        if (len < (uint8_t)(max_len - 1U))
        {
            buf[len++] = (char)c;
            uart_putc(c);   /* local echo, since most terminals don't do it for you */
        }
    }
}

static uint8_t str_eq(const char *a, const char *b)
{
    while (*a && *b)
    {
        if (*a != *b)
        {
            return 0;
        }
        a++;
        b++;
    }
    return (*a == '\0' && *b == '\0');
}

/* ---------- commands ---------- */

static void cmd_arm(void)
{
    drain_loop_clear_ready();
    arm_pulse();
    cap_state            = CAP_ARMED;
    cap_source           = CAP_SOURCE_CLI;
    have_captured_buffer = 0;
    print_str("Armed. Waiting for trigger.\r\n");
}

static void cmd_status(void)
{
    switch (cap_state)
    {
        case CAP_IDLE:     print_str("IDLE - not armed.\r\n"); break;
        case CAP_ARMED:    print_str("ARMED - waiting for trigger.\r\n"); break;
        case CAP_CAPTURED: print_str("CAPTURED - ready, run 'dump'.\r\n"); break;
    }
}

static void cmd_dump(void)
{
    if (cap_state != CAP_CAPTURED)
    {
        print_str("No capture ready. Run 'arm' first and wait for done.\r\n");
        return;
    }
    drain_loop_run();     /* pulls the 2048 bytes out of the FPGA over the GPIO link */
    have_captured_buffer = 1;
    cap_state = CAP_IDLE; /* buffer consumed; need a fresh arm for the next one */

    const uint8_t *buf = drain_loop_get_buffer();
    for (uint16_t i = 0; i < DRAIN_BUFFER_BYTES; i++)
    {
        print_hex_byte(buf[i]);
        uart_putc(' ');
        if ((i & 0x0FU) == 0x0FU)
        {
            print_str("\r\n");   /* 16 bytes per line */
        }
    }
    print_str("\r\n");
}

static void cmd_rate(const char *arg)
{
    if (arg[0] < '0' || arg[0] > '3' || arg[1] != '\0')
    {
        print_str("Usage: rate <0-3>  (0=10MS/s 1=1MS/s 2=100kS/s 3=10kS/s)\r\n");
        return;
    }
    uint8_t r = (uint8_t)(arg[0] - '0');
    rate_set(r);
    print_str("Rate set to ");
    uart_putc((uint8_t)arg[0]);
    print_str(".\r\n");
}

/* ---------- selftest (brief section 9) ---------- */

/* Arms and, separately, waits-then-drains - split in two so each stage can
 * arm right before it starts driving the probe signal (the FPGA's capture
 * start is edge-triggered off that signal, so the two have to be adjacent
 * in time) without duplicating the wait/timeout/drain bookkeeping six times. */
static void selftest_arm(void)
{
    /* Every stage's trigger depends on MOSI being low when its pattern's
     * first 1-bit arrives, since the FPGA triggers on a RISING edge and
     * `polarity` is a board switch firmware can't drive - but the previous
     * stage can leave MOSI at either level (e.g. stage_ramp's last byte,
     * 0x93, ends on a 1). Park it low with a dummy 0x00 byte first, before
     * the FPGA is armed: if the park happened after arm_pulse(), the park
     * transfer's own transition would occur while the FPGA is already
     * watching for an edge, and (level-dependent) risks being mistaken for
     * the real trigger instead of the pattern that follows it. Clearing the
     * stale ready flag comes after the park and right before arm_pulse(),
     * so nothing between the clear and the real arm can set it again. */
    spi_test_send_byte(0x00U, SELFTEST_BIT_RATE_HZ);
    drain_loop_clear_ready();
    arm_pulse();
    cap_state = CAP_ARMED;
}

static uint8_t selftest_wait_and_drain(uint32_t timeout_ms)
{
    uint32_t waited_ms = 0;
    while (!drain_loop_ready() && waited_ms < timeout_ms)
    {
        delay_us(1000);
        waited_ms++;
    }

    if (!drain_loop_ready())
    {
        cap_state = CAP_IDLE;
        drain_loop_clear_ready();
        return 0;
    }

    cap_state = CAP_CAPTURED;
    drain_loop_run();
    cap_state = CAP_IDLE;
    return 1;
}

/* Majority-decodes the just-drained buffer at the middle of each bit's
 * window (to sit clear of edge jitter) and compares against
 * expected[0..expected_bytes), MSB-first per byte - matching how
 * drain_loop_run() packs samples. Stops (and reports success) if the
 * buffer runs out before expected_bytes is exhausted, since a short
 * buffer isn't itself a decode error.
 *
 * actual_clock_hz is the real, achieved SPI clock (from
 * spi_test_actual_clock_hz()), not the requested one - SPI1's BR[2:0]
 * prescaler only hits specific clocks, so the requested rate is rarely
 * exact. Each sample index is recomputed from bit_index * SAMPLE_RATE /
 * actual_clock_hz rather than accumulated via an integer samples-per-bit
 * step: at 421875 Hz the real rate is 23.70 samples/bit, and truncating
 * that to 23 drifts by ~0.70 samples every bit - 113 samples (4.7
 * bit-widths) of drift by bit 160. Recomputing fresh each time avoids
 * that compounding error. */
static uint8_t verify_spi_pattern(const uint8_t *expected, uint16_t expected_bytes, uint32_t actual_clock_hz)
{
    const uint8_t *buf = drain_loop_get_buffer();

    for (uint16_t byte_i = 0; byte_i < expected_bytes; byte_i++)
    {
        for (uint8_t bit_i = 0; bit_i < 8U; bit_i++)
        {
            uint32_t bit_index = (uint32_t)byte_i * 8U + bit_i;
            uint32_t sample_index = (bit_index * SELFTEST_SAMPLE_RATE_HZ) / actual_clock_hz
                                     + (SELFTEST_SAMPLE_RATE_HZ / actual_clock_hz) / 2U;
            if (sample_index >= DRAIN_SAMPLE_COUNT)
            {
                return 1;
            }

            uint8_t got = (buf[sample_index >> 3] >> (7U - (sample_index & 7U))) & 0x1U;
            uint8_t want = (expected[byte_i] >> (7U - bit_i)) & 0x1U;
            if (got != want)
            {
                print_str("(mismatch at byte ");
                print_uint(byte_i);
                print_str(" bit ");
                print_uint(bit_i);
                print_str(") ");
                return 0;
            }
        }
    }
    return 1;
}

/* [1/6] Redefined from the original "bypass capture" idea, which doesn't
 * match anything in the actual arm/rd_strobe/data interface - there's no
 * separate diagnostic readout path. This drives an incrementing byte
 * sequence through the normal SPI+capture+drain path instead, exercising
 * every bit value across a full byte range rather than one fixed pattern. */
static uint8_t stage_ramp(void)
{
    print_str("[1/6] Ramp: ");

    /* First byte's MSB must be 1: the FPGA triggers on the probe's first
     * RISING edge, and the buffer is recorded starting from that edge. A
     * ramp starting at 0x00 has its first 1-bit at bit 15 (0x01's LSB), so
     * the trigger would fire 15 bit-times late and every sample after it
     * would be misaligned against verify_spi_pattern's expected bit
     * positions. Starting at 0x80 puts a 1 in bit 0, so the trigger fires
     * on the very first bit and the rest of the ramp lines up. */
    uint8_t pattern[20];
    for (uint8_t i = 0; i < 20U; i++)
    {
        pattern[i] = (uint8_t)(0x80U + i);
    }

    selftest_arm();
    spi_test_send_bytes(pattern, sizeof(pattern), SELFTEST_BIT_RATE_HZ);

    if (!selftest_wait_and_drain(5000U))
    {
        print_str("FAIL (capture timed out)\r\n");
        return 0;
    }
    if (!verify_spi_pattern(pattern, sizeof(pattern), spi_test_actual_clock_hz(SELFTEST_BIT_RATE_HZ)))
    {
        print_str("FAIL\r\n");
        return 0;
    }
    print_str("PASS\r\n");
    return 1;
}

/* [2/6] Both levels in a single triggered capture instead of two. The
 * capture core only fires on a RISING edge, and a lone 0x00 byte sent
 * after MOSI has settled high (the end of the previous stage/idle state)
 * produces just a falling edge - it would never trigger. Sending {0xFF,
 * 0x00} back to back gives exactly one rising edge (0xFF's leading edge)
 * to trigger on; the 0x00 byte's falling edge then happens mid-window,
 * with MOSI held low by the driver for the rest of the capture, same as
 * before. So the first byte's worth of samples (8 bit-times at the actual
 * SPI clock) must read all-1, and everything after the guard band below
 * must read all-0. */
static uint8_t stage_static_levels(void)
{
    print_str("[2/6] Static levels: ");

    uint8_t pattern[2] = { 0xFFU, 0x00U };

    /* Boundary between the two levels, in samples: 8 bit-times at the
     * ACTUAL SPI clock (spi_test_actual_clock_hz()), not the unachievable
     * 100 kHz - at 421875 Hz that's ~190 samples, not 800. */
    uint32_t actual_clock_hz = spi_test_actual_clock_hz(SELFTEST_BIT_RATE_HZ);
    uint32_t high_samples = (8U * SELFTEST_SAMPLE_RATE_HZ) / actual_clock_hz;

    /* The FPGA pipeline (2 sync flops + 1 trigger flop + the N+1 divider
     * gap, with the recorded sample itself 2 clocks behind) puts sample 0
     * about 140 ns after the probe edge, which lands the real transition
     * ~1.4 samples earlier than the arithmetic boundary above. Leave a few
     * samples unchecked on either side of it rather than trip on that
     * skew. */
    const uint32_t guard = 3U;

    selftest_arm();
    spi_test_send_bytes(pattern, sizeof(pattern), SELFTEST_BIT_RATE_HZ);
    if (!selftest_wait_and_drain(5000U))
    {
        print_str("FAIL (capture timed out)\r\n");
        return 0;
    }

    const uint8_t *buf = drain_loop_get_buffer();
    for (uint16_t i = 0; i < DRAIN_SAMPLE_COUNT; i++)
    {
        if ((uint32_t)i + guard >= high_samples && i < high_samples + guard)
        {
            continue;   /* inside the guard band around the transition */
        }
        uint8_t bit  = (buf[i >> 3] >> (7U - (i & 7U))) & 0x1U;
        uint8_t want = (i < high_samples) ? 1U : 0U;
        if (bit != want)
        {
            print_str(i < high_samples ? "FAIL (not all 1s)\r\n" : "FAIL (not all 0s)\r\n");
            return 0;
        }
    }

    print_str("PASS\r\n");
    return 1;
}

/* [3/6] Alternating 0xFF/0x00 bytes at the 100 kHz bit rate. 100 kHz isn't
 * actually achievable on SPI1 (see spi_test_actual_clock_hz()), but the
 * transition count doesn't depend on the clock either way: 32 alternating
 * bytes give exactly 31 level changes at the byte boundaries, and the
 * pattern is short enough (~607 us at the slowest achievable clock,
 * 421875 Hz) that it's well within the 16384-sample buffer regardless of
 * rate. This is a transition-count sanity check, not a bit-exact decode -
 * that's what the one-byte/twenty-byte/ramp stages already cover. */
static uint8_t stage_square_wave(void)
{
    print_str("[3/6] Square wave: ");

    uint8_t pattern[32];
    for (uint8_t i = 0; i < 32U; i++)
    {
        pattern[i] = (i & 1U) ? 0x00U : 0xFFU;
    }

    selftest_arm();
    spi_test_send_bytes(pattern, sizeof(pattern), SELFTEST_BIT_RATE_HZ);
    if (!selftest_wait_and_drain(5000U))
    {
        print_str("FAIL (capture timed out)\r\n");
        return 0;
    }

    const uint8_t *buf = drain_loop_get_buffer();
    uint8_t  prev = (buf[0] & 0x80U) ? 1U : 0U;
    uint32_t transitions = 0;
    for (uint16_t i = 0; i < DRAIN_SAMPLE_COUNT; i++)
    {
        uint8_t bit = (buf[i >> 3] >> (7U - (i & 7U))) & 0x1U;
        if (bit != prev)
        {
            transitions++;
            prev = bit;
        }
    }

    uint32_t expected = sizeof(pattern) - 1U;
    print_str("(expected ~");
    print_uint(expected);
    print_str(", got ");
    print_uint(transitions);
    print_str(") ");

    if (transitions < (expected * 3U) / 4U || transitions > (expected * 5U) / 4U)
    {
        print_str("FAIL\r\n");
        return 0;
    }
    print_str("PASS\r\n");
    return 1;
}

/* [4/6] spi_test_send_byte(0xB6, 100kHz): 0xB6 = 0b10110110, MSB-first, so
 * the first sample should be high. 100 samples/bit at 10 MS/s, 800 total. */
static uint8_t stage_one_byte(void)
{
    print_str("[4/6] One byte (0xB6): ");

    uint8_t pattern[1] = { 0xB6U };

    selftest_arm();
    spi_test_send_byte(0xB6U, SELFTEST_BIT_RATE_HZ);
    if (!selftest_wait_and_drain(5000U))
    {
        print_str("FAIL (capture timed out)\r\n");
        return 0;
    }
    if (!verify_spi_pattern(pattern, sizeof(pattern), spi_test_actual_clock_hz(SELFTEST_BIT_RATE_HZ)))
    {
        print_str("FAIL\r\n");
        return 0;
    }
    print_str("PASS\r\n");
    return 1;
}

/* [5/6] Same idea as one-byte, but 20 repeats of the same known-good byte
 * (~16,000 of the 16,384-sample buffer), to stress sustained transmission
 * rather than a single decode. */
static uint8_t stage_twenty_bytes(void)
{
    print_str("[5/6] Twenty bytes (0xB6 x20): ");

    uint8_t pattern[20];
    for (uint8_t i = 0; i < 20U; i++)
    {
        pattern[i] = 0xB6U;
    }

    selftest_arm();
    spi_test_send_bytes(pattern, sizeof(pattern), SELFTEST_BIT_RATE_HZ);
    if (!selftest_wait_and_drain(5000U))
    {
        print_str("FAIL (capture timed out)\r\n");
        return 0;
    }
    if (!verify_spi_pattern(pattern, sizeof(pattern), spi_test_actual_clock_hz(SELFTEST_BIT_RATE_HZ)))
    {
        print_str("FAIL\r\n");
        return 0;
    }
    print_str("PASS\r\n");
    return 1;
}

/* [6/6] Repeats the one-byte test at doubling SPI clock until the decoded
 * pattern stops matching, or samples/bit drops below 2 (no meaningful
 * decode possible below that, regardless of hardware - stop rather than
 * clock indefinitely). Reports the clock it broke at, per the brief. */
static uint8_t stage_push_until_break(void)
{
    print_str("[6/6] Push until it breaks: ");

    uint8_t  pattern[1] = { 0xB6U };
    uint32_t clock_hz   = SELFTEST_BIT_RATE_HZ;
    uint32_t last_good  = 0;

    for (;;)
    {
        uint32_t actual_clock_hz = spi_test_actual_clock_hz(clock_hz);
        uint32_t samples_per_bit = SELFTEST_SAMPLE_RATE_HZ / actual_clock_hz;
        if (samples_per_bit < 2U)
        {
            break;
        }

        selftest_arm();
        spi_test_send_byte(0xB6U, clock_hz);
        if (!selftest_wait_and_drain(5000U))
        {
            print_str("FAIL (capture timed out during sweep)\r\n");
            return 0;
        }

        if (!verify_spi_pattern(pattern, sizeof(pattern), actual_clock_hz))
        {
            break;
        }

        last_good = actual_clock_hz;
        clock_hz *= 2U;
    }

    if (last_good == 0U)
    {
        print_str("FAIL (broke immediately at 100 kHz)\r\n");
        return 0;
    }

    print_str("PASS - held up to ");
    print_uint(last_good);
    print_str(" Hz, broke at ");
    print_uint(spi_test_actual_clock_hz(clock_hz));
    print_str(" Hz (datasheet figure)\r\n");
    return 1;
}

static void cmd_selftest(void)
{
    /* Every stage's sample-count math assumes rate 0 (10 MS/s) - force it
     * rather than trust whatever the CLI was last left at. */
    rate_set(0);

    print_str("\r\n--- selftest ---\r\n");
    uint8_t passed = 0;
    passed = (uint8_t)(passed + stage_ramp());
    passed = (uint8_t)(passed + stage_static_levels());
    passed = (uint8_t)(passed + stage_square_wave());
    passed = (uint8_t)(passed + stage_one_byte());
    passed = (uint8_t)(passed + stage_twenty_bytes());
    passed = (uint8_t)(passed + stage_push_until_break());

    print_str("--- ");
    print_uint(passed);
    print_str("/6 stages passed ---\r\n");
}

/* The existing auto-repeat behavior, unchanged in substance from the
 * old main.c loop - just moved here and given an exit path. Any byte
 * arriving on UART breaks out back to the idle prompt instead of
 * being silently swallowed, since drain_loop_run()/uart_frame_send()
 * would otherwise never let the CLI back in. */
static void cmd_repeat(void)
{
    print_str("Repeating. Send any byte to stop.\r\n");
    drain_loop_clear_ready();
    arm_pulse();

    uint32_t last_end_tick = 0;
    uint8_t  have_last_end = 0;

    for (;;)
    {
        if (drain_loop_ready())
        {
            /* t0 doubles as both "start of drain" and, via last_end_tick,
             * the far end of the dead-time window from the prior cycle. */
            uint32_t t0 = DWT->CYCCNT;

            if (have_last_end)
            {
                dead_time_us = cycles_to_us(t0 - last_end_tick);
            }

            drain_loop_run();
            drain_time_us = cycles_to_us(DWT->CYCCNT - t0);

            t0 = DWT->CYCCNT;
            uart_frame_send_config();
            uart_frame_send();
            transfer_time_us = cycles_to_us(DWT->CYCCNT - t0);

            last_end_tick   = DWT->CYCCNT;
            have_last_end   = 1;
            have_timing_data = 1;

            arm_pulse();
        }
        if (uart_rx_ready())
        {
            (void)uart_getc();   /* discard the byte that broke the loop */
            print_str("\r\nStopped.\r\n");
            cap_state = CAP_IDLE;
            return;
        }
    }
}

static void cmd_timing(void)
{
    if (!have_timing_data)
    {
        print_str("no data yet\r\n");
        return;
    }
    print_timing_line("drain:", 6U, drain_time_us);
    print_timing_line("transfer:", 9U, transfer_time_us);
    print_timing_line("dead:", 5U, dead_time_us);
}

/* ---------- dispatch ---------- */

void cli_init(void)
{
    rate_set(0);
    drain_loop_clear_ready();
    arm_pulse();          /* defensive: see cli.h doc comment */
    cap_state  = CAP_ARMED;
    cap_source = CAP_SOURCE_CLI;
}

void cli_run(void)
{
    char line[CLI_LINE_MAX];
    print_str("\r\nlogic analyzer ready.\r\n> ");

    for (;;)
    {
        if (!read_line(line, CLI_LINE_MAX))
        {
            continue;
        }

        if (str_eq(line, "arm"))              { cmd_arm(); }
        else if (str_eq(line, "status"))      { cmd_status(); }
        else if (str_eq(line, "dump"))        { cmd_dump(); }
        else if (str_eq(line, "test"))        { cmd_selftest(); }
        else if (str_eq(line, "selftest"))    { cmd_selftest(); }
        else if (str_eq(line, "repeat"))      { cmd_repeat(); }
        else if (str_eq(line, "timing"))      { cmd_timing(); }
        else if (line[0] == 'r' && line[1] == 'a' && line[2] == 't'
                  && line[3] == 'e' && line[4] == ' ')
        {
            cmd_rate(&line[5]);
        }
        else if (line[0] != '\0')
        {
            print_str("Unknown command. Try: arm status dump rate selftest repeat timing\r\n");
        }

        print_str("> ");
    }
}
