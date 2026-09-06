#ifndef SPI_TEST_H
#define SPI_TEST_H

#include <stdint.h>

void spi_test_init(void);

/* Sends one byte, MSB first, at the given SPI clock in Hz (approx -
 * actual rate is the nearest achievable prescaler division of the
 * peripheral clock). Blocks until transmission completes. */
void spi_test_send_byte(uint8_t byte, uint32_t clock_hz);

/* Sends `len` bytes from `data`, back to back, at the given clock. */
void spi_test_send_bytes(const uint8_t *data, uint16_t len, uint32_t clock_hz);

/* Returns the SPI clock the hardware will actually produce for a request
 * of requested_hz - the nearest achievable BR[2:0] prescaler division of
 * SPI1's peripheral clock, not the requested value itself. */
uint32_t spi_test_actual_clock_hz(uint32_t requested_hz);

#endif /* SPI_TEST_H */
