module capture (
    input  clk,
    input  output_trigger,
    input  sample_en,     // from rate_div — only sample when this is high
    input  arm,   	 // from MCU — kicks FULL back to IDLE for next capture
	 input reset,
    output reg done, //
    output reg [13:0] sample_counter,
    output we
);
    parameter IDLE    = 2'b00;
    parameter RUNNING = 2'b01;
    parameter FULL    = 2'b10;
    parameter MAX_SAMPLES = 16384;
    reg [1:0]  state;

    // we is now combinational, tied straight to sample_en, so it lands on
    // the SAME edge as sample_counter's pre-increment value — the address
    // the sample was actually taken at, not the one it's about to become.
    assign we = (state == RUNNING) && sample_en;

    always @(posedge clk) begin
	if (reset) begin
        done           <= 0;
        sample_counter <= 0;
        state          <= IDLE;     
    end
else begin 
        case (state)
            IDLE: begin
                sample_counter <= 0;   // reset ready for next capture
                done           <= 0;   // clear done flag from any previous run
                if (output_trigger)
                    state <= RUNNING;
                else
                    state <= IDLE;
            end
          RUNNING: begin
    if (sample_en) begin
        sample_counter <= sample_counter + 1;
        if (sample_counter == MAX_SAMPLES - 1) begin
            state <= FULL;
            done  <= 1;
        end else begin
            state <= RUNNING;
        end
    end
    else begin
        state <= RUNNING;
    end
end
            FULL: begin
                done <= 1;
                if (arm)
                    state <= IDLE;
                else
                    state <= FULL;
            end
            default: state <= IDLE;   //if state doesn't match IDLE, RUNNING, or FULL, do this instead.
                                          //safety net against unknown/undefined states

        endcase
    end
	 end
endmodule