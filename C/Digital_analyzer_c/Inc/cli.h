#ifndef CLI_H
#define CLI_H

/* One-time setup: defensively re-arms the FPGA (clears any stale FULL
 * state left by the selftest wrapper before the MCU came up) and puts
 * the CLI into its idle prompt state. Mirrors the boot-time arm_pulse()
 * that used to live directly in main.c. */
void cli_init(void);

/* Runs the command prompt forever. Never returns - this replaces the
 * old auto-repeat for(;;) loop in main.c. The auto-repeat behavior
 * still exists, but now it's one command ("repeat") instead of the
 * only thing the firmware does. Marked noreturn instead of adding dead
 * code after its call site, since it genuinely never returns. */
__attribute__((noreturn)) void cli_run(void);

#endif /* CLI_H */
