// exit_ctrl.sv - Phase 4: margin comparator, exit FSM and the prediction register.
//
// After the score update of timestep t the query stage presents top1 (leader), top2 (second-largest score) and the leader's index (dec_valid_i). The margin is top1 - top2
// (an unsigned subtraction: top1 >= top2 by construction). EXIT when  EARLY_EXIT_EN && exit_en_i && margin >= theta_i. The prediction is the leader of THIS timestep, so the
// emitted prediction is the argmax at the exit timestep by construction (the testbench and test_exit_ctrl check it against the reference). The last timestep (T-1) always
// finishes the inference: its prediction is the final argmax, exactly Phase 3.
//
//   exited_q   : set when the margin fires; the integration holds the SNN's event intake from then on ("stop accepting events"); both arrays then idle.
//   pred_valid_o: one-cycle strobe the cycle after the decision (exit or last timestep); pred_o / pred_tstep_o / pred_early_o hold until the next sample.
// EARLY_EXIT_EN = 0 builds none of the comparator: the controller only latches the final prediction, which is the Phase 3 behaviour (and the "early exit OFF" ablation build).
import hdc_pkg::*;

module exit_ctrl #(
    parameter bit EARLY_EXIT_EN = EARLY_EXIT_EN_DEFAULT,
    parameter int N_TS = 100
) (
    input  logic                  clk_i,
    input  logic                  rst_n_i,
    input  logic                  clr_i,
    input  logic                  dec_valid_i,
    input  logic [  W_TADDR-1:0]  dec_tstep_i,
    input  logic [  W_CLASS-1:0]  top1_idx_i,
    input  logic [  W_SCORE-1:0]  top1_i,
    input  logic [  W_SCORE-1:0]  top2_i,
    input  logic [  W_THETA-1:0]  theta_i,
    input  logic                  exit_en_i,
    output logic                  fire_o,         // combinational: this decision cycle exits
    output logic [  W_SCORE-1:0]  margin_o,
    output logic                  exited_q_o,     // level: stop accepting events
    output logic                  pred_valid_o,
    output logic [  W_CLASS-1:0]  pred_o,
    output logic [  W_TADDR-1:0]  pred_tstep_o,
    output logic                  pred_early_o,
    output logic                  finished_o      // level: prediction emitted (exit or last timestep)
);
  localparam int W_CMP = (W_SCORE > W_THETA) ? W_SCORE : W_THETA;  // zero-extended compare width
  logic exited_q, fin_q, pv_q, early_q;
  logic [W_CLASS-1:0] pred_q;
  logic [W_TADDR-1:0] ts_q;
  logic last;

  assign last = (dec_tstep_i == W_TADDR'(N_TS - 1));

  if (EARLY_EXIT_EN) begin : g_cmp
    assign margin_o = top1_i - top2_i;
    assign fire_o   = dec_valid_i && exit_en_i && !fin_q && (W_CMP'(margin_o) >= W_CMP'(theta_i));
  end else begin : g_nocmp
    assign margin_o = '0;
    assign fire_o   = 1'b0;
    logic unused_n;
    assign unused_n = &{1'b0, top1_i, top2_i, theta_i, exit_en_i};
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      exited_q <= 1'b0;
      fin_q    <= 1'b0;
      pv_q     <= 1'b0;
      early_q  <= 1'b0;
      pred_q   <= '0;
      ts_q     <= '0;
    end else begin
      pv_q <= 1'b0;
      if (dec_valid_i && !fin_q && (fire_o || last)) begin
        pred_q   <= top1_idx_i;
        ts_q     <= dec_tstep_i;
        early_q  <= fire_o;
        fin_q    <= 1'b1;
        pv_q     <= 1'b1;
        exited_q <= fire_o;
      end
    end
  end

  assign exited_q_o   = exited_q;
  assign finished_o   = fin_q;
  assign pred_valid_o = pv_q;
  assign pred_o       = pred_q;
  assign pred_tstep_o = ts_q;
  assign pred_early_o = early_q;
endmodule
