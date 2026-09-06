#ifndef GPIO_DRIVER_H
#define GPIO_DRIVER_H

#include <stdint.h>

void gpio_init(void);
void arm_pulse(void);
void rd_strobe_pulse(void);
uint8_t data_read(void);
void rate_set(uint8_t rate);
uint8_t rate_get(void);

#endif /* GPIO_DRIVER_H */
