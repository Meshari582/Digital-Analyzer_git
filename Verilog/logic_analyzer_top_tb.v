`timescale 1 ns / 100 ps
module logic_analyzer_top_tb;

    // how many samples this simulation captures ----
    // The real board captures 16384. Shrinking it to 16 keeps the sim short
    // while still being long enough to show four full runs of the probe
    // pattern, so an off-by-one in the address or the strobe cannot hide.
    localparam DEPTH = 16;

    reg        clk;
    reg        reset;
    reg        probe_in_raw;
    reg        polarity;
    reg        arm_raw;
    reg        rd_strobe_raw;
    reg  [1:0] rate;
    wire       data;
    wire       done;

    // Golden reference: what the DUT actually wrote, in write order.
    // Filled by watching the write port, checked against the read port later.
    reg  expected [0:DEPTH-1];
    reg  got      [0:DEPTH-1];
    integer samples_written;
    integer errors;
    integer i;

    // Clock: 20ns period, same as every other testbench in this project.
    always begin
        #10;
        clk <= ~clk;
    end

    defparam dut.capture_inst.MAX_SAMPLES = DEPTH;

    logic_analyzer_top dut (
        .clk(clk),
        .reset(reset),
        .probe_in_raw(probe_in_raw),
        .polarity(polarity),
        .arm_raw(arm_raw),
        .rd_strobe_raw(rd_strobe_raw),
        .rate(rate),
        .data(data),
        .done(done)
    );

    // Zero the buffer at power-up. This lives here and not in buffer.v because
    // Quartus tries to statically unroll a 16384-iteration loop during synthesis
    // and gives up at 5000. On real hardware the M9K contents come from the
    // configuration bitstream, so the RTL never needed this -- it is purely so
    // the waveform does not show X on data for addresses nothing has written yet.
    integer init_i;
    initial begin
        for (init_i = 0; init_i < 16384; init_i = init_i + 1)
            dut.buffer_inst.mem[init_i] = 1'b0;
    end

    // Watch the buffer's write port. Every time capture asserts we, record
    // which address was written and what bit went in. This is the reference
    // the readback gets compared against.
    always @(posedge clk) begin
        if (dut.we) begin
            expected[dut.sample_counter] = dut.probe_sync;
            samples_written = samples_written + 1;
        end
    end

    initial begin
        clk           <= 1'b0;
        reset         <= 1'b1;
        probe_in_raw  <= 1'b0;
        polarity      <= 1'b1;   // trigger on a RISING edge
        arm_raw       <= 1'b0;
        rd_strobe_raw <= 1'b0;

        // rate 2'b00 selects rate_div_0, which is the N=5 divider: one
        // sample every 100ns. 2'b01 would select N=50 (one sample every
        // 1000ns), which is far slower than the probe pattern below and
        // would make every captured sample read back as the same value.
        rate          <= 2'b00;

        samples_written = 0;
        errors   = 0;

        #35;                     // hold reset across two clock edges
        reset <= 1'b0;
        #45;

        // Probe pattern: rising edge fires the trigger, then the probe
        // toggles every 200ns. At one sample per 100ns that is two samples
        // per level, so the captured data should come back as runs of two.
        probe_in_raw <= 1'b1;
        forever begin
            #200 probe_in_raw <= ~probe_in_raw;
        end
    end

    initial begin
        wait (done);
        #20;

        if (samples_written !== DEPTH) begin
            $display("FAIL: capture wrote %0d samples, expected %0d", samples_written, DEPTH);
            errors = errors + 1;
        end

        // Read cycle, exactly as the MCU will do it: READ FIRST, ADVANCE
        // SECOND. Sample the data pin, then pulse rd_strobe to move on.
        for (i = 0; i < DEPTH; i = i + 1) begin
            got[i] = data;
            if (data !== expected[i]) begin
                $display("FAIL: sample %0d read back %b, expected %b (raddr was %0d)",
                         i, data, expected[i], dut.readout_inst.raddr);
                errors = errors + 1;
            end
            if (dut.readout_inst.raddr !== i) begin
                $display("FAIL: on read %0d the read pointer was at %0d",
                         i, dut.readout_inst.raddr);
                errors = errors + 1;
            end
            rd_strobe_raw <= 1'b1;
            #60;                 // hold past the 2 sync flops + 1 trigger flop
            rd_strobe_raw <= 1'b0;
            // Settle time before the next read. The full path from the strobe
            // edge to a valid data pin is: 2 sync flops + 1 trigger flop +
            // raddr update + buffer read + data_out register = 6 clock edges,
            // or 120ns at 50MHz. 200ns here leaves margin. On the MCU this is
            // free -- a loop iteration is microseconds, which is exactly what
            // "read first, advance second" in the brief is buying.
            #200;
        end

        // Re-arm: sends capture back to IDLE and readout's raddr back to 0.
        // This has to happen AFTER the drain, not before it -- arming restarts
        // the capture, and a running capture overwrites the buffer underneath
        // a readback that is still in progress.
        arm_raw <= 1'b1;
        #60;
        arm_raw <= 1'b0;
        #40;

        $write("written : ");
        for (i = 0; i < DEPTH; i = i + 1) $write("%b", expected[i]);
        $write("\nread    : ");
        for (i = 0; i < DEPTH; i = i + 1) $write("%b", got[i]);
        $display("");

        if (errors == 0)
            $display("PASS - %0d samples captured and read back in order, starting at address 0", DEPTH);
        else
            $display("FAIL - %0d error(s)", errors);

        #40;
        $stop;
    end

    // Safety net so the simulation cannot hang if done never arrives.
    initial begin
        #200000;
        $display("FAIL - timeout, done never asserted");
        $stop;
    end

endmodule