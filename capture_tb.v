`timescale 1 ns / 100 ps
module capture_tb;

    reg  clk;
    reg  output_trigger;
    reg  sample_en;
    reg  arm;
	 reg reset;
    wire done;
    wire we;
    wire [13:0] sample_counter;
    // Clock generation: same 20ns period pattern you've used in every testbench so far.
    always begin
        #10;
        clk <= ~clk;
    end

   
    initial begin
        // t=0: start everything low/idle. capture should sit in IDLE here.
        clk            <= 1'b0;
        output_trigger <= 1'b0;
        sample_en      <= 1'b0;
        arm            <= 1'b0;
		  reset          <= 1'b1;

        #20; // let it settle in IDLE for a bit before anything happens
		  reset           <=1'b0;

        // --- Fire the trigger to leave IDLE and go to RUNNING ---
        output_trigger <= 1'b1;
        #20;
        output_trigger <= 1'b0;  // trigger is a pulse, not a held level — drop it back down
        // capture should now be in RUNNING (as of the next posedge after this)

        // --- Feed it 8 sample_en pulses, one per clock tick, to fill the buffer ---
        // Since MAX_SAMPLES=8, the 8th pulse should push it into FULL.
        repeat (8) begin
            sample_en <= 1'b1;
            #20;
            sample_en <= 1'b0;
            #20;
        end
        // By now, done should be high and state should be FULL.
        #20;

        // --- Pulse arm to send it back to IDLE ---
        arm <= 1'b1;
        #20;
        arm <= 1'b0;

        #40; // idle a bit, confirm it settled back in IDLE with done cleared

        $stop;
    end
	  // Instantiate the DUT, but override MAX_SAMPLES down to 8 just for this test.
    // The real module defaults to 16384 — way too many cycles to simulate practically.
    // This #(...) syntax overrides the parameter only for this instance, without
    // touching the value anywhere else that uses capture normally.
    capture #(.MAX_SAMPLES(8)) dut (
        .clk(clk),
        .output_trigger(output_trigger),
        .sample_en(sample_en),
		  .reset(reset),
        .arm(arm),
        .done(done),
		  .we(we),
        .sample_counter(sample_counter)
    );
/*
clk — the simulation clock, toggling every 10ns (20ns period), same as every testbench you've built — this is the heartbeat that all your synchronous logic reacts to on each posedge.
output_trigger — the input you're using to simulate the pulse that would normally come from trigger.v; in the waveform it goes high once early on, briefly, to kick capture out of IDLE and into RUNNING.
sample_en — the input simulating the periodic pulse from rate_div, driven by your repeat (8) loop; the waveform shows it toggling high/low repeatedly, each pulse advancing sample_counter by one during RUNNING.
arm — the input simulating the MCU telling capture to reset and start over; it goes high once near the end of the simulation, which should kick state from FULL back to IDLE.
done — the output flag capture raises once sample_counter reaches MAX_SAMPLES-1 (8, since you overrode it); the waveform shows it going high partway through and then dropping back to low once arm pulses.
*/
endmodule