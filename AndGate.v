module AndGate ( //name of the module 
input a, //has an input called a
input b, // has an input called b
output out // has an output called out, notice there is no comma (Since there is a closing bracket of the variables)
); // closing the variables
assign out = a&b; // assign is a keyword that has continuous assignment, 
// the output signal being driven, declared in the module's port list.
// = :specifying the logic that drives out.
//a&b: the bitwise AND operator applied to a and b.
endmodule