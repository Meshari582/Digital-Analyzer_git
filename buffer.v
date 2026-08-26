module buffer (
    input clk,

    // WRITING side — used by capture
    input we,             // "write enable" — only actually write when this is high
    input [13:0] waddr,   // which page to write to (14 bits covers 0–16383)
    input wdata,           // the bit to write onto that page

    // READING side — used by readout
    input [13:0] raddr,   // which page to read from
    output reg rdata       // the bit that comes back off that page
);
reg mem [0:16383];   // the notebook: 16384 pages, 1 bit each
integer init_i;                         
initial begin
    for (init_i = 0; init_i < 16384; init_i = init_i + 1) // mem all starts at 0 for all 16384 bits 
        mem[init_i] = 1'b0;
end

always @(posedge clk) begin
    if (we)
        mem[waddr] <= wdata;
end
always @(posedge clk) begin
    rdata <= mem[raddr];
end

endmodule