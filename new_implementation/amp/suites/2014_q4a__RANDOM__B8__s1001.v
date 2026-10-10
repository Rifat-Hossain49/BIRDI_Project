`timescale 1ns / 1ps
module testbench;
  reg clk;
  reg w;
  reg R;
  reg E;
  reg L;
  wire Q;
  integer file, scenario;
  top_module DUT (.clk(clk), .w(w), .R(R), .E(E), .L(L), .Q(Q));

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    file = $fopen("TBout.txt", "w");
    scenario = 1;
    w = 0;
    R = 0;
    E = 0;
    L = 0;
    w = 0;
    R = 0;
    E = 0;
    L = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    w = 0;
    R = 1;
    E = 1;
    L = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    w = 0;
    R = 0;
    E = 0;
    L = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    w = 0;
    R = 0;
    E = 0;
    L = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    w = 1;
    R = 0;
    E = 0;
    L = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    w = 1;
    R = 0;
    E = 1;
    L = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    w = 1;
    R = 1;
    E = 0;
    L = 1;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    w = 0;
    R = 0;
    E = 0;
    L = 0;
    $fdisplay(file, "[check]scenario: %d, clk = %d, w = %d, R = %d, E = %d, L = %d, Q = %d", scenario, clk, w, R, E, L, Q);
    #10;
    $fclose(file);
    $finish;
  end
endmodule
