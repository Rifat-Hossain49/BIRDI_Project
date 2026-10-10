`timescale 1ns / 1ps
module testbench;
  reg clk;
  reg slowena;
  reg reset;
  wire [3:0] q;
  integer file, scenario;
  top_module DUT (.clk(clk), .slowena(slowena), .reset(reset), .q(q));

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    file = $fopen("TBout.txt", "w");
    scenario = 1;
    slowena = 0;
    reset = 0;
    slowena = 1;
    reset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    slowena = 1;
    reset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    slowena = 1;
    reset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    slowena = 1;
    reset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    slowena = 1;
    reset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    slowena = 1;
    reset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    slowena = 1;
    reset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    slowena = 1;
    reset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, slowena = %d, reset = %d, q = %d", scenario, clk, slowena, reset, q);
    #10;
    $fclose(file);
    $finish;
  end
endmodule
