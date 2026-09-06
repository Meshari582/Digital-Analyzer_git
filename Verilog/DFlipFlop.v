module DFlipFlop (
    input  clk,      // Clock input — the flip-flop only reacts at the instant
                      // this rises from 0 to 1 (see posedge below)
    input  reset,     // Control input — forces q back to 0 when high,
                       // regardless of what d is doing
    input  d,          // Data input — whatever value is here at the clock
                        // edge gets captured into q
    output reg q         // The stored output — holds its value between
                          // clock edges, only updates AT a rising edge
								  
								  //reg is only needed when a signal is assigned inside an always block
);

    always @(posedge clk) begin   // This block runs exactly once per clock
                                    // rising edge — nothing happens in between
        if (reset)                  // Checked only at the clock edge, not
                                     // continuously — parentheses required
            q <= 0;                  // Reset takes priority: force q to 0
        else 
            q <= d;                   // Otherwise, capture d into q.
                                      // <= (non-blocking) is the convention
                                      // inside clocked always blocks
    end

endmodule