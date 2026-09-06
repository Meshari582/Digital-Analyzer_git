`timescale 1 ns / 100 ps

module sync_tb;

    reg clk;     // System clock — both flip-flops update on its rising edge
    reg reset;    // Synchronous reset — forces the whole chain to 0
    reg d;        // Raw, potentially unstable async input signal
    wire q;         // Final synced output — safe to use elsewhere in the design



    // Clock generation: toggles every 10 ns -> 20 ns period
    always begin
        #10;
        clk <= ~clk;
    end
	 /* every 10 ns, clk flips. Since it takes two flips to get back to where it started (0→1→0), 
		  that gives you a clock with a 20 ns period — i.e., it goes high for 10 ns, low for 10 ns, repeating.
        */

    // Test stimulus
 
initial begin //initial just runs through once and stops.
    // Start in reset, at time=0
    clk   <= 1'b0;
    reset <= 1'b1;
    d     <= 1'b0;
    #20;                  // let reset take effect after 20ns

    reset <= 1'b0;         // release reset
    #40;                   // idle a bit with d=0, confirm q stays 0, at time=60ns
	                        // checking that q correctly settles to and stays at 0, with nothing else going on.

    d <= 1'b1;              // change d — now watch it take 2 clock edges to reach q
    #100;                   // give it several cycles to settle and show the delay clearly

    d <= 1'b0;               // change d back, watch the delay again
    #100;

    reset <= 1'b1;            // test reset while d is toggling
    #20;

    reset <= 1'b0;
    #40;

    $stop;
end

    // Instantiate the device under test
       sync dut (  //the name of the module
       .clk(clk),
       .reset(reset),
       .d(d),
       .q(q)
        
		  //.port_name_inside_module(signal_name_in_testbench)
    );

endmodule