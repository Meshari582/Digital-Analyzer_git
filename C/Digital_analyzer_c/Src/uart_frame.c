/* ============================================================================
 * Wire protocol direction scheme (PROTOCOL_VERSION 2, see uart_frame.h)
 * ============================================================================
 * PC <-> MCU direction is encoded by giving MCU->PC-only meanings their own
 * type code, rather than reusing a PC->MCU code with a direction-dependent
 * payload. Concretely: PROTOCOL_VERSION 1 sent FRAME_TYPE_CONFIG (type 0)
 * MCU->PC carrying capture metadata (rate/sample_count/trigger_latency_ns);
 * that collided with the brief's PC->MCU CONFIG command (set the rate). V2
 * splits them - FRAME_TYPE_CONFIG (0) is PC->MCU only, and the MCU->PC
 * metadata frame moved to the new FRAME_TYPE_CAPTURE_INFO (8). FRAME_TYPE_
 * STATUS (3) is the one type used both directions (empty PC request, 1-byte
 * MCU reply) - no collision there since request and reply are the only two
 * possible meanings and they're distinguishable by direction alone.
 *
 * Every RX frame's VER byte is checked against PROTOCOL_VERSION; a mismatch
 * gets FRAME_TYPE_ERROR instead of being processed, so a stale v1 PC client
 * fails loudly instead of getting CONFIG's meaning silently swapped on it.
 *
 * ASCII CLI text and binary frames share one UART. Frames start with the
 * two-byte sequence FRAME_SOF0 FRAME_SOF1 (0x55 0xAA); uart_frame_rx_feed()
 * is a non-blocking, one-byte-per-call state machine that recognises this
 * prefix and, everywhere else, reports FRAME_RX_NOT_FRAME so the caller
 * (cli.c) can fall through to ordinary line buffering. A lone 0x55 not
 * followed by 0xAA is a false start: the state machine backs out to
 * WAIT_SOF0 and reports the *next* byte as FRAME_RX_NOT_FRAME, but the 0x55
 * itself is not replayed into the ASCII stream - an un-echoed stray 'U'
 * before something that isn't a valid frame is an accepted, documented
 * tradeoff, not a bug (see uart_frame.h for the full type table).
 * ============================================================================
 */
#include "uart_frame.h"
#include "drain_loop.h"
#include "gpio_driver.h"

#ifndef UART_FRAME_HOST_TEST
#include "stm32f7xx_hal.h"
#endif

#define UART_BAUD_RATE      921600U

/* APB1 clock feeding USART3. Hardcoded because BRR is now computed by hand
 * instead of HAL_UART_Init() doing it from HAL_RCC_GetPCLK1Freq() - if
 * SystemClock_Config()'s APB1CLKDivider ever changes, this has to change
 * with it or the baud rate silently drifts. */
#define UART_PCLK_HZ        54000000U

/* Payload bytes per DATA frame. The brief doesn't fix this - chosen to keep
 * each frame (SOF+header+payload+CRC = 262 bytes) well clear of any UART
 * buffer limit, while cleanly dividing DRAIN_BUFFER_BYTES (2048 / 256 = 8
 * frames per capture). */
#define FRAME_MAX_PAYLOAD   256U

#define FRAME_SOF0  0x55U
#define FRAME_SOF1  0xAAU

static uint16_t frame_seq;

/* div_run's per-rate divide count N, from logic_analyzer_top.v - rate 0-3
 * map to N = 5, 50, 500, 5000.
 *
 * Trigger-to-sample-0 latency is (N+2) FPGA clocks (20 ns @ 50 MHz), not
 * (N+1): 2 sync flops + 1 trigger flop put probe_trigger in cycle k+3;
 * div_run releases the dividers at posedge k+3; sample_en asserts in cycle
 * k+N+4; buffer writes at posedge k+N+4, storing probe_sync as of posedge
 * k+N+2 (buffer.v's read is registered, one cycle behind). Net: sample 0's
 * sampling instant is (N+2)*20 ns after the trigger edge - simulated at
 * 140/240/340 ns for N=5, matching this formula, not the old (N+1)*20.
 * Residual +-20 ns of async quantisation (the probe edge lands anywhere in
 * the first sync flop's clock period) isn't captured by this figure. */
static const uint16_t TRIGGER_DIVIDER_N[4] = { 5U, 50U, 500U, 5000U };

/* ---------- RX ring buffer ----------
 * Single producer (USART3_IRQHandler), single consumer (the main-loop poll
 * via uart_rx_ready()/uart_getc()), so plain volatile head/tail with no
 * critical section is sufficient - the two sides never write the same
 * variable. Power-of-two size for cheap masking. 256 bytes covers the
 * worst realistic blocking window (a frame-sourced capture's drain+send is
 * ~6.5 ms =~ 600 bytes at 921600 baud is more than that, but the PC only
 * ever sends ~14-byte command frames while the MCU's busy, not a stream) -
 * genuine overflow isn't expected under normal traffic; the counter below
 * exists to prove that rather than assume it. */
#define UART_RX_BUF_SIZE  256U

static volatile uint8_t  rx_buf[UART_RX_BUF_SIZE];
static volatile uint16_t rx_head;
static volatile uint16_t rx_tail;
static volatile uint32_t rx_overflow_count;

/* The actual ring-buffer push, factored out of the ISR so it's callable
 * (and host-testable) without touching any peripheral register - the ISR
 * itself just reads USART3 and hands the byte here. On a full buffer the
 * newest byte is dropped and counted; tail is never touched from here,
 * since advancing it is the consumer's job and doing it from the ISR would
 * race uart_getc(). */
static void uart_rx_isr_push(uint8_t byte)
{
    uint16_t head = rx_head;
    uint16_t next = (uint16_t)((head + 1U) & (UART_RX_BUF_SIZE - 1U));

    if (next != rx_tail)
    {
        rx_buf[head] = byte;
#ifndef UART_FRAME_HOST_TEST
        __DMB();   /* the byte must be visible before head moves past it */
#endif
        rx_head = next;
    }
    else
    {
        rx_overflow_count++;
    }
}

uint8_t uart_rx_ready(void)
{
    return (rx_head != rx_tail) ? 1U : 0U;
}

uint8_t uart_getc(void)
{
    uint16_t tail = rx_tail;
    uint8_t  c    = rx_buf[tail];
    rx_tail = (uint16_t)((tail + 1U) & (UART_RX_BUF_SIZE - 1U));
    return c;
}

uint32_t uart_rx_overflow_count(void)
{
    return rx_overflow_count;
}

#ifndef UART_FRAME_HOST_TEST

void uart_frame_init(void)
{
    __HAL_RCC_GPIOD_CLK_ENABLE();
    __HAL_RCC_USART3_CLK_ENABLE();

    GPIO_InitTypeDef cfg = {0};
    cfg.Pin       = GPIO_PIN_8 | GPIO_PIN_9;
    cfg.Mode      = GPIO_MODE_AF_PP;
    cfg.Pull      = GPIO_PULLUP;
    cfg.Speed     = GPIO_SPEED_FREQ_VERY_HIGH;
    cfg.Alternate = GPIO_AF7_USART3;
    HAL_GPIO_Init(GPIOD, &cfg);

    /* BRR = PCLK / baud, rounded to nearest rather than truncated - at
     * 921600 on a 54 MHz APB1 this lands on 915254 baud (~0.7% off), well
     * inside UART tolerance. */
    USART3->BRR = (UART_PCLK_HZ + (UART_BAUD_RATE / 2U)) / UART_BAUD_RATE;

    /* 8N1, TX + RX both on (RX needed for the CLI, not just TX). */
    USART3->CR1 = USART_CR1_TE | USART_CR1_RE;
    USART3->CR1 |= USART_CR1_UE;   /* enable last, after everything else is set */

    /* Clear any RXNE/ORE left over from before UE was set - RM0410 notes
     * these can latch from line noise even while the USART is disabled.
     * Read RDR (clears RXNE) then write ICR (clears ORE, which reading RDR
     * does NOT do on this USART version - see USART3_IRQHandler) before
     * enabling the RX interrupt, so the first IRQ isn't a spurious one. */
    (void)USART3->RDR;
    USART3->ICR = USART_ICR_ORECF;
    USART3->CR1 |= USART_CR1_RXNEIE;

    /* Same priority as EXTI15_10 (DONE) - both handlers are a handful of
     * instructions, no ordering dependency between them. */
    HAL_NVIC_SetPriority(USART3_IRQn, 5, 0);
    HAL_NVIC_EnableIRQ(USART3_IRQn);
}

void uart_putc(uint8_t c)
{
    while (!(USART3->ISR & USART_ISR_TXE)) { }   /* wait for TX data register empty */
    USART3->TDR = c;
}

/* USART3 has no RX FIFO on this part, and a frame-sourced capture blocks
 * the main loop for several ms (drain + send) - long enough for the PC to
 * overrun a poll-only RX path. This ISR is why uart_rx_ready()/uart_getc()
 * above read a ring buffer instead of the peripheral directly: bytes are
 * pulled off USART3 the instant they arrive, regardless of what the main
 * loop is doing.
 *
 * Reading RDR clears RXNE on this USART version, but does NOT clear ORE
 * (that's F1/F4 behaviour, not F7/USART v2) - ORE needs an explicit ICR
 * write, and since ORE keeps re-asserting the interrupt (RXNEIE gates both
 * flags) as long as it's set, skipping that write turns this into an
 * interrupt storm rather than the silent-deafness failure it's meant to
 * prevent. ISR is read once into a local so both flags are handled off one
 * consistent snapshot, ORE first. */
void USART3_IRQHandler(void)
{
    uint32_t sr = USART3->ISR;

    if (sr & USART_ISR_ORE)
    {
        USART3->ICR = USART_ICR_ORECF;
    }

    if (sr & USART_ISR_RXNE)
    {
        uart_rx_isr_push((uint8_t)USART3->RDR);
    }
}

#else /* UART_FRAME_HOST_TEST */

/* Host stand-in for uart_putc() - just enough for send_frame()/uart_write()
 * to link when this file is compiled standalone for RX-side testing. Real
 * hardware TX is not part of what's under test here. */
void uart_putc(uint8_t c)
{
    (void)c;
}

#endif /* UART_FRAME_HOST_TEST */

void uart_write(const uint8_t *data, uint16_t len)
{
    for (uint16_t i = 0; i < len; i++)
    {
        uart_putc(data[i]);
    }
}

uint16_t crc16_ccitt(const uint8_t *data, uint16_t len)
{
    uint16_t crc = 0xFFFFU;

    for (uint16_t i = 0; i < len; i++)
    {
        crc ^= (uint16_t)data[i] << 8;

        for (uint8_t bit = 0; bit < 8U; bit++)
        {
            if (crc & 0x8000U)
            {
                crc = (uint16_t)((crc << 1) ^ 0x1021U);
            }
            else
            {
                crc = (uint16_t)(crc << 1);
            }
        }
    }

    return crc;
}

/* header(6) + payload(<=FRAME_MAX_PAYLOAD): TYPE, VER, SEQ lo/hi, LEN lo/hi,
 * then payload - laid out contiguously so CRC can be taken over TYPE-through
 * -DATA in one call, and so header+payload go out in a single transmit. */
static void send_frame(frame_type_t type, const uint8_t *payload, uint16_t len)
{
    uint8_t body[6U + FRAME_MAX_PAYLOAD];

    body[0] = (uint8_t)type;
    body[1] = PROTOCOL_VERSION;
    body[2] = (uint8_t)(frame_seq & 0xFFU);
    body[3] = (uint8_t)(frame_seq >> 8);
    body[4] = (uint8_t)(len & 0xFFU);
    body[5] = (uint8_t)(len >> 8);

    for (uint16_t i = 0; i < len; i++)
    {
        body[6U + i] = payload[i];
    }

    uint16_t crc = crc16_ccitt(body, 6U + len);

    uint8_t sof[2]       = { FRAME_SOF0, FRAME_SOF1 };
    uint8_t crc_bytes[2] = { (uint8_t)(crc & 0xFFU), (uint8_t)(crc >> 8) };

    uart_write(sof, sizeof(sof));
    uart_write(body, 6U + len);
    uart_write(crc_bytes, sizeof(crc_bytes));

    frame_seq++;
}

void uart_frame_send_reply(frame_type_t type, const uint8_t *payload, uint16_t len)
{
    send_frame(type, payload, len);
}

/* Sent once immediately ahead of a capture's DATA frames, so the PC side
 * knows what rate the capture used and where sample 0 sits in time -
 * uart_frame_send() alone doesn't carry either. Payload, all little-endian:
 * rate (1 byte), sample_count (4 bytes), trigger_latency_ns (4 bytes). */
void uart_frame_send_config(void)
{
    uint8_t  rate               = rate_get();
    uint32_t sample_count       = DRAIN_SAMPLE_COUNT;
    uint32_t divider_n          = TRIGGER_DIVIDER_N[rate];
    uint32_t trigger_latency_ns = (divider_n + 2U) * 20U;

    uint8_t payload[9];
    payload[0] = rate;
    payload[1] = (uint8_t)(sample_count & 0xFFU);
    payload[2] = (uint8_t)((sample_count >> 8) & 0xFFU);
    payload[3] = (uint8_t)((sample_count >> 16) & 0xFFU);
    payload[4] = (uint8_t)((sample_count >> 24) & 0xFFU);
    payload[5] = (uint8_t)(trigger_latency_ns & 0xFFU);
    payload[6] = (uint8_t)((trigger_latency_ns >> 8) & 0xFFU);
    payload[7] = (uint8_t)((trigger_latency_ns >> 16) & 0xFFU);
    payload[8] = (uint8_t)((trigger_latency_ns >> 24) & 0xFFU);

    send_frame(FRAME_TYPE_CAPTURE_INFO, payload, sizeof(payload));
}

void uart_frame_send(void)
{
    const uint8_t *buffer = drain_loop_get_buffer();
    uint16_t offset = 0;

    while (offset < DRAIN_BUFFER_BYTES)
    {
        uint16_t remaining = DRAIN_BUFFER_BYTES - offset;
        uint16_t chunk = (remaining > FRAME_MAX_PAYLOAD) ? FRAME_MAX_PAYLOAD : remaining;

        send_frame(FRAME_TYPE_DATA, &buffer[offset], chunk);
        offset += chunk;
    }
}

/* ---------- RX frame assembler ----------
 * One byte per uart_frame_rx_feed() call, mirroring send_frame()'s body[]
 * layout (TYPE, VER, SEQ lo/hi, LEN lo/hi, then DATA) so the same
 * crc16_ccitt() call validates it. WAIT_SOF0/WAIT_SOF1 double as the
 * ASCII/binary arbitration described in the file header comment - a byte
 * that doesn't advance past them is exactly a byte this isn't a frame. */
typedef enum
{
    RXS_WAIT_SOF0 = 0,
    RXS_WAIT_SOF1,
    RXS_TYPE,
    RXS_VER,
    RXS_SEQ_LO,
    RXS_SEQ_HI,
    RXS_LEN_LO,
    RXS_LEN_HI,
    RXS_DATA,
    RXS_CRC_LO,
    RXS_CRC_HI,
} rx_frame_state_t;

static rx_frame_state_t rx_frame_state = RXS_WAIT_SOF0;
static uint8_t           rx_body[6U + FRAME_MAX_PAYLOAD];
static uint16_t          rx_body_len;
static uint16_t          rx_declared_len;
static uint16_t          rx_data_idx;
static uint16_t          rx_crc_recv;

frame_rx_result_t uart_frame_rx_feed(uint8_t byte, rx_frame_t *out)
{
    switch (rx_frame_state)
    {
    case RXS_WAIT_SOF0:
        if (byte == FRAME_SOF0)
        {
            rx_frame_state = RXS_WAIT_SOF1;
            return FRAME_RX_CONSUMED;
        }
        return FRAME_RX_NOT_FRAME;

    case RXS_WAIT_SOF1:
        if (byte == FRAME_SOF1)
        {
            rx_body_len     = 0;
            rx_frame_state  = RXS_TYPE;
            return FRAME_RX_CONSUMED;
        }
        /* False start: the buffered SOF0 is dropped (documented tradeoff -
         * see file header), this byte goes back to the caller unconsumed
         * as ordinary data. */
        rx_frame_state = RXS_WAIT_SOF0;
        return FRAME_RX_NOT_FRAME;

    case RXS_TYPE:
        rx_body[rx_body_len++] = byte;
        rx_frame_state = RXS_VER;
        return FRAME_RX_CONSUMED;

    case RXS_VER:
        rx_body[rx_body_len++] = byte;
        rx_frame_state = RXS_SEQ_LO;
        return FRAME_RX_CONSUMED;

    case RXS_SEQ_LO:
        rx_body[rx_body_len++] = byte;
        rx_frame_state = RXS_SEQ_HI;
        return FRAME_RX_CONSUMED;

    case RXS_SEQ_HI:
        rx_body[rx_body_len++] = byte;
        rx_frame_state = RXS_LEN_LO;
        return FRAME_RX_CONSUMED;

    case RXS_LEN_LO:
        rx_body[rx_body_len++] = byte;
        rx_declared_len = byte;
        rx_frame_state  = RXS_LEN_HI;
        return FRAME_RX_CONSUMED;

    case RXS_LEN_HI:
        rx_body[rx_body_len++] = byte;
        rx_declared_len |= (uint16_t)byte << 8;
        if (rx_declared_len > FRAME_MAX_PAYLOAD)
        {
            rx_frame_state = RXS_WAIT_SOF0;
            return FRAME_RX_OVERSIZE;
        }
        rx_data_idx     = 0;
        rx_frame_state  = (rx_declared_len == 0U) ? RXS_CRC_LO : RXS_DATA;
        return FRAME_RX_CONSUMED;

    case RXS_DATA:
        rx_body[rx_body_len++] = byte;
        rx_data_idx++;
        if (rx_data_idx >= rx_declared_len)
        {
            rx_frame_state = RXS_CRC_LO;
        }
        return FRAME_RX_CONSUMED;

    case RXS_CRC_LO:
        rx_crc_recv     = byte;
        rx_frame_state  = RXS_CRC_HI;
        return FRAME_RX_CONSUMED;

    case RXS_CRC_HI:
    default:
        rx_crc_recv |= (uint16_t)byte << 8;
        rx_frame_state = RXS_WAIT_SOF0;

        if (crc16_ccitt(rx_body, rx_body_len) != rx_crc_recv)
        {
            return FRAME_RX_BAD_CRC;
        }

        out->type    = (frame_type_t)rx_body[0];
        out->version = rx_body[1];
        out->seq     = (uint16_t)((uint16_t)rx_body[2] | ((uint16_t)rx_body[3] << 8));
        out->len     = rx_declared_len;
        out->payload = &rx_body[6];
        return FRAME_RX_COMPLETE;
    }
}
