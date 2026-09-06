module counter_wide (
    input clk,
    input reset,
    output reg [12:0] counter // 13 bits — 0 to 8191, covers N up to 5000
);
    always @(posedge clk) begin
        if (reset)
            counter <= 13'b0;
        else
            counter <= counter + 1;
    end
endmodule