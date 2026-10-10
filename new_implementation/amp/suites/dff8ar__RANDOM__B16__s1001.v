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
    d = 30;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 46;
    areset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 82;
    areset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 191;
    areset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 101;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 15;
    areset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 96;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 9;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 208;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 51;
    areset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 222;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 200;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 156;
    areset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 85;
    areset = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 18;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    d = 48;
    areset = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, d = %d, areset = %d, q = %d", scenario, clk, d, areset, q);
    #10;
    $fclose(file);
    $finish;
  end
endmodule
