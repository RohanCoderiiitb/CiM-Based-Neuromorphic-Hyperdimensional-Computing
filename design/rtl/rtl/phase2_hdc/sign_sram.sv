// sign_sram.sv - BEHAVIOURAL MODEL of the sign-table SRAM macro of the factorized class memory (optimisation item 11): NTS words x N_CLASSES bits (100 x 10), written by the host's class image
// load, read once per timestep. It replaced 1,000 flip-flops, their 113 clock gates and a 100:1 read multiplexer. Single port, synchronous: a write (we_i) or a read (re_i) per cycle, never both.
// Under SYNTHESIS this module is a BLACKBOX (like cim_macro); its LEF / Liberty / energy come from synth/opt/gen_macros.py (CACTI 7, 45 nm, ITRS low-operating-power, 256 B: 1,130 um^2, 0.28 / 0.34 pJ
// per read / write, 4.6 uW leakage, 0.39 ns access) [ASSUM].
import hdc_pkg::*;

`ifdef SYNTHESIS
(* blackbox *)
module sign_sram #(
    parameter int W = 10
) (
    input  logic         clk_i,
    input  logic         we_i,
    input  logic         re_i,
    input  logic [6:0]   a_i,
    input  logic [W-1:0] d_i,
    output logic [W-1:0] q_o
);
endmodule
`else
module sign_sram #(
    parameter int W = 10
) (
    input  logic         clk_i,
    input  logic         we_i,
    input  logic         re_i,
    input  logic [6:0]   a_i,
    input  logic [W-1:0] d_i,
    output logic [W-1:0] q_o
);
  logic [W-1:0] mem[128];
  logic [W-1:0] q_q;
  always_ff @(posedge clk_i) begin
    if (we_i) mem[a_i] <= d_i;
    if (re_i) q_q <= mem[a_i];
  end
  assign q_o = q_q;
endmodule
`endif
