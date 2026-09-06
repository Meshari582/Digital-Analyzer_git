#ifndef DRAIN_LOOP_H
#define DRAIN_LOOP_H

#include <stdint.h>

#define DRAIN_SAMPLE_COUNT  16384U
#define DRAIN_BUFFER_BYTES  (DRAIN_SAMPLE_COUNT / 8U)

void drain_loop_init(void);
void drain_loop_run(void);
uint8_t drain_loop_ready(void);
void drain_loop_clear_ready(void);
const uint8_t *drain_loop_get_buffer(void);

/* Exposed for gpio_driver.c's pulse-width timing; not a drain-loop concern itself. */
void delay_us(uint32_t us);

/* Sub-microsecond DWT delay, for the drain loop's per-sample settle wait.
 * Rounds up (ceiling), never returns early - see drain_loop.c. */
void delay_ns(uint32_t ns);

#endif /* DRAIN_LOOP_H */
