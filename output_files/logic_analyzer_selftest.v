module logic_analyzer_selftest (
    input  clk,
    input  reset,
    input  polarity,
    input  arm_raw,
    input  rd_strobe_raw,
    input  [1:0] rate,
    output data,
    output done,
    output led_heartbeat   // watch this LED to confirm the FPGA is alive/clocking
);
    reg [27:0] slow_counter;      // 50MHz clock -> need ~250,000,000 ticks for 5s
    reg probe_fake;

    always @(posedge clk) begin
        if (!reset) begin              // S1 idle = HIGH = running; S1 pressed = LOW = reset
            slow_counter <= 0;
            probe_fake   <= 0;
        end else if (slow_counter == 28'd249_999_999) begin  // 50,000,000 * 5
            slow_counter <= 0;
            probe_fake   <= ~probe_fake;   // toggle every 5 seconds
        end else begin
            slow_counter <= slow_counter + 1;
        end
    end

    assign led_heartbeat = probe_fake;

    logic_analyzer_top dut (
        .clk(clk),
        .reset(reset),
        .probe_in_raw(probe_fake),
        .polarity(polarity),
        .arm_raw(arm_raw),
        .rd_strobe_raw(rd_strobe_raw),
        .rate(rate),
        .data(data),
        .done(done)
    );
endmodule