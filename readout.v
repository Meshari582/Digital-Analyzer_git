module readout (
    input clk,
    input reset,           // resets raddr back to page 0 at the start of a new capture
    input rd_strobe,            
    input rdata,           
    output reg [13:0] raddr,   // which page to read from
    output reg data_out       // the bit that comes back off that page
);
    always @(posedge clk) begin
        if (reset) begin
            raddr    <= 0;
            data_out <= 0;      // start over at page 0
        end
        else begin
            data_out <= rdata;      // rdata is always mem[raddr] — no strobe needed to see it
            if (rd_strobe)
                raddr <= raddr + 1;   // advance AFTER the current sample has been read
        end
    end
endmodule