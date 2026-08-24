module counter (
input clk,
input reset,
output reg [12:0] counter // 13 bits — can represent 0–8191
);
always @(posedge clk or posedge reset) begin
if (reset) //if reset=1,
counter <= 4'b0000; //reset the count to 0 
else 
counter <= counter+1; //otherwise increment the counter by 1
end 
endmodule