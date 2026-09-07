#ifndef PIN_CONFIG_H
#define PIN_CONFIG_H

#include "stm32f7xx_hal.h"

#define ARM_PORT        GPIOB
#define ARM_PIN         GPIO_PIN_6
#define RD_STROBE_PORT  GPIOB
#define RD_STROBE_PIN   GPIO_PIN_11
#define DATA_PORT       GPIOC
#define DATA_PIN        GPIO_PIN_7
#define DONE_PORT       GPIOE
#define DONE_PIN        GPIO_PIN_13
#define RATE0_PORT      GPIOB
#define RATE0_PIN       GPIO_PIN_4
#define RATE1_PORT      GPIOB
#define RATE1_PIN       GPIO_PIN_5

/* SPI1, AF5. PA5/PA6/PA7 is the standard SPI1 mapping on this family; the
 * alternative (PB3/PB4/PB5) conflicts with RATE0/RATE1 above, which already
 * claim PB4/PB5 (also the Arduino SPI1 header pins - see project notes).
 * MISO (PA6) is left unclaimed: transmit-only, nothing reads it. SCK (PA5)
 * still has to be configured on the STM32 side (the peripheral needs it
 * internally to shift MOSI out) even though only MOSI is wired to the FPGA. */
#define SPI_SCK_PORT    GPIOA
#define SPI_SCK_PIN     GPIO_PIN_5
#define SPI_MOSI_PORT   GPIOA
#define SPI_MOSI_PIN    GPIO_PIN_7

#endif /* PIN_CONFIG_H */
