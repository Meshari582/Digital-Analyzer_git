`timescale 1 ns / 100 ps
module trigger_tb;
   reg  clk;
   reg  probe_in;
   reg  polarity;
	reg reset;
   wire output_trigger;

    // Clock generation: toggles every 10 ns -> 20 ns period
    always begin
        #10;
        clk <= ~clk;
    end
    // every 10 ns, clk flips. Since it takes two flips to get back to where
    // it started (0->1->0), that gives you a clock with a 20 ns period —
    // i.e., it goes high for 10 ns, low for 10 ns, repeating.

    // Test stimulus
    initial begin // initial just runs through once and stops.

        // t=0: start everything at a known state. polarity=1 means we're
        // initially configured to watch for RISING edges only.
        clk      <= 1'b0;
        probe_in <= 1'b0;
        polarity <= 1'b1;
        reset    <= 1'b1;
        #20;                     // wait 20ns (one full clock period) with probe_in low,
                                  // so the DUT settles into a known starting state
        reset    <=1'b0;                          // (prev_sample = 0) before we give it anything to detect.

        // --- TEST 1: matching-polarity rising edge ---
        probe_in <= 1'b1;        // t=20: raise probe_in — a rising edge, and polarity=1
        polarity <= 1'b1;        // says "watch for rising," so this SHOULD trigger.
                                  // Because of how non-blocking assigns schedule, the DUT
                                  // won't actually see probe_in=1 until the next posedge,
                                  // which lands at t=30. Expect a one-cycle pulse there.

        #40;                     // hold probe_in high for 40ns (two clock cycles) —
        polarity <= 1'b1;        // long enough to see the trigger pulse fire once at
                                  // t=30 and confirm it drops back to 0 on the very next
                                  // tick (t=50), proving it's a one-cycle-wide pulse and
                                  // not a level signal.

        #100;                    // keep idling with probe_in still high — nothing new
                                  // should happen here, output_trigger should stay low
                                  // the whole time since there's no new edge.

        // --- TEST 2: matching-polarity falling edge ---
        probe_in <= 1'b0;        // t=160: drop probe_in — a falling edge, and we're about
        polarity <= 1'b0;        // to set polarity=0 ("watch for falling"), so this
                                  // SHOULD trigger too. Expect a one-cycle pulse at t=170.

        #100;                    // idle with probe_in low and polarity still 0, confirming
                                  // output_trigger drops back to 0 and stays there with
                                  // nothing else going on.

        // --- TEST 3: mismatched-polarity edge (the "ignore" case) ---
        probe_in <= 1'b1;        // t=260: raise probe_in — this IS a rising edge, but
        polarity <= 1'b0;        // polarity is still 0 ("watch for falling only"), so
                                  // this should NOT trigger. This is the important negative
                                  // test: it catches bugs like a swapped if/else in the DUT,
                                  // where the "wrong" edge might slip through and fire
                                  // anyway. Expect output_trigger to stay flat here.

        #150;                    // run a bit longer after the mismatched edge to confirm
                                  // output_trigger really does stay low the whole time —
                                  // no delayed or spurious pulse.

        $stop;                   // end simulation
    end

    // Instantiate the device under test
    trigger dut (
        .clk(clk),
        .probe_in(probe_in),
        .polarity(polarity),
		  .reset(reset),
        .output_trigger(output_trigger)
    );

endmodule