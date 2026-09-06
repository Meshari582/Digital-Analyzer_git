`ifndef LOGIC_ANALYZER_PARAMS_VH
`define LOGIC_ANALYZER_PARAMS_VH

// Sample buffer geometry. Kept in one place because capture.v (sample
// counter / MAX_SAMPLES), buffer.v (mem array / address ports), readout.v
// (raddr) and logic_analyzer_top.v (sample_counter/raddr wires) all have to
// agree on the same depth and address width.
`define BUFFER_DEPTH 16384          // samples per capture
`define ADDR_WIDTH   14             // bits needed to address BUFFER_DEPTH-1

// Board clock and the four MCU-selectable sample-rate dividers (rate_div's
// N parameter, one instance per rate[1:0] selection in logic_analyzer_top).
`define CLK_HZ     50_000_000
`define RATE_DIV_0 5
`define RATE_DIV_1 50
`define RATE_DIV_2 500
`define RATE_DIV_3 5000

`endif // LOGIC_ANALYZER_PARAMS_VH
