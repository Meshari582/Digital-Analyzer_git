`include "logic_analyzer_params.vh"

module buffer (
    input clk,
    // WRITING side — used by capture
    input we,             // "write enable" — only actually write when this is high
    input [`ADDR_WIDTH-1:0] waddr,   // which page to write to (14 bits covers 0-16383)
    input wdata,           // the bit to write onto that page
    // READING side — used by readout
    input [`ADDR_WIDTH-1:0] raddr,   // which page to read from
    output reg rdata       // the bit that comes back off that page
);
reg mem [0:`BUFFER_DEPTH-1];   // the notebook: 16384 pages, 1 bit each
always @(posedge clk) begin
    if (we)
        mem[waddr] <= wdata;
end
always @(posedge clk) begin
    rdata <= mem[raddr];
end
endmodule