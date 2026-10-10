`timescale 1ns / 1ps
module testbench;
  reg clk;
  reg areset;
  reg x;
  wire z;
  integer file, scenario;
  top_module DUT (.clk(clk), .areset(areset), .x(x), .z(z));

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    file = $fopen("TBout.txt", "w");
    scenario = 1;
    areset = 0;
    x = 0;
    areset = 0;
    x = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    areset = 0;
    x = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    areset = 0;
    x = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    areset = 1;
    x = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    areset = 0;
    x = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    areset = 1;
    x = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    areset = 1;
    x = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    areset = 0;
    x = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, areset = %d, x = %d, z = %d", scenario, clk, areset, x, z);
    #10;
    $fclose(file);
    $finish;
  end
endmodule
