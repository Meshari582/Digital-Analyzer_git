#ifndef UART_FRAME_H
#define UART_FRAME_H

#include <stdint.h>

/* Wire protocol, PROTOCOL_VERSION 2. See the comment block at the top of
 * uart_frame.c for the full direction-scheme writeup (why CONFIG and
 * CAPTURE_INFO are separate type codes instead of one direction-dependent
 * code, and how ASCII CLI text coexists with binary frames on one UART).
 * This table is the part the PC-side tool has to mirror exactly. */
#define PROTOCOL_VERSION 2U

typedef enum
{
    FRAME_TYPE_CONFIG       = 0,  /* PC -> MCU: [rate:1][polarity_request:1]. rate is 0-3; polarity_request
                                    * 0xFF means "leave it alone" (the only legal value today - polarity is
                                    * a board switch, MCU replies ERROR for anything else). */
    FRAME_TYPE_ARM          = 1,  /* PC -> MCU: empty payload. */
    FRAME_TYPE_ABORT        = 2,  /* PC -> MCU: empty payload. MCU always replies ERROR - no HW abort exists. */
    FRAME_TYPE_STATUS       = 3,  /* PC -> MCU: empty payload (request). MCU -> PC: 1 byte, capture_state_t
                                    * (0=IDLE, 1=ARMED, 2=CAPTURED) (reply). Same code both ways - request and
                                    * reply are distinguishable by direction alone, no collision to resolve. */
    FRAME_TYPE_DATA         = 4,  /* MCU -> PC: one chunk of the sample buffer (up to 256 bytes/frame). */
    FRAME_TYPE_ACK          = 5,  /* MCU -> PC: empty payload. */
    FRAME_TYPE_NAK          = 6,  /* MCU -> PC: empty payload. Malformed/rejected request, bad CRC, or
                                    * "nothing to re-read" - not an ERROR because nothing on the MCU broke. */
    FRAME_TYPE_ERROR        = 7,  /* MCU -> PC: payload is a short ASCII reason string (not NUL-terminated;
                                    * length is the frame LEN field). */
    FRAME_TYPE_CAPTURE_INFO = 8,  /* MCU -> PC: [rate:1][sample_count:4][trigger_latency_ns:4], all
                                    * little-endian, sent immediately ahead of a capture's DATA frames. */
    FRAME_TYPE_REREAD       = 9,  /* PC -> MCU: empty payload. Re-drains and re-sends the last captured
                                    * buffer (CAPTURE_INFO + DATA frames) WITHOUT calling arm_pulse() - the
                                    * FPGA's read address wraps exactly back to 0 after 16384 more strobes
                                    * (14-bit raddr, 16384-deep buffer), so this replays the same capture.
                                    * NAKs if no capture has been drained since the last arm. */
} frame_type_t;

typedef struct
{
    frame_type_t   type;
    uint8_t        version;
    uint16_t       seq;
    uint16_t       len;
    const uint8_t *payload;   /* Points into uart_frame.c's internal RX assembly buffer - valid only until
                                * the next uart_frame_rx_feed() call. Copy out anything you need to keep. */
} rx_frame_t;

typedef enum
{
    FRAME_RX_CONSUMED = 0,  /* Byte absorbed into an in-progress (or now-complete) frame. */
    FRAME_RX_NOT_FRAME,     /* Byte is not part of a frame - caller should treat it as plain data (e.g. an
                              * ASCII CLI character). */
    FRAME_RX_COMPLETE,      /* *out is a validated, CRC-good frame. */
    FRAME_RX_BAD_CRC,       /* Frame fully received but CRC mismatch. Already resynced to WAIT_SOF0. */
    FRAME_RX_OVERSIZE,      /* Declared LEN exceeded the max payload. Already resynced to WAIT_SOF0. */
} frame_rx_result_t;

void uart_frame_init(void);
void uart_frame_send_config(void);
void uart_frame_send(void);
void uart_frame_send_reply(frame_type_t type, const uint8_t *payload, uint16_t len);

/* Feeds one received byte into the RX frame assembler. Call for every byte
 * pulled off uart_getc(), before treating it as anything else - see
 * uart_frame.c's top-of-file comment for the SOF-based arbitration this
 * implements. Non-blocking: never waits for more bytes than are already
 * available, and can back out of a false-start SOF match. */
frame_rx_result_t uart_frame_rx_feed(uint8_t byte, rx_frame_t *out);

uint16_t crc16_ccitt(const uint8_t *data, uint16_t len);

uint8_t  uart_rx_ready(void);
uint8_t  uart_getc(void);
void     uart_putc(uint8_t c);
void     uart_write(const uint8_t *data, uint16_t len);

/* Count of bytes dropped by the RXNE ISR because the RX ring buffer was
 * full (never advances tail from the ISR - see uart_frame.c). Should stay
 * 0 under normal PC command traffic; feeds the error-rate reporting. */
uint32_t uart_rx_overflow_count(void);

#endif /* UART_FRAME_H */
