`timescale 1 ns / 100 ps
 module buffer_tb;

    reg clk;
    reg  we;
    reg  [13:0] waddr;
    reg  wdata;
    reg  [13:0] raddr;
    wire rdata;
    // Clock generation: same 20ns period pattern you've used in every testbench so far.
    always begin
        #10;
        clk <= ~clk;
    end

initial begin
    // start everything at a known state
    clk   <= 1'b0;
    we    <= 1'b0;
    waddr <= 14'd0;
    wdata <= 1'b0;
    raddr <= 14'd5;
	 
    #20;

    // write a 1 onto page 5
    we    <= 1'b1;
    waddr <= 14'd5;
    wdata <= 1'b1;
    #20;
    we <= 1'b0;   // done writing

    #20;   // idle a tick, nothing should happen

    // now point the read side at page 5, and WATCH rdata carefully —
    // it should NOT show 1 immediately. It should still show whatever
    // it was before, for exactly one more tick.
    raddr <= 14'd5;
    #20;   // one tick after setting raddr — rdata should NOW show 1

    $stop;
end
	  // Instantiate the DUT
    buffer dut (
        .clk(clk),
        .we(we),
        .waddr(waddr),
        .wdata(wdata),
        .raddr(raddr),
		  .rdata(rdata)
    );

endmodule