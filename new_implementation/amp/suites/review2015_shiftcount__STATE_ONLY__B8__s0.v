`timescale 1ns / 1ps
module testbench;
  reg clk;
  reg shift_ena;
  reg count_ena;
  reg data;
  wire [3:0] q;
  integer file, scenario;
  top_module DUT (.clk(clk), .shift_ena(shift_ena), .count_ena(count_ena), .data(data), .q(q));

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    file = $fopen("TBout.txt", "w");
    scenario = 1;
    shift_ena = 0;
    count_ena = 0;
    data = 0;
    shift_ena = 0;
    count_ena = 0;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    shift_ena = 0;
    count_ena = 1;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    shift_ena = 0;
    count_ena = 1;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    shift_ena = 0;
    count_ena = 1;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    shift_ena = 0;
    count_ena = 1;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    shift_ena = 0;
    count_ena = 1;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    shift_ena = 0;
    count_ena = 1;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    shift_ena = 0;
    count_ena = 1;
    data = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, shift_ena = %d, count_ena = %d, data = %d, q = %d", scenario, clk, shift_ena, count_ena, data, q);
    #10;
    $fclose(file);
    $finish;
  end
endmodule
