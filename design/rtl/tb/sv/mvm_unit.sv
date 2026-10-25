// mvm_unit.sv - test wrapper for Level 3: blocks B (count_mem, SRAM), D (plane_seq, scan sequencer), E (cim_macro) and G (shift_accum) as ONE unit, with the testbench acting as the
// controller (no event_ctr, so arbitrary count vectors can be injected). Wiring is identical to snn_top. ready_o is low during the post-reset SRAM sweep.
import cim_neurohdc_pkg::*;

module mvm_unit #(
    parameter int ROWS_PER_GROUP  = 4,
    parameter int N_PARALLEL_COLS = 40
) (
    input  logic                     clk_i,
    input  logic                     rst_n_i,
    // counters
    input  logic                     ev_valid_i,
    input  logic [       W_ADDR-1:0] ev_addr_i,
    output logic                     busy_o,
    output logic                     ready_o,
    // weights (direct write port of the behavioural crossbar)
    input  logic                     wr_en_i,
    input  logic [  W_MACRO_IDX-1:0] wr_macro_i,
    input  logic [       W_ADDR-1:0] wr_addr_i,
    input  logic [    W_WL_WORD-1:0] wr_data_i,
    // sequencing
    input  logic                     start_i,          // pulse: clear X and scan the counters
    output logic                     seq_done_o,
    output logic [N_NEURONS*W_X-1:0] x_o,
    output logic [       W_STAT-1:0] active_o,
    output logic [       W_STAT-1:0] rows_skipped_o,
    output logic [       W_STAT-1:0] rows_read_o,
    output logic [       W_STAT-1:0] reads_allcols_o,
    output logic [       W_STAT-1:0] reads_plane_o,
    output logic [       W_STAT-1:0] reads_issued_o,
    output logic [       W_STAT-1:0] zero_groups_o,
    output logic                     rd_valid_o,
    output logic [        W_GRP-1:0] group_idx_o,
    output logic [    W_BIT_IDX-1:0] bitrow_idx_o,
    output logic [              3:0] assert_fail_o
);
  localparam int W_M = $clog2(ROWS_PER_GROUP + 1);
  localparam int W_PASS = (N_WCOLS / N_PARALLEL_COLS > 1) ? $clog2(N_WCOLS / N_PARALLEL_COLS) : 1;
  logic [W_COUNT-1:0] scan_q;
  logic scan_qv, scan_re, fwd;
  logic [W_ADDR-1:0] scan_addr;
  logic rd_valid, m_valid, seq_busy;
  logic [ROWS_PER_GROUP-1:0] rd_bits;
  logic [W_GRP-1:0] group_idx;
  logic [W_BIT_IDX-1:0] row_sel;
  logic [W_PASS-1:0] rd_pass;
  logic [N_PARALLEL_COLS*W_M-1:0] m_data;

  count_mem u_count_mem (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .ev_valid_i(ev_valid_i), .ev_addr_i(ev_addr_i), .wipe_i(1'b0), .flush_i(1'b0),
      .scan_re_i(scan_re), .scan_addr_i(scan_addr), .q_o(scan_q), .scan_qv_o(scan_qv), .busy_o(busy_o), .ready_o(ready_o), .fwd_o(fwd),
      .chk_i(1'b0), .chk_expected_i('0), .assert_fail_o(assert_fail_o[0])
  );
  plane_seq #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_plane_seq (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .start_i(start_i), .abort_i(1'b0),
      .scan_re_o(scan_re), .scan_addr_o(scan_addr), .scan_q_i(scan_q), .scan_qv_i(scan_qv),
      .rd_valid_o(rd_valid), .rd_bits_o(rd_bits), .group_idx_o(group_idx), .row_sel_o(row_sel), .pass_o(rd_pass),
      .done_o(seq_done_o), .busy_o(seq_busy), .active_o(active_o), .rows_skipped_o(rows_skipped_o), .rows_read_o(rows_read_o), .reads_allcols_o(reads_allcols_o),
      .reads_plane_o(reads_plane_o), .reads_issued_o(reads_issued_o), .zero_groups_o(zero_groups_o), .assert_fail_o(assert_fail_o[1])
  );
  localparam int WGM = (N_INPUTS / ROWS_PER_GROUP) > 1 ? $clog2(N_INPUTS / ROWS_PER_GROUP) : 1;      // one group (g = 512): the macro's group port is empty, a 1-bit slice of the (zero) index is passed
  cim_macro #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_cim_macro (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .wr_en_i(wr_en_i), .wr_macro_i(wr_macro_i), .wr_addr_i(wr_addr_i), .wr_data_i(wr_data_i),
      .rd_valid_i(rd_valid), .rd_bits_i(rd_bits), .rd_grp_i(group_idx[WGM-1:0]), .rd_pass_i(rd_pass), .m_valid_o(m_valid), .m_o(m_data)
  );
  shift_accum #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_shift_accum (
      .clk_i(clk_i), .rst_n_i(rst_n_i), .clr_i(start_i), .iss_valid_i(rd_valid), .iss_b_i(row_sel), .iss_pass_i(rd_pass), .iss_bits_i(rd_bits),
      .m_valid_i(m_valid), .m_i(m_data), .x_o(x_o), .assert_fail_o(assert_fail_o[2])
  );
  assign rd_valid_o = rd_valid;
  assign group_idx_o = group_idx;
  assign bitrow_idx_o = row_sel;
  assign assert_fail_o[3] = 1'b0;
  logic unused_ok;
  assign unused_ok = &{1'b0, fwd, seq_busy};
endmodule
