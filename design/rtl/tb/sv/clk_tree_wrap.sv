// clk_tree_wrap.sv - test wrapper of clk_gate_tree: one 4-bit counter per word, clocked by that word's GATED clock, so a testbench can count exactly how many rising edges each word saw.
`timescale 1ns / 1ps
module clk_tree_wrap #(
    parameter int N      = 512,
    parameter int LEVELS = 3
) (
    input  logic                 clk_i,
    input  logic                 clr_i,
    input  logic                 we_i,
    input  logic [$clog2(N)-1:0] addr_i,
    output logic [N*4-1:0]       edges_o
);
  logic [N-1:0] gclk;
  clk_gate_tree #(
      .N     (N),
      .LEVELS(LEVELS)
  ) u_tree (
      .clk_i (clk_i),
      .clr_i (clr_i),
      .we_i  (we_i),
      .addr_i(addr_i),
      .gclk_o(gclk)
  );
  for (genvar i = 0; i < N; i++) begin : g_cnt
    logic [3:0] c = 4'd0;
    always @(posedge gclk[i]) c <= c + 4'd1;
    assign edges_o[i*4+:4] = c;
  end
endmodule
