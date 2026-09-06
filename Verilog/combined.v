module combined (
    input a,            // First input signal to the combined circuit
    input b,            // Second input signal to the combined circuit
    input c,             // Third input signal to the combined circuit
    output result         // Output of the combined circuit
);

    // Declare an internal wire to connect the AND gate's output
    // to the OR gate's input. This wire only exists inside this
    // module — it is not visible outside it.
    wire and_output;

    // Create (instantiate) an AND gate called "my_and".
    // This connects the module's inputs a and b to the AND gate's
    // inputs, and connects the AND gate's output to "and_output".
    // Effectively: and_output = a AND b
    AndGate my_and (
        .a(a),              // Connect module input a to gate input a
        .b(b),              // Connect module input b to gate input b
        .out(and_output)      // Gate's output goes into the wire and_output
    );

    // Create (instantiate) an OR gate called "my_or".
    // This takes the result of the AND gate (and_output) as one input,
    // and the module's input c as the other input.
    // Effectively: result = and_output OR c = (a AND b) OR c
    ORgate my_or (
        .a(and_output),        // First OR input comes from the AND gate's result
        .b(c),               // Second OR input is the module input c
        .out(result)          // Final output of the whole circuit
    );

endmodule