`timescale 1ns / 1ps
module testbench;
reg  clk;
reg  load;
reg  ena;
reg [1:0] amount;
reg [63:0] data;
wire [63:0] q;

integer file, scenario;
// DUT instantiation
top_module DUT (
    .clk(clk),
    .load(load),
    .ena(ena),
    .amount(amount),
    .data(data),
    .q(q)
);
// Clock generation
initial begin
    clk = 0;
    forever #5 clk = ~clk;
end

initial begin
    file = $fopen("TBout.txt", "w");
end
// Scenario Based Test
initial begin
    // scenario 1
    scenario = 1;
    load = 1;
    ena = 0;
    amount = 2'b00;
    data = 64'hAAAAAAAAAAAAAAAA;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 1
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 2
    scenario = 2;
    load = 0;
    ena = 1;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 
    amount = 2'b00;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 2
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 3
    scenario = 3;
    amount = 2'b01;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 3
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 4
    scenario = 4;
    amount = 2'b10;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 4
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 5
    scenario = 5;
    amount = 2'b11;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 5
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 6
    scenario = 6;
    ena = 0;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 
    amount = 2'b00;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 6
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 7
    scenario = 7;
    load = 1;
    ena = 0;
    data = 64'h5555555555555555;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 7
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 8
    scenario = 8;
    load = 1;
    data = 64'hFFFFFFFFFFFFFFFF;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 8
    ena = 1;
    load = 0;
    amount = 2'b00;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 9
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 9
    scenario = 9;
    load = 1;
    data = 64'h8000000000000000;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Loading at Cycle 10
    load = 0;
    ena = 1;
    amount = 2'b10;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 10
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 
    amount = 2'b11;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 11
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 

    // scenario 10
    scenario = 10;
    load = 0;
    amount = 2'b00;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10;
    repeat(3) begin
        $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q); #10; 
    end

    // scenario 11
    scenario = 11;
    load = 1;
    ena = 0;
    data = 64'h123456789ABCDEF0;
    $fdisplay(file, "scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);
    #10; // Cycle 15
    $fdisplay(file, "[check]scenario: %d, clk = %d, load = %d, ena = %d, amount = %d, data = %d, q = %d", scenario, clk, load, ena, amount, data, q);

    $fclose(file);
    $finish;
end

endmodule
