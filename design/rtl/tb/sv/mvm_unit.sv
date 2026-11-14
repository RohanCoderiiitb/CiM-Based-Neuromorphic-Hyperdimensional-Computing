// mvm_unit.sv - test wrapper for Level 3: blocks B (count_mem, SRAM), D (plane_seq, packed-row scan sequencer), E (cim_macro), G (shift_accum) and H (if_neuron_array, which accumulates the reads into V) as ONE
// unit, with the testbench acting as the controller (no event_ctr, so arbitrary count vectors can be injected). Wiring is identical to snn_top. ready_o is low during the post-reset SRAM sweep.
// The counter set flips at every start_i (as snn_ctrl does at the hand-over); after seq_done_o the wrapper runs the neuron update (N_PASSES cycles) and pulses xvalid_o: x_o is then the X of the vector.
import cim_neurohdc_pkg::*;

module mvm_unit #(
    parameter int ROWS_PER_GROUP  = 4,
    parameter int N_PARALLEL_COLS = 40
) (
    input  logic                     clk_i,
    input  logic                     rst_n_i,
    // counters (lane 0 only)
    input  logic                     ev_valid_i,
    input  logic [       W_ADDR-1:0] ev_addr_i,
    output logic                     busy_o,
    output logic                     ready_o,
    output logic                     lane_ok_o,
    // weights (direct write port of the behavioural crossbar)
    input  logic                     wr_en_i,
    input  logic [  W_MACRO_IDX-1:0] wr_macro_i,
    input  logic [       W_ADDR-1:0] wr_addr_i,
    input  logic [    W_WL_WORD-1:0] wr_data_i,
    // sequencing
    input  logic                     start_i,          // pulse: scan the counters of the set that was just filled
    output logic                     seq_done_o,
    output logic                     xvalid_o,         // the neuron update has finished: x_o is the X of the vector
    output logic [N_NEURONS*W_X-1:0] x_o,
    output logic [       W_STAT-1:0] active_o,
    output logic [       W_STAT-1:0] rows_skipped_o,
    output logic [       W_STAT-1:0] rows_read_o,
    output logic [       W_STAT-1:0] reads_allcols_o,
    output logic [       W_STAT-1:0] reads_plane_o,
    output logic [       W_STAT-1:0] reads_issued_o,
    output logic [       W_STAT-1:0] zero_groups_o,
    output logic                     rd_valid_o,
    output logic [  S_ROWS*W_RB-1:0] rd_rows_o,
    output logic [      W_BAND-1:0]  rd_band_o,
    output logic [    W_BIT_IDX-1:0] bitrow_idx_o,
    output logic [              4:0] assert_fail_o
);
  localparam int W_M = $clog2(ROWS_PER_GROUP + 1);
  localparam int N_PASSES = N_WCOLS / N_PARALLEL_COLS;
  localparam int W_PASS = (N_PASSES > 1) ? $clog2(N_PASSES) : 1;
  localparam int PN = N_PARALLEL_COLS / W_WEIGHT;
  logic [ROWS_PER_GROUP*W_COUNT-1:0] scan_q;
  logic scan_qv, scan_re, scan_clr, fwd;
  logic [W_GRP-1:0] scan_grp;
  logic rd_valid, m_valid, seq_busy, ing_sel_q, scan_set;
  logic cm_in_ready, dirty_clr, dirty_clr_set;
  logic [2*(N_INPUTS/ROWS_PER_GROUP/N_DIRTY_GS)-1:0] dirty;
  logic [S_ROWS-1:0] rd_rv;
  logic [S_ROWS*W_RB-1:0] rd_rows;
  logic [W_BAND-1:0] rd_band;
  logic [W_BIT_IDX-1:0] row_sel;
  logic [W_PASS-1:0] rd_pass;
  logic [N_PARALLEL_COLS*W_M-1:0] m_data;
  logic acc_valid;
  logic [W_PASS-1:0] acc_pass;
  logic [PN*W_V-1:0] acc_d;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) ing_sel_q <= 1'b0;
    else if (start_i) ing_sel_q <= ~ing_sel_q;
  end

  logic [N_LANES-1:0] ev_v;
  logic [N_LANES*W_ADDR-1:0] ev_a;
  assign ev_v = {{(N_LANES - 1) {1'b0}}, ev_valid_i};
  assign ev_a = {{((N_LANES - 1) * W_ADDR) {1'b0}}, ev_addr_i};
  assign cm_in_ready = 1'b1;
  assign lane_ok_o = cm_in_ready;

  count_mem u_count_mem (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .ev_valid_i(ev_v), .ev_addr_i(ev_a), .wipe_i(1'b0), .flush_i(1'b0), .ing_sel_i(ing_sel_q), .scan_set_i(scan_set),
      .scan_re_i(scan_re), .scan_clr_i(scan_clr), .scan_grp_i(scan_grp[W_BANK_ADDR-1:0]), .q_o(scan_q), .scan_qv_o(scan_qv),
      .busy_o(busy_o), .ready_o(ready_o), .dirty_o(dirty), .dirty_clr_i(dirty_clr), .dirty_clr_set_i(dirty_clr_set), .fwd_o(fwd),
      .chk_i(1'b0), .chk_expected_i('0), .assert_fail_o(assert_fail_o[0])
  );
  plane_seq #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_plane_seq (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .start_i(start_i), .abort_i(1'b0), .ing_sel_i(ing_sel_q), .scan_set_o(scan_set), .dirty_i(dirty), .dirty_clr_o(dirty_clr), .dirty_clr_set_o(dirty_clr_set),
      .scan_re_o(scan_re), .scan_clr_o(scan_clr), .scan_grp_o(scan_grp), .scan_q_i(scan_q), .scan_qv_i(scan_qv),
      .rd_valid_o(rd_valid), .rd_rv_o(rd_rv), .rd_rows_o(rd_rows), .rd_band_o(rd_band), .row_sel_o(row_sel), .pass_o(rd_pass),
      .done_o(seq_done_o), .busy_o(seq_busy), .active_o(active_o), .rows_skipped_o(rows_skipped_o), .rows_read_o(rows_read_o), .reads_allcols_o(reads_allcols_o),
      .reads_plane_o(reads_plane_o), .reads_issued_o(reads_issued_o), .zero_groups_o(zero_groups_o), .assert_fail_o(assert_fail_o[1])
  );
  cim_macro #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_cim_macro (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .wr_en_i(wr_en_i), .wr_macro_i(wr_macro_i), .wr_addr_i(wr_addr_i), .wr_data_i(wr_data_i),
      .rd_valid_i(rd_valid), .rd_rv_i(rd_rv), .rd_rows_i(rd_rows), .rd_band_i(rd_band), .rd_pass_i(rd_pass), .m_valid_o(m_valid), .m_o(m_data)
  );
  shift_accum #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_shift_accum (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .iss_valid_i(rd_valid), .iss_b_i(row_sel), .iss_pass_i(rd_pass), .iss_bits_i(rd_rv),
      .m_valid_i(m_valid), .m_i(m_data), .d_valid_o(acc_valid), .d_pass_o(acc_pass), .d_o(acc_d), .assert_fail_o(assert_fail_o[2])
  );

  // the update runs N_PASSES cycles after the scan has finished (one cycle after seq_done_o: the last result is accumulated)
  logic [3:0] upd_cnt_q;
  logic upd, upd_q, run_q;
  logic [N_NEURONS-1:0] spike;
  logic [N_NEURONS*W_V-1:0] v_unused;
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      upd_cnt_q <= '0;
      run_q <= 1'b0;
      upd_q <= 1'b0;
    end else begin
      upd_q <= run_q && (upd_cnt_q == 4'(N_PASSES - 1));
      if (seq_done_o) begin
        run_q <= 1'b1;
        upd_cnt_q <= '0;
      end else if (run_q) begin
        if (upd_cnt_q == 4'(N_PASSES - 1)) run_q <= 1'b0;
        upd_cnt_q <= upd_cnt_q + 4'd1;
      end
    end
  end
  assign upd = run_q;
  assign xvalid_o = upd_q;
  if_neuron_array #(
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_neurons (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .clr_i(1'b0), .acc_i(acc_valid), .acc_pass_i(acc_pass), .d_i(acc_d), .upd_i(upd), .thresh_i({N_NEURONS{W_THRESH'(16383)}}),
      .thresh_shared_i(1'b0), .spike_o(spike), .upd_done_o(), .v_o(v_unused), .x_o(x_o), .assert_fail_o(assert_fail_o[4])
  );
  assign rd_valid_o = rd_valid;
  assign rd_rows_o = rd_rows;
  assign rd_band_o = rd_band;
  assign bitrow_idx_o = row_sel;
  assign assert_fail_o[3] = 1'b0;
  logic unused_ok;
  assign unused_ok = &{1'b0, fwd, seq_busy, spike, v_unused};
endmodule
