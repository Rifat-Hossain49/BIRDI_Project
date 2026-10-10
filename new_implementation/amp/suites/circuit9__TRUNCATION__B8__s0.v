`timescale 1ns / 1ps
module testbench;
  reg clk;
  reg a;
  wire [2:0] q;
  integer file, scenario;
  top_module DUT (.clk(clk), .a(a), .q(q));

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    file = $fopen("TBout.txt", "w");
    scenario = 1;
    a = 0;
    a = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    a = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    a = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    a = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    a = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    a = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    a = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    a = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, a = %d, q = %d", scenario, clk, a, q);
    #10;
    $fclose(file);
    $finish;
  end
endmodule
