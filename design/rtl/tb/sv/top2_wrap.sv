// top2_wrap.sv - clocked wrapper for the cocotb test of the combinational top2_tree (registered inputs and outputs, so every simulator evaluates it on a clock edge).
module top2_wrap #(
    parameter int N = 10,
    parameter int W = 11,
    parameter int WI = 5
) (
    input  logic           clk_i,
    input  logic           rst_n_i,
    input  logic [N*W-1:0] scores_i,
    output logic [  W-1:0] v1_o,
    output logic [ WI-1:0] i1_o,
    output logic [  W-1:0] v2_o
);
  logic [N*W-1:0] s_q;
  logic [  W-1:0] v1_d, v2_d;
  logic [ WI-1:0] i1_d;
  always_ff @(posedge clk_i) s_q <= rst_n_i ? scores_i : '0;
  top2_tree #(
      .N (N),
      .W (W),
      .WI(WI)
  ) u_t (
      .scores_i(s_q),
      .v1_o    (v1_d),
      .i1_o    (i1_d),
      .v2_o    (v2_d)
  );
  always_ff @(posedge clk_i) begin
    v1_o <= v1_d;
    i1_o <= i1_d;
    v2_o <= v2_d;
  end
endmodule
