`timescale 1ns / 1ps
module testbench;
  reg clk;
  reg [7:0] d;
  reg areset;
  wire [7:0] q;
  integer file, scenario;
  top_module DUT (.clk(clk), .d(d), .areset(areset), .q(q));

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    file = $fopen("TBout.txt", "w");
    scenario = 1;
    d = 0;
    areset = 0;
    d = 0;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 1;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 2;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 3;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 4;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 5;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 6;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 7;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 8;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 9;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 10;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 11;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 12;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 13;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 14;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 15;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    $fclose(file);
    $finish;
  end
endmodule
