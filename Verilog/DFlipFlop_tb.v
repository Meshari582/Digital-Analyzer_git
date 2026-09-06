`timescale 1 ns / 100 ps

module DFlipFlop_tb;

    reg clk;
    reg reset;
    reg d;
    wire q;

    // Clock generation: toggles every 10 ns -> 20 ns period
    always begin
        #10;
        clk <= ~clk;
    end
	 /* every 10 ns, clk flips. Since it takes two flips to get back to where it started (0→1→0), 
		  that gives you a clock with a 20 ns period — i.e., it goes high for 10 ns, low for 10 ns, repeating.
        */

    // Test stimulus
    initial begin //Only runs once in order
        // Initial state
        clk   <= 1'b0;
        reset <= 1'b1;   // Hold reset high first
        d     <= 1'b0;
		  /*
1'b0
│ │ │
│ │ └── the actual value (0) in binary
│ └──── the base: b = binary (also d=decimal, h=hex, o=octal)
└────── the width: how many bits this value occupies

*/
        #20               // Wait one clock edge so reset actually takes effect
        reset <= 1'b0;    // Release reset
        d     <= 1'b1;

        #20
        d <= 1'b0; //Both reset and Data is 0

        #20
        d <= 1'b1; //Data=1, Reset=0

        #20
        reset <= 1'b1;    // Data= 1, Reset=1
        d     <= 1'b1;

        #20
        reset <= 1'b0; // Data=1, Reset =0

        #20   
        $stop;
    end

    // Instantiate the device under test
    DFlipFlop dut (  //the name of the module
        .clk(clk), 
        .reset(reset),
        .d(d),
        .q(q)
		  //.port_name_inside_module(signal_name_in_testbench)
    );

endmodule