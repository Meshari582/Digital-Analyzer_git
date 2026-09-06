`timescale 1 ns / 100 ps
module readout_tb;
    reg clk;
    reg reset;
    reg rd_strobe;            
    reg rdata;           
    wire [13:0] raddr;   
    wire data_out;       
    // Clock generation: toggles every 10 ns -> 20 ns period
    always begin
        #10;
        clk <= ~clk;
    end
	 /* every 10 ns, clk flips. Since it takes two flips to get back to where it started (0→1→0), 
		  that gives you a clock with a 20 ns period — i.e., it goes high for 10 ns, low for 10 ns, repeating.
        */
    // Test stimulus
      initial begin
        // Known starting state
        clk       <= 1'b0;
        reset     <= 1'b1;   // hold reset high so raddr starts known, at page 0
        rd_strobe <= 1'b0;
        rdata     <= 1'b0;
        #20;   // let things settle
        reset <= 1'b0;   // release reset — raddr should now read 0, not X
        // Simulate buffer already showing page 0's bit = 1
        rdata <= 1'b1;
        #20;   // give it a tick to settle before we pulse
        // --- First strobe: MCU asks for the current bit ---
        rd_strobe <= 1'b1;
        #20;               // one tick — raddr moves and pending is set; data_out doesn't grab rdata until next tick
        rd_strobe <= 1'b0;
        #20;              // idle a tick, confirm nothing changes without a strobe
        // Simulate buffer now showing page 1's bit = 0
        rdata <= 1'b0;
        #20;   // let it settle, matching buffer's one-tick read delay
        // --- Second strobe: MCU asks for the next bit ---
        rd_strobe <= 1'b1;
        #20;
        rd_strobe <= 1'b0;
        #40;   // idle, confirm it holds steady with no more strobes
        $stop;
    end
    // Instantiate the device under test
        readout dut (  //the name of the module
        .clk(clk), 
        .reset(reset),
        .rd_strobe(rd_strobe),
        .rdata(rdata),
        .raddr(raddr),
		  .data_out(data_out)
		  //.port_name_inside_module(signal_name_in_testbench)
    );
endmodule