#include "spi_test.h"
#include "pin_config.h"
#include "stm32f7xx_hal.h"

/* SPI1 hangs off APB2. Hardcoded for the same reason UART_PCLK_HZ is in
 * uart_frame.c: it's now computed by hand instead of HAL doing it, so if
 * SystemClock_Config()'s APB2CLKDivider ever changes, this has to change
 * with it. */
#define SPI1_PCLK_HZ    108000000U

/* Finds the BR[2:0] value (divider = 2^(BR+1), i.e. /2 up to /256) whose
 * resulting clock is closest to clock_hz - same nearest-available-divider
 * rounding used for the UART BRR calculation. */
static uint8_t spi_prescaler_for_clock(uint32_t clock_hz)
{
    uint8_t  best_br   = 0;
    uint32_t best_diff = 0xFFFFFFFFU;

    for (uint8_t br = 0; br <= 7U; br++)
    {
        uint32_t achieved = SPI1_PCLK_HZ >> (br + 1U);
        uint32_t diff = (achieved > clock_hz) ? (achieved - clock_hz) : (clock_hz - achieved);
        if (diff < best_diff)
        {
            best_diff = diff;
            best_br   = br;
        }
    }
    return best_br;
}

uint32_t spi_test_actual_clock_hz(uint32_t requested_hz)
{
    return SPI1_PCLK_HZ >> (spi_prescaler_for_clock(requested_hz) + 1U);
}

/* BR is only safe to change while SPE is 0. Everything else in CR1 (MSTR,
 * SSM, SSI, MSB-first) is set once in spi_test_init() and preserved here. */
static void spi_configure_clock(uint32_t clock_hz)
{
    uint8_t br = spi_prescaler_for_clock(clock_hz);

    SPI1->CR1 &= ~SPI_CR1_SPE;
    SPI1->CR1  = (SPI1->CR1 & ~SPI_CR1_BR) | ((uint32_t)br << SPI_CR1_BR_Pos);
    SPI1->CR1 |= SPI_CR1_SPE;
}

void spi_test_init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_SPI1_CLK_ENABLE();

    /* SCK (PA5) is configured because the peripheral needs it internally to
     * shift MOSI out, even though only MOSI (PA7) is wired to the FPGA. */
    GPIO_InitTypeDef cfg = {0};
    cfg.Pin       = SPI_SCK_PIN | SPI_MOSI_PIN;
    cfg.Mode      = GPIO_MODE_AF_PP;
    cfg.Pull      = GPIO_NOPULL;
    cfg.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    cfg.Alternate = GPIO_AF5_SPI1;
    HAL_GPIO_Init(SPI_MOSI_PORT, &cfg);   /* SCK and MOSI are both on GPIOA */

    /* Master, MSB first (LSBFIRST left clear), mode 0 (CPOL=0/CPHA=0, both
     * left clear). SSM+SSI: software NSS forced high - no NSS pin is used,
     * there's no slave to select, and without this MSTR would fault-clear
     * itself the instant SPE is set (NSS floats with no hardware pin). */
    SPI1->CR1 = SPI_CR1_MSTR | SPI_CR1_SSM | SPI_CR1_SSI;

    /* 8-bit data frames (DS = 0b0111). FRXTH is irrelevant - RX is never
     * read in this transmit-only driver. */
    SPI1->CR2 = (uint32_t)7U << SPI_CR2_DS_Pos;
}

/* With DS set to 8-bit frames, the reference manual requires DR be accessed
 * with 8-bit instructions, not the 32-bit access the struct's uint32_t
 * member would otherwise generate - hence the explicit byte-pointer cast. */
static void spi_write_byte(uint8_t byte)
{
    while (!(SPI1->SR & SPI_SR_TXE)) { }
    *(volatile uint8_t *)&SPI1->DR = byte;
}

void spi_test_send_byte(uint8_t byte, uint32_t clock_hz)
{
    spi_configure_clock(clock_hz);
    spi_write_byte(byte);
    while (!(SPI1->SR & SPI_SR_TXE)) { }
    while (SPI1->SR & SPI_SR_BSY) { }
}

void spi_test_send_bytes(const uint8_t *data, uint16_t len, uint32_t clock_hz)
{
    spi_configure_clock(clock_hz);

    for (uint16_t i = 0; i < len; i++)
    {
        spi_write_byte(data[i]);
    }

    while (!(SPI1->SR & SPI_SR_TXE)) { }
    while (SPI1->SR & SPI_SR_BSY) { }
}
