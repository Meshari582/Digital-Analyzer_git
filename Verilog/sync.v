module sync (
    input  clk,      // System clock — both flip-flops update on its rising edge
    input  reset,    // Synchronous reset — forces the whole chain to 0
    input  d,        // Raw, potentially unstable async input signal
    output q         // Final synced output — safe to use elsewhere in the design
);
// 2 clock cycles between d and q
    // Internal wire connecting the first flip-flop's output to the
    // second flip-flop's input. Not visible outside this module.
    wire q1;

    // First flip-flop: catches the raw async input. Its output (q1)
    // may be briefly unstable (metastable) if d changes right at
    // the clock edge.
    DFlipFlop DflipFlop1 (
        .clk(clk),
        .reset(reset),
        .d(d),
        .q(q1)
    );

    // Second flip-flop: samples q1 one clock cycle later, by which
    // point any metastability has almost certainly resolved.
    // Its output (q) is the clean, synced signal.
    DFlipFlop DflipFlop2 (
        .clk(clk),
        .reset(reset),
        .d(q1),
        .q(q)
    );

endmodule