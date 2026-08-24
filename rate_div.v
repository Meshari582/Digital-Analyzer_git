module rate_div (
    input  clk,
    input  reset,
    output reg sample_en   // pulses high for 1 cycle every N clock ticks
);
    parameter N = 5;   // divide-by value — change this number to change the sample rate
	 
	  wire [12:0] count;
	  wire counter_reset;

	  // hit_max is a registered (synchronous) version of "count == N-1".
	  // This delays the reset trigger by one clock edge, so count actually
	  // holds at N-1 for a full cycle instead of self-resetting the instant
	  // it gets there (which was racing ahead of sample_en's own check).
	  reg hit_max; //instead of adding up to 8191, it counts up to N-1
	  always @(posedge clk or posedge reset) begin
	      if (reset)
	          hit_max <= 0;
	      else
	          hit_max <= (count == N-1);
	  end
//was count equal to N-1 just now? If yes, hit_max becomes 1. If no, hit_max becomes 0.


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
		 
always @(posedge clk or posedge reset) begin
	 
	   if (reset) begin 
	sample_en <= 0;
end else 	
	sample_en <= hit_max;
   
 end
	 endmodule