module logic_analyzer_10m50_top (
    input  clk,              // CLK50M_MAX10 — 50 MHz onboard clock (doc 683447 Table 15, pin J10)
    input  pb0_n,             // raw S1 pushbutton: active-low, idle HIGH, LOW while pressed (doc 683447 Table 11)
    input  probe_in_raw,       // real probe wire, Pmod A (J8) — passed straight through, no fake pattern
    input  polarity,            // DIP SW1.1 (doc 683447 Table 12)

    //From the MCU (STM32)
    input  arm_raw,
    input  rd_strobe_raw,
    input  [1:0] rate,

    //To the MCU (STM32)
    output data,
    output done
);

    // logic_analyzer_top's reset is synchronous ACTIVE-HIGH (every submodule
    // does `if (reset) ... <= 0`). S1 idle = HIGH = running; S1 pressed =
    // LOW = reset — so it has to be inverted here before it reaches the DUT,
    // or the chip sits in permanent reset except while someone is physically
    // holding the button down.
    wire reset = ~pb0_n;

    logic_analyzer_top dut (
        .clk(clk),
        .reset(reset),
        .probe_in_raw(probe_in_raw),
        .polarity(polarity),
        .arm_raw(arm_raw),
        .rd_strobe_raw(rd_strobe_raw),
        .rate(rate),
        .data(data),
        .done(done)
    );

endmodule
