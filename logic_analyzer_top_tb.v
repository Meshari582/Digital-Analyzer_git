`timescale 1 ns / 100 ps
module logic_analyzer_top_tb;
    reg        clk;
    reg        reset;
    reg        probe_in_raw;
    reg        polarity;
    reg        arm_raw;
    reg        rd_strobe_raw;
    reg  [1:0] rate;
    wire       data;
    wire       done;
    // Clock generation: same 20ns period pattern used every one of your
    // module testbenches so far — toggles every 10ns.
    always begin
        #10;
        clk <= ~clk;
    end
    // Reach into the hierarchy and shrink capture's MAX_SAMPLES down to 8
    // just for this simulation. The real board still uses 16384 — this
    // override only exists inside this testbench, it never touches
    // capture.v itself.
    defparam dut.capture_inst.MAX_SAMPLES = 8;
    // Instantiate the device under test
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
    initial begin
        // t=0: known starting state. reset held high so both sync chains
        // clear, and capture's state (which has no reset port of its own)
        // self-resolves out of X into IDLE via its default case branch.
        clk           <= 1'b0;
        reset         <= 1'b1;
        probe_in_raw  <= 1'b0;
        polarity      <= 1'b1;   // watch for a RISING edge on the probe
        arm_raw       <= 1'b0;
        rd_strobe_raw <= 1'b0;
        rate          <= 2'b01;  // fastest divider (N=5), keeps sim short
        #20;                     // one clock edge under reset is enough
        reset <= 1'b0;           // release reset
        #40;                     // idle a couple ticks, confirm everything sits at 0
        //Fire the probe trigger
        // probe_in_raw has to clear 2 sync stages (2 clock edges) plus one
        // more edge through trigger before probe_trigger actually pulses,
        // so we hold it well past that 3-edge (60ns) propagation delay.
        probe_in_raw <= 1'b1;
        #100;
        probe_in_raw <= 1'b0;    // trigger only needed the one rising edge
        //Let rate_div_0 (N=5) feed capture 8 samples
        // rate_div_0 free-runs the whole time regardless of capture's
        // state, pulsing sample_en every 5 ticks. Once capture is in
        // RUNNING it uses those pulses to fill the buffer (shrunk to 8
        // deep via the defparam above) and moves itself into FULL.
wait (done);              // block here until capture actually finishes, no more guessing
#20;                       // one clock margin so 'done' is stable before we act on it
        // by this point `done` should be high
        //Pulse arm_raw: send capture back to IDLE, readout's raddr to 0 
		  
        arm_raw <= 1'b1;
        #60;                     // hold past the sync+trigger propagation delay
        arm_raw <= 1'b0;
        #40;
        //Read all 8 samples back out, one rd_strobe pulse at a time
        repeat (8) begin
            rd_strobe_raw <= 1'b1;
            #60;                 // hold past sync+trigger so exactly one pulse lands
            rd_strobe_raw <= 1'b0;
            #40;                 // idle between strobes
        end
        #40;
        $stop;
    end
endmodule

