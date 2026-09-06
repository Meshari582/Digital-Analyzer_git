#include "drain_loop.h"
#include "gpio_driver.h"
#include "pin_config.h"

static volatile uint8_t ready_flag;
static uint8_t sample_buffer[DRAIN_BUFFER_BYTES];

static void dwt_init(void)
{
    /* DEMCR.TRCENA must be set before any other DWT/ITM register access -
     * per the ARMv7-M architecture reference, those blocks aren't guaranteed
     * accessible until it's enabled. Getting this backwards means the LAR
     * unlock below is a no-op, DWT stays locked, CTRL|=CYCCNTENA is silently
     * dropped, and delay_us() spins forever on the first call. */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->LAR = 0xC5ACCE55;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

void delay_us(uint32_t us)
{
    uint32_t start = DWT->CYCCNT;
    uint32_t cycles = (SystemCoreClock / 1000000U) * us;
    while ((DWT->CYCCNT - start) < cycles);
}

/* SystemCoreClock/1000000U is cycles-per-microsecond, not cycles-per-nanosecond -
 * an earlier version of this used SystemCoreClock/1000U (cycles-per-millisecond)
 * for a nanosecond delay, which is 1000x too large. cycles-per-ns is a fraction
 * (216 MHz -> 0.216 cyc/ns), so do the multiply before the divide and round up:
 * a delay that's too short defeats the settle time it exists for, a delay that's
 * a few ns too long just costs a few ns. */
void delay_ns(uint32_t ns)
{
    uint32_t start  = DWT->CYCCNT;
    uint32_t cycles = ((SystemCoreClock / 1000000U) * ns + 999U) / 1000U;
    while ((DWT->CYCCNT - start) < cycles);
}

void drain_loop_init(void)
{
    dwt_init();
}

uint8_t drain_loop_ready(void)
{
    return ready_flag;
}

void drain_loop_clear_ready(void)
{
    ready_flag = 0;
}

const uint8_t *drain_loop_get_buffer(void)
{
    return sample_buffer;
}

void drain_loop_run(void)
{
    ready_flag = 0;
    uint8_t byte = 0;

    for (uint32_t i = 0; i < DRAIN_SAMPLE_COUNT; i++)
    {
        /* Read first: data_out already holds the sample at the current raddr.
         * The strobe then advances to the next one, ready for iteration i+1.
         *
         * Settle budget, measured from the strobe's rising edge (not from
         * rd_strobe_pulse()'s return): its requested 60 ns hold (really
         * ~100-120 ns, see rd_strobe_pulse()) counts toward it, plus ~150 ns
         * more for the FPGA's clk-to-out, board delay and +-20 ns async
         * quantisation before `data` is valid for the next iteration's
         * read. Total per sample - hold + this + loop overhead - lands
         * around 300 ns, so ~5 ms for the full 16384-sample drain. */
        byte = (byte << 1) | data_read();
        rd_strobe_pulse();
        delay_ns(150);

        if ((i & 7U) == 7U)
        {
            sample_buffer[i >> 3] = byte;
            byte = 0;
        }
    }
}

/* Lines 10..15 share this vector; DONE (line 12) is the only one this
 * project unmasks (see gpio_init()'s EXTI->IMR write), so no other line can
 * pend here - but PR is tested rather than assumed, and only DONE_PIN's bit
 * is cleared, so an unrelated line pending here (should EXTI->IMR ever gain
 * one) can't be silently eaten. PR is rc_w1 (RM0410 EXTI section, "Pending
 * register") - writing 1 clears just that bit, 0s elsewhere are no-ops. */
void EXTI15_10_IRQHandler(void)
{
    if (EXTI->PR & DONE_PIN)
    {
        EXTI->PR = DONE_PIN;
        ready_flag = 1;
    }
}
