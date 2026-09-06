#include "gpio_driver.h"
#include "pin_config.h"
#include "drain_loop.h"

typedef struct
{
    GPIO_TypeDef *port;
    uint32_t      pin;
} gpio_pin_t;

/* Last value passed to rate_set() - lets uart_frame.c's CONFIG frame read
 * back the active rate instead of tracking its own copy. */
static uint8_t last_rate;

void gpio_init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOF_CLK_ENABLE();

    /* REQUIRED for EXTI. HAL_GPIO_Init() used to write SYSCFG->EXTICR[] to
     * select which PORT drives a given EXTI line; we do that write directly
     * below. With the SYSCFG clock off that write is silently discarded -
     * no fault, no warning. It only appeared to work before because EXTICR
     * resets to 0, which selects port A, and DONE happened to be on PA9.
     * Move DONE to any other port without this line and the interrupt just
     * never fires. */
    __HAL_RCC_SYSCFG_CLK_ENABLE();

    /* ARM, RD_STROBE, RATE0, RATE1: push-pull output, no pull, high speed.
     * Paired with their own *_PORT macro (not a literal GPIOB) so this
     * breaks loudly, not silently, if one of them is ever moved.
     * MODER/OSPEEDR/PUPDR are 2 bits per pin; OTYPER is 1 bit per pin. */
    static const gpio_pin_t OUTPUT_PINS[4] =
    {
        { ARM_PORT,       ARM_PIN       },
        { RD_STROBE_PORT, RD_STROBE_PIN },
        { RATE0_PORT,     RATE0_PIN     },
        { RATE1_PORT,     RATE1_PIN     },
    };

    for (uint32_t i = 0; i < 4U; i++)
    {
        GPIO_TypeDef *port = OUTPUT_PINS[i].port;
        uint32_t      pin  = OUTPUT_PINS[i].pin;
        uint32_t      pos  = POSITION_VAL(pin);

        port->MODER   = (port->MODER   & ~(3UL << (pos * 2U))) | (1UL << (pos * 2U));
        port->OSPEEDR = (port->OSPEEDR & ~(3UL << (pos * 2U))) | (2UL << (pos * 2U));
        port->PUPDR  &= ~(3UL << (pos * 2U));
        port->OTYPER &= ~pin;
    }

    /* DATA: floating input. MODER 00 = input, PUPDR 00 = no pull. */
    uint32_t data_pos = POSITION_VAL(DATA_PIN);
    DATA_PORT->MODER &= ~(3UL << (data_pos * 2U));
    DATA_PORT->PUPDR &= ~(3UL << (data_pos * 2U));

    /* DONE: floating input, rising-edge EXTI. */
    uint32_t done_pos = POSITION_VAL(DONE_PIN);
    DONE_PORT->MODER &= ~(3UL << (done_pos * 2U));
    DONE_PORT->PUPDR &= ~(3UL << (done_pos * 2U));

    /* Route DONE's EXTI line to its port. Line n's 4-bit port-select field
     * lives at EXTICR[n/4], nibble position (n%4)*4. GPIO_GET_INDEX follows
     * DONE_PORT so this can't silently point at the wrong port if DONE
     * moves again. */
    SYSCFG->EXTICR[done_pos >> 2] =
        (SYSCFG->EXTICR[done_pos >> 2] & ~(0xFUL << ((done_pos & 3U) * 4U)))
        | ((uint32_t)GPIO_GET_INDEX(DONE_PORT) << ((done_pos & 3U) * 4U));

    EXTI->RTSR |= DONE_PIN;   /* trigger on rising edge */
    EXTI->FTSR &= ~DONE_PIN;  /* not falling edge */
    EXTI->IMR  |= DONE_PIN;   /* unmask -> routed to NVIC */

    /* Drive the handshake lines to a known state before anyone uses them.
     * ODR does reset to 0, but relying on that means the first arm_pulse()
     * depends on an assumption rather than on something we did. The FPGA
     * edge-detects these, so a clean starting level matters. */
    ARM_PORT->BSRR       = (uint32_t)ARM_PIN << 16;
    RD_STROBE_PORT->BSRR = (uint32_t)RD_STROBE_PIN << 16;
    rate_set(0);

    /* Pins 10..15 share the EXTI15_10 vector. DONE is on pin 12 today. If it
     * moves outside 10..15, change both this IRQn and the handler in
     * drain_loop.c. */
    HAL_NVIC_SetPriority(EXTI15_10_IRQn, 5, 0);
    HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);
}

void arm_pulse(void)
{
    ARM_PORT->BSRR = ARM_PIN;
    delay_us(1);
    ARM_PORT->BSRR = (uint32_t)ARM_PIN << 16;
}

/* Must outlast one FPGA clock period (20 ns @ 50 MHz) plus setup/board
 * margin for the 2-flop synchroniser to reliably catch the edge - budgeted
 * at >=60 ns (3 FPGA clocks).
 *
 * NOT an unrolled __NOP() chain: the ARMv7-M ARM explicitly says NOP "is
 * not necessarily a time-consuming NOP" - the M7's dual-issue front end can
 * fold them to near-zero cost, which would silently collapse this hold and
 * cause exactly the intermittent missed-edge failure this delay exists to
 * prevent. delay_ns() is DWT-cycle-counted, so it's a real elapsed-time
 * floor regardless of how the compiler/pipeline treat any given
 * instruction. Its own read-subtract-compare overhead (~10 cycles/~46 ns)
 * means the requested 60 ns actually lands around 100-120 ns - looser than
 * the NOP estimate, but guaranteed rather than hopeful. Verify the real
 * width with SignalTap on rd_strobe_sync once on the bench. */
void rd_strobe_pulse(void)
{
    RD_STROBE_PORT->BSRR = RD_STROBE_PIN;
    delay_ns(60);
    RD_STROBE_PORT->BSRR = (uint32_t)RD_STROBE_PIN << 16;
}

uint8_t data_read(void)
{
    return (DATA_PORT->IDR & DATA_PIN) ? 1U : 0U;
}

void rate_set(uint8_t rate)
{
    RATE0_PORT->BSRR = (rate & 0x1U) ? RATE0_PIN : ((uint32_t)RATE0_PIN << 16);
    RATE1_PORT->BSRR = (rate & 0x2U) ? RATE1_PIN : ((uint32_t)RATE1_PIN << 16);
    last_rate = rate;
}

uint8_t rate_get(void)
{
    return last_rate;
}
