module readout (
    input clk,
    input reset,           // resets raddr back to page 0 at the start of a new capture
    input rd_strobe,            
    input rdata,           
    output reg [13:0] raddr,   // which page to read from
    output reg data_out       // the bit that comes back off that page
);
    reg pending;   // "raddr just moved, rdata isn't caught up yet"

    always @(posedge clk or posedge reset) begin
        if (reset) begin
            raddr    <= 0;
            data_out <= 0;      // start over at page 0
            pending  <= 0;
        end
        else if (rd_strobe) begin
            raddr   <= raddr + 1;   // move on to the next page
            pending <= 1;             // remember: rdata not ready yet
        end
        else if (pending) begin
            data_out <= rdata;      // buffer has caught up, grab it now
            pending  <= 0;
        end
    end
endmodule