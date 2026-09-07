## LogicAnalyzer.sdc
## Clock source: CLK50M_MAX10, PIN_J10, 50.000 MHz crystal oscillator (U15)
## per MAX 10 FPGA 10M50 Evaluation Kit User Guide (doc 683447), Table 15,
## and confirmed against LogicAnalyzer.qsf: set_location_assignment PIN_J10 -to clk.
## logic_analyzer_top is a single-clock synchronous design -- every register
## in the hierarchy (sync, trigger, rate_div/counter, capture, buffer,
## readout) is clocked by this one port.

create_clock -name clk -period 20.000 [get_ports {clk}]

derive_clock_uncertainty
