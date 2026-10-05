// mvm_unit.sv - test wrapper for Level 3: blocks B (count_mem), D (plane_seq), E (cim_macro), G (shift_accum) as ONE unit, with the testbench
// acting as the controller (no event_ctr, so arbitrary count vectors can be injected). Wiring is identical to snn_top.
import cim_neurohdc_pkg::*;

module mvm_unit #(
    parameter int ROWS_PER_GROUP  = 8,
    parameter int N_PARALLEL_COLS = 160,
    parameter bit PLANE_SKIP_EN   = 1'b1
) (
    input  logic                     clk_i,
    input  logic                     rst_n_i,
    // counters
    input  logic                     ev_valid_i,
    input  logic [       W_ADDR-1:0] ev_addr_i,
    input  logic                     wipe_i,
    output logic                     busy_o,
    // weights (direct write port of the behavioural crossbar)
    input  logic                     wr_en_i,
    input  logic [  W_MACRO_IDX-1:0] wr_macro_i,
    input  logic [       W_ADDR-1:0] wr_addr_i,
    input  logic [    W_WL_WORD-1:0] wr_data_i,
    // sequencing
    input  logic                     start_i,          // pulse: clear X and walk the bit-rows
    output logic                     seq_done_o,
    output logic [N_NEURONS*W_X-1:0] x_o,
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
  logic [N_INPUTS-1:0] row, active_vec, row_drv;
  logic row_nz, fwd, chk_unused;
  logic [W_BIT_IDX-1:0] row_sel;
  logic rd_valid, rd_last, m_valid;
  logic [W_GRP-1:0] group_idx;
  logic [W_WEIGHT-1:0] plane_mask;
  logic [W_M_FLAT-1:0] m_data;
  logic [W_PCOUNT-1:0] a_row;
  logic seq_busy;

  count_mem u_count_mem (
      .clk_i(clk_i),
      .rst_n_i(rst_n_i),
      .ev_valid_i(ev_valid_i),
      .ev_addr_i(ev_addr_i),
      .wipe_i(wipe_i),
      .row_sel_i(row_sel),
      .row_o(row),
      .row_nz_o(row_nz),
      .active_o(active_vec),
      .busy_o(busy_o),
      .fwd_o(fwd),
      .chk_i(1'b0),
      .chk_expected_i('0),
      .assert_fail_o(assert_fail_o[0])
  );
  plane_seq #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS),
      .PLANE_SKIP_EN  (PLANE_SKIP_EN)
  ) u_plane_seq (
      .clk_i(clk_i),
      .rst_n_i(rst_n_i),
      .start_i(start_i),
      .row_nz_i(row_nz),
      .row_sel_o(row_sel),
      .rd_valid_o(rd_valid),
      .group_idx_o(group_idx),
      .plane_mask_o(plane_mask),
      .rd_last_o(rd_last),
      .done_o(seq_done_o),
      .busy_o(seq_busy),
      .rows_skipped_o(rows_skipped_o),
      .rows_read_o(rows_read_o),
      .reads_allcols_o(reads_allcols_o),
      .reads_plane_o(reads_plane_o),
      .reads_issued_o(reads_issued_o),
      .assert_fail_o(assert_fail_o[1])
  );
  assign row_drv = rd_valid ? row : '0;
  cim_macro #(
      .ROWS_PER_GROUP(ROWS_PER_GROUP)
  ) u_cim_macro (
      .clk_i(clk_i),
      .rst_n_i(rst_n_i),
      .wr_en_i(wr_en_i),
      .wr_macro_i(wr_macro_i),
      .wr_addr_i(wr_addr_i),
      .wr_data_i(wr_data_i),
      .rd_valid_i(rd_valid),
      .rd_bitrow_i(row_drv),
      .rd_grp_i(group_idx),
      .rd_plane_mask_i(plane_mask),
      .m_valid_o(m_valid),
      .m_o(m_data)
  );
  shift_accum #(
      .ROWS_PER_GROUP(ROWS_PER_GROUP)
  ) u_shift_accum (
      .clk_i(clk_i),
      .rst_n_i(rst_n_i),
      .clr_i(start_i),
      .iss_valid_i(rd_valid),
      .iss_bitrow_i(row_drv),
      .iss_grp_i(group_idx),
      .iss_b_i(row_sel),
      .iss_last_i(rd_last),
      .iss_plane0_i(plane_mask[0]),
      .m_valid_i(m_valid),
      .m_i(m_data),
      .a_row_o(a_row),
      .x_o(x_o),
      .zero_groups_o(zero_groups_o),
      .assert_fail_o(assert_fail_o[2])
  );
  assign rd_valid_o = rd_valid;
  assign group_idx_o = group_idx;
  assign bitrow_idx_o = row_sel;
  assign assert_fail_o[3] = 1'b0;
  logic unused_ok;
  assign unused_ok  = &{1'b0, active_vec, fwd, chk_unused, a_row, seq_busy};
  assign chk_unused = 1'b0;
endmodule
