`include "logic_analyzer_params.vh"

module logic_analyzer_top (
    //Board-side inputs
    input  clk,              // 50 MHz onboard clock — the single clock domain for the whole design
    input  reset,             // synchronous reset (from a KEY or a switch on the DE-10 Lite)
    input  probe_in_raw,       // the probe wire — arrives from the outside world with no
                                // relationship to our clock, so it must be synced before use
    input  polarity,            // board switch: 1 = trigger on rising edge, 0 = falling edge

    //From the MCU (STM32) 
    input  arm_raw,           // pulse to start a capture and clear the last one
    input  rd_strobe_raw,      // pulse to move to the next sample
    input  [1:0] rate,          // sample-rate select — picks which rate_div drives sample_en

    //To the MCU (STM32)
    output data,             // the sample bit at the current read address
    output done              // capture finished — MCU wires this to an interrupt input
);

    // STAGE 1 — Synchronizers
    // probe_in_raw, arm_raw, and rd_strobe_raw are all async: nothing
    // guarantees they change safely relative to our clock edge. Each
    // one gets its own two-flop sync module before it's allowed to
    // touch anything else in the design.
	 //2 clock cycle delays
    //
    // polarity and rate[1:0] are also board-level inputs (DIP switches,
    // doc 683447 Table 12) with no timing relationship to clk, so they get
    // the same two-flop treatment. Each bit of rate is synced independently
    // with its own sync instance -- fine here because rate only comes from
    // a hand-operated switch, changes are rare, and any single-cycle
    // transient mux mismatch during a switch change is harmless (rate is
    // only consulted while div_run is active, long after power-up settling).

    wire probe_sync;
    wire arm_sync;
    wire rd_strobe_sync;
    wire polarity_sync;
    wire [1:0] rate_sync;

    sync sync_probe (
        .clk(clk),
        .reset(reset),
        .d(probe_in_raw),
        .q(probe_sync)
    );

    sync sync_arm (
        .clk(clk),
        .reset(reset),
        .d(arm_raw),
        .q(arm_sync)
    );

    sync sync_rd_strobe (
        .clk(clk),
        .reset(reset),
        .d(rd_strobe_raw),
        .q(rd_strobe_sync)
    );

    sync sync_polarity (
        .clk(clk),
        .reset(reset),
        .d(polarity),
        .q(polarity_sync)
    );

    sync sync_rate0 (
        .clk(clk),
        .reset(reset),
        .d(rate[0]),
        .q(rate_sync[0])
    );

    sync sync_rate1 (
        .clk(clk),
        .reset(reset),
        .d(rate[1]),
        .q(rate_sync[1])
    );

    // STAGE 2 — Trigger x3
    // trigger's actual job is edge-detection: watch a signal, fire
    // one clock tick when it sees the edge you asked for. That's
    // exactly what we need in two different places:
    //
    //  (a) the REAL probe trigger — starts a capture when the probe
    //      does whatever polarity says to watch for.
    //
    //  (b) arm_sync and rd_strobe_sync are MCU-driven pulses. The
    //      STM32 runs far slower than our 50 MHz clock, so a single
    //      MCU "pulse" sits HIGH for hundreds of our clock ticks —
    //      not one. If we fed arm_sync straight into capture as a
    //      level, capture would see "arm" asserted for hundreds of
    //      cycles and re-arm hundreds of times instead of once.
    //      trigger already converts "level held high" into "one-tick
    //      pulse on the rising edge," so we reuse it here as a pulse
    //      shaper — polarity hardwired to 1 (rising edge) since we
    //      only care about the pulse starting, not the level itself.
    //1 clock cycle delay
    wire probe_trigger;   // one-tick pulse: the real capture-start trigger
    wire arm_pulse;       // one-tick pulse: MCU's arm request, shaped down from a long level
    wire rd_strobe_pulse; // one-tick pulse: MCU's read-strobe request, shaped down the same way

    trigger trigger_probe (
        .clk(clk),
        .probe_in(probe_sync),
		  .reset(reset),
        .polarity(polarity_sync), // board switch decides rising vs falling edge (synced)
        .output_trigger(probe_trigger)
    );

    trigger trigger_arm (
        .clk(clk),
        .probe_in(arm_sync),
		  .reset(reset),
        .polarity(1'b1),          // always rising-edge: fire once when arm_sync goes high
        .output_trigger(arm_pulse)
    );

    trigger trigger_rd_strobe (
        .clk(clk),
        .probe_in(rd_strobe_sync),
		   .reset(reset),
        .polarity(1'b1),          // always rising-edge: fire once when rd_strobe_sync goes high
        .output_trigger(rd_strobe_pulse)
    );

    // STAGE 3 — Rate select: four rate_div instances, muxed
    // rate_div's divide value N is a parameter, meaning it's baked in
    // at compile time — a wire can't reach in and change it while the
    // design is running. But the MCU needs to pick the sample rate at
    // RUNTIME via the `rate` input. So instead of one rate_div with a
    // variable N, we build four rate_div copies, each with a different
    // fixed N, and use a case statement to pick which one's sample_en
    // output actually gets used, based on rate[1:0].
     //1 clock cycle delay
    wire sample_en_0, sample_en_1, sample_en_2, sample_en_3; // one output per divider
    reg  sample_en;                                          // the one we actually forward

    // The dividers used to free-run from power-on, completely unaware of
    // whether a capture was happening. That meant the probe edge landed at a
    // random point in the divider's cycle, so the gap between the trigger
    // firing and sample 0 being written varied from 1 to N clocks, differently
    // on every single capture. The PC tool assumes sample n happened exactly
    // n * period after the trigger, so that gap was going straight into the
    // time axis as error.
    //
    // div_run holds all four dividers in reset until the trigger fires, then
    // releases them together. Now every capture starts the divider from the
    // same phase, so sample 0 always lands a FIXED N+1 clocks after the
    // trigger instead of a random 1..N. Same constant every time, so the PC
    // can simply subtract it.
    reg div_run;
    always @(posedge clk) begin
        if (reset)
            div_run <= 0;
        else if (probe_trigger)
            div_run <= 1;      // capture starting - let the dividers go
        else if (arm_pulse)
            div_run <= 0;      // capture finished and re-armed - park them again
    end

    wire div_reset = reset || ~div_run;

    rate_div #(.N(`RATE_DIV_0)) rate_div_0 (.clk(clk), .reset(div_reset), .sample_en(sample_en_0));
    rate_div #(.N(`RATE_DIV_1)) rate_div_1 (.clk(clk), .reset(div_reset), .sample_en(sample_en_1));
    rate_div #(.N(`RATE_DIV_2)) rate_div_2 (.clk(clk), .reset(div_reset), .sample_en(sample_en_2));
    rate_div #(.N(`RATE_DIV_3)) rate_div_3 (.clk(clk), .reset(div_reset), .sample_en(sample_en_3));

    always @(*) begin       // combinational mux — just picking a wire, no clocking needed here
        case (rate_sync)
            2'b00: sample_en = sample_en_0;
            2'b01: sample_en = sample_en_1;
            2'b10: sample_en = sample_en_2;
            2'b11: sample_en = sample_en_3;
            default: sample_en = sample_en_0;
        endcase
    end

    // STAGE 4 — capture -> buffer -> readout
    
    wire        we;              // buffer's write enable
    wire [`ADDR_WIDTH-1:0] sample_counter;  // capture's running count -> buffer's write address
    wire [`ADDR_WIDTH-1:0] raddr;           // readout's read pointer -> buffer's read address
    wire        rdata;           // buffer's read output -> readout's data input

    // capture also needs to clear readout's read pointer back to page 0
    // whenever a new capture starts, or the second capture would start
    // reading from wherever the first one left off. reset OR a fresh
    // arm pulse both send raddr back to 0.
    wire readout_reset = reset || arm_pulse; //reset is on OR arm_pulse is on 

    capture capture_inst (
        .clk(clk),
        .output_trigger(probe_trigger),  // real probe edge starts the capture
		  .reset(reset),
        .sample_en(sample_en),           // muxed tick from stage 3 paces the sampling
        .arm(arm_pulse),                 // MCU's arm pulse kicks FULL back to IDLE
        .done(done),                     // straight out to the MCU
        .sample_counter(sample_counter), // becomes buffer's write address
        .we(we)                          // becomes buffer's write enable
    );

    buffer buffer_inst (
        .clk(clk),
        .we(we),                  // only write when capture says so
        .waddr(sample_counter),   // write to the page capture is currently on
        .wdata(probe_sync),       // the actual bit being recorded is the synced probe value
        .raddr(raddr),            // read side driven by readout's pointer
        .rdata(rdata)             // read result goes back to readout
    );

    readout readout_inst (
        .clk(clk),
        .reset(readout_reset),      // reset OR fresh arm -> raddr back to page 0
        .rd_strobe(rd_strobe_pulse),// MCU's shaped read-strobe pulse
        .rdata(rdata),               // bit coming back from buffer
        .raddr(raddr),                // drives buffer's read address
        .data_out(data)                // straight out to the MCU
    );

endmodule