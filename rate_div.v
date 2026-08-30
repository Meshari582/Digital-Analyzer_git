module rate_div (
    input  clk,
    input  reset,
    output reg sample_en   // pulses high for 1 cycle every N clock ticks
);
    parameter N = 5;   // divide-by value — change this number to change the sample rate
	 
	  wire [12:0] count;
	  wire counter_reset;

	  // Combinational compare — was a registered "hit_max" flop before, which delayed
	  // the reset trigger by one clock edge and made count sit at N-1 for two cycles
	  // instead of one (that was the source of the extra 20ns per period).
	  wire hit_max = (count == N-1);
//is count equal to N-1 right now? If yes, hit_max is 1. If no, hit_max is 0.


	   assign counter_reset = reset || hit_max; //the module's own external reset input.
	                                                  //If a person/system asserts this, it's true (1).
													  
     // continuously drive this wire's value based  on whatever's on the right-hand side,
	  //updating instantly anytime the right side changes
	  
	  //(count == N-1) — true (1) exactly when the counter has counted all the way up and hit its target value.
	  
	  counter counter1 (
        .clk(clk),
        .reset(counter_reset),
        .counter(count)
		 );
		 
always @(posedge clk) begin
	 
	   if (reset) begin 
	sample_en <= 0;
end else 	
	sample_en <= hit_max;
   
 end
	 endmodule