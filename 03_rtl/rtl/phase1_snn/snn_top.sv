// snn_top.sv - Phase 1E top level: events in, 20 spike bits out, once per timestep, N_TIMESTEPS timesteps.
//   event -> addr_gen -> count_mem -> [plane_seq -> cim_macro (behavioural crossbar) -> shift_accum] -> if_neuron_array -> spike_reg
//                          ^ event_ctr decides when the timestep ends;  snn_ctrl sequences everything.
// ROWS_PER_GROUP (g) and N_PARALLEL_COLS are parameters: the output raster is bit-identical for every value (tests/test_g_sweep).
// `group_idx_o` / `rd_*_o` expose each crossbar read so the analog side can select its per-group comparator ladder (1B).






import cim_neurohdc_pkg::AER_SHIFT_DVS;
import cim_neurohdc_pkg::AER_SHIFT_NMNIST;
import cim_neurohdc_pkg::CFG_AER_SHIFT;
import cim_neurohdc_pkg::CFG_COORD_MUL;
import cim_neurohdc_pkg::CFG_N_EVENTS;
import cim_neurohdc_pkg::CFG_THRESH_BASE;
import cim_neurohdc_pkg::CFG_THRESH_SHARED;
import cim_neurohdc_pkg::COORD_MUL_DVS;
import cim_neurohdc_pkg::COORD_MUL_NMNIST;
import cim_neurohdc_pkg::GEOM_NMNIST_DEFAULT;
import cim_neurohdc_pkg::INSTRUMENT_EN_DEFAULT;
import cim_neurohdc_pkg::N_INPUTS;
import cim_neurohdc_pkg::N_NEURONS;
import cim_neurohdc_pkg::N_PARALLEL_COLS_DEFAULT;
import cim_neurohdc_pkg::PLANE_SKIP_EN_DEFAULT;
import cim_neurohdc_pkg::ROWS_PER_GROUP_DEFAULT;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_AER;
import cim_neurohdc_pkg::W_BIT_IDX;
import cim_neurohdc_pkg::W_CFG_ADDR;
import cim_neurohdc_pkg::W_CFG_DATA;
import cim_neurohdc_pkg::W_COORD;
import cim_neurohdc_pkg::W_COORD_MUL;
import cim_neurohdc_pkg::W_GRP;
import cim_neurohdc_pkg::W_MACRO_IDX;
import cim_neurohdc_pkg::W_M_FLAT;
import cim_neurohdc_pkg::W_NEVENTS;
import cim_neurohdc_pkg::W_PCOUNT;
import cim_neurohdc_pkg::W_STAT;
import cim_neurohdc_pkg::W_THRESH;
import cim_neurohdc_pkg::W_TSTEP;
import cim_neurohdc_pkg::W_V;
import cim_neurohdc_pkg::W_WEIGHT;
import cim_neurohdc_pkg::W_WL_WORD;
import cim_neurohdc_pkg::W_X;

module snn_top #(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT,
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    parameter bit PLANE_SKIP_EN = PLANE_SKIP_EN_DEFAULT,
    parameter bit INSTRUMENT_EN = INSTRUMENT_EN_DEFAULT,
    parameter bit GEOM_NMNIST = GEOM_NMNIST_DEFAULT
) (
    input  logic                     clk_i,
    input  logic                     rst_n_i,
    // configuration (writable in IDLE / LOAD / DONE only)
    input  logic                     cfg_we_i,
    input  logic [   W_CFG_ADDR-1:0] cfg_addr_i,
    input  logic [   W_CFG_DATA-1:0] cfg_data_i,
    // weight image shift-in
    input  logic                     load_start_i,
    input  logic                     wl_valid_i,
    input  logic [    W_WL_WORD-1:0] wl_data_i,
    output logic                     wl_ready_o,
    // run control
    input  logic                     start_i,
    input  logic                     ingest_en_i,
    // AER event stream (valid/ready)
    input  logic                     ev_valid_i,
    input  logic [        W_AER-1:0] ev_aer_i,
    output logic                     ev_ready_o,
    // result
    output logic [    N_NEURONS-1:0] spike_o,
    output logic                     spike_valid_o,
    output logic [      W_TSTEP-1:0] spike_tstep_o,
    output logic                     done_o,
    output logic [              1:0] state_o,
    output logic                     weights_loaded_o,
    // crossbar read side-band for the analog ladder select
    output logic                     rd_valid_o,
    output logic [        W_GRP-1:0] group_idx_o,
    output logic [    W_BIT_IDX-1:0] bitrow_idx_o,
    // DEBUG_EXPOSE_V
    output logic [N_NEURONS*W_X-1:0] x_o,
    output logic [N_NEURONS*W_V-1:0] v_o,
    // per-timestep instrumentation (valid with spike_valid_o)
    output logic [       W_STAT-1:0] ts_events_o,
    output logic [       W_STAT-1:0] ts_active_o,
    output logic [       W_STAT-1:0] ts_rows_skipped_o,
    output logic [       W_STAT-1:0] ts_rows_read_o,
    output logic [       W_STAT-1:0] ts_reads_allcols_o,
    output logic [       W_STAT-1:0] ts_reads_plane_o,
    output logic [       W_STAT-1:0] ts_reads_issued_o,
    output logic [       W_STAT-1:0] ts_zero_groups_o,
    output logic [       W_STAT-1:0] ts_fwd_o,
    output logic [       W_STAT-1:0] ts_cycles_o,
    output logic [       W_STAT-1:0] ts_cycles_ingest_o,
    output logic [       W_STAT-1:0] cyc_total_o,
    output logic [              7:0] assert_fail_o        // one sticky bit per block that carries assertions + top
);
  // ------------------------------------------------------------------ configuration registers
  logic signed [W_THRESH-1:0] thresh_q[N_NEURONS];
  logic [W_COORD_MUL-1:0] coord_mul_q;
  logic [W_BIT_IDX-1:0] aer_shift_q;
  logic thresh_shared_q;
  logic cfg_n_we;
  logic [W_CFG_ADDR-1:0] thr_idx;
  logic [N_NEURONS*W_THRESH-1:0] thresh_flat;
  logic top_cfg_fail_q;

  assign thr_idx  = cfg_addr_i - W_CFG_ADDR'(CFG_THRESH_BASE);
  assign cfg_n_we = cfg_we_i && (cfg_addr_i == W_CFG_ADDR'(CFG_N_EVENTS));

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      for (int j = 0; j < N_NEURONS; j++) thresh_q[j] <= '0;
      coord_mul_q     <= GEOM_NMNIST ? W_COORD_MUL'(COORD_MUL_NMNIST) : W_COORD_MUL'(COORD_MUL_DVS);
      aer_shift_q     <= GEOM_NMNIST ? W_BIT_IDX'(AER_SHIFT_NMNIST) : W_BIT_IDX'(AER_SHIFT_DVS);
      thresh_shared_q <= 1'b0;
    end else if (cfg_we_i) begin
      if (thr_idx < W_CFG_ADDR'(N_NEURONS)) thresh_q[thr_idx] <= cfg_data_i[W_THRESH-1:0];  // wraps (fails) below CFG_THRESH_BASE
      if (cfg_addr_i == W_CFG_ADDR'(CFG_COORD_MUL)) coord_mul_q <= cfg_data_i[W_COORD_MUL-1:0];
      if (cfg_addr_i == W_CFG_ADDR'(CFG_AER_SHIFT)) aer_shift_q <= cfg_data_i[W_BIT_IDX-1:0];
      if (cfg_addr_i == W_CFG_ADDR'(CFG_THRESH_SHARED)) thresh_shared_q <= cfg_data_i[0];
    end
  end
  for (genvar j = 0; j < N_NEURONS; j++) begin : g_thr
    assign thresh_flat[j*W_THRESH+:W_THRESH] = thresh_q[j];
  end

  // ------------------------------------------------------------------ [A] address generator
  logic [W_AER-1:0] ev_xmask;
  logic [W_BIT_IDX-1:0] ev_p_pos;
  logic [W_COORD-1:0] ev_x, ev_y;
  logic ev_p;
  logic [W_ADDR-1:0] ev_addr;

  assign ev_xmask = (W_AER'(1) << aer_shift_q) - W_AER'(1);
  assign ev_x     = W_COORD'(ev_aer_i & ev_xmask);
  assign ev_y     = W_COORD'((ev_aer_i >> aer_shift_q) & ev_xmask);
  assign ev_p_pos = aer_shift_q << 1;
  assign ev_p     = ev_aer_i[ev_p_pos];

  addr_gen u_addr_gen (
      .x_i        (ev_x),
      .y_i        (ev_y),
      .p_i        (ev_p),
      .coord_mul_i(coord_mul_q),
      .addr_o     (ev_addr)
  );

  // ------------------------------------------------------------------ control
  logic ev_accept, boundary, sample_clr, wl_start, wl_done;
  logic [W_NEVENTS-1:0] ev_n, ev_total;
  logic [W_TSTEP-1:0] ev_tstep;
  logic sample_done;
  logic ctrl_done, spikes_done, seq_busy_unused, wl_busy_unused;
  logic cm_busy, cm_fwd, cm_wipe, cm_chk;
  logic [W_NEVENTS-1:0] cm_chk_expected;
  logic [ W_PCOUNT-1:0] active_cnt;
  logic seq_start, seq_done, acc_clr, neuron_upd, spike_load;
  logic [W_TSTEP-1:0] ts_idx;
  logic [W_STAT-1:0] sq_skipped, sq_rows, sq_allcols, sq_plane, sq_issued, zero_groups;

  snn_ctrl u_ctrl (
      .clk_i              (clk_i),
      .rst_n_i            (rst_n_i),
      .load_start_i       (load_start_i),
      .start_i            (start_i),
      .ingest_en_i        (ingest_en_i),
      .ev_valid_i         (ev_valid_i),
      .ev_ready_o         (ev_ready_o),
      .ev_accept_o        (ev_accept),
      .boundary_i         (boundary),
      .ev_n_i             (ev_n),
      .ev_tstep_i         (ev_tstep),
      .ev_total_i         (ev_total),
      .sample_done_i      (sample_done),
      .wl_start_o         (wl_start),
      .wl_done_i          (wl_done),
      .sample_clr_o       (sample_clr),
      .cm_busy_i          (cm_busy),
      .cm_fwd_i           (cm_fwd),
      .cm_wipe_o          (cm_wipe),
      .cm_chk_o           (cm_chk),
      .cm_chk_expected_o  (cm_chk_expected),
      .active_cnt_i       (active_cnt),
      .seq_start_o        (seq_start),
      .seq_done_i         (seq_done),
      .seq_rows_skipped_i (sq_skipped),
      .seq_rows_read_i    (sq_rows),
      .seq_reads_allcols_i(sq_allcols),
      .seq_reads_plane_i  (sq_plane),
      .seq_reads_issued_i (sq_issued),
      .zero_groups_i      (zero_groups),
      .acc_clr_o          (acc_clr),
      .neuron_upd_o       (neuron_upd),
      .spike_load_o       (spike_load),
      .ts_idx_o           (ts_idx),
      .spike_valid_i      (spike_valid_o),
      .state_o            (state_o),
      .weights_loaded_o   (weights_loaded_o),
      .done_o             (ctrl_done),
      .ts_events_o        (ts_events_o),
      .ts_active_o        (ts_active_o),
      .ts_rows_skipped_o  (ts_rows_skipped_o),
      .ts_rows_read_o     (ts_rows_read_o),
      .ts_reads_allcols_o (ts_reads_allcols_o),
      .ts_reads_plane_o   (ts_reads_plane_o),
      .ts_reads_issued_o  (ts_reads_issued_o),
      .ts_zero_groups_o   (ts_zero_groups_o),
      .ts_fwd_o           (ts_fwd_o),
      .ts_cycles_o        (ts_cycles_o),
      .ts_cycles_ingest_o (ts_cycles_ingest_o),
      .cyc_total_o        (cyc_total_o),
      .assert_fail_o      (assert_fail_o[0])
  );

  // ------------------------------------------------------------------ [C] event counter
  event_ctr u_event_ctr (
      .clk_i        (clk_i),
      .rst_n_i      (rst_n_i),
      .clr_i        (sample_clr),
      .cfg_n_we_i   (cfg_n_we),
      .cfg_n_i      (cfg_data_i),
      .ev_valid_i   (ev_accept),
      .boundary_o   (boundary),
      .tstep_o      (ev_tstep),
      .n_o          (ev_n),
      .ev_total_o   (ev_total),
      .sample_done_o(sample_done),
      .assert_fail_o(assert_fail_o[1])
  );

  // ------------------------------------------------------------------ [B] counters
  logic [N_INPUTS-1:0] row, active_vec, row_drv;
  logic row_nz;
  logic [W_BIT_IDX-1:0] row_sel;

  count_mem u_count_mem (
      .clk_i         (clk_i),
      .rst_n_i       (rst_n_i),
      .ev_valid_i    (ev_accept),
      .ev_addr_i     (ev_addr),
      .wipe_i        (cm_wipe),
      .row_sel_i     (row_sel),
      .row_o         (row),
      .row_nz_o      (row_nz),
      .active_o      (active_vec),
      .busy_o        (cm_busy),
      .fwd_o         (cm_fwd),
      .chk_i         (cm_chk),
      .chk_expected_i(cm_chk_expected),
      .assert_fail_o (assert_fail_o[2])
  );

  if (INSTRUMENT_EN) begin : g_instr
    // sampled only in the CHECK cycle (snn_ctrl latches it there): gating the input keeps the 512-bit tree quiet the rest of the time
    logic [N_INPUTS-1:0] active_gated;
    assign active_gated = cm_chk ? active_vec : '0;
    popcount #(
        .N(N_INPUTS)
    ) u_active (
        .bits_i (active_gated),
        .count_o(active_cnt)
    );
  end else begin : g_no_instr
    assign active_cnt = '0;
  end

  // ------------------------------------------------------------------ [D] plane sequencer
  logic rd_valid, rd_last;
  logic [W_GRP-1:0] group_idx;
  logic [W_WEIGHT-1:0] plane_mask;

  plane_seq #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS),
      .PLANE_SKIP_EN  (PLANE_SKIP_EN)
  ) u_plane_seq (
      .clk_i          (clk_i),
      .rst_n_i        (rst_n_i),
      .start_i        (seq_start),
      .row_nz_i       (row_nz),
      .row_sel_o      (row_sel),
      .rd_valid_o     (rd_valid),
      .group_idx_o    (group_idx),
      .plane_mask_o   (plane_mask),
      .rd_last_o      (rd_last),
      .done_o         (seq_done),
      .busy_o         (seq_busy_unused),
      .rows_skipped_o (sq_skipped),
      .rows_read_o    (sq_rows),
      .reads_allcols_o(sq_allcols),
      .reads_plane_o  (sq_plane),
      .reads_issued_o (sq_issued),
      .assert_fail_o  (assert_fail_o[3])
  );
  // the crossbar row drivers are energised only while a read is issued (zero otherwise)
  assign row_drv      = rd_valid ? row : '0;
  assign rd_valid_o   = rd_valid;
  assign group_idx_o  = group_idx;
  assign bitrow_idx_o = row_sel;

  // ------------------------------------------------------------------ [F] weight load + [E] behavioural crossbar
  logic wr_en;
  logic [W_MACRO_IDX-1:0] wr_macro;
  logic [W_ADDR-1:0] wr_addr;
  logic [W_WL_WORD-1:0] wr_data;
  logic m_valid;
  logic [W_M_FLAT-1:0] m_data;

  weight_load u_weight_load (
      .clk_i        (clk_i),
      .rst_n_i      (rst_n_i),
      .start_i      (wl_start),
      .wl_valid_i   (wl_valid_i),
      .wl_data_i    (wl_data_i),
      .wl_ready_o   (wl_ready_o),
      .wr_en_o      (wr_en),
      .wr_macro_o   (wr_macro),
      .wr_addr_o    (wr_addr),
      .wr_data_o    (wr_data),
      .busy_o       (wl_busy_unused),
      .done_o       (wl_done),
      .assert_fail_o(assert_fail_o[4])
  );

  cim_macro #(
      .ROWS_PER_GROUP(ROWS_PER_GROUP)
  ) u_cim_macro (
      .clk_i          (clk_i),
      .rst_n_i        (rst_n_i),
      .wr_en_i        (wr_en),
      .wr_macro_i     (wr_macro),
      .wr_addr_i      (wr_addr),
      .wr_data_i      (wr_data),
      .rd_valid_i     (rd_valid),
      .rd_bitrow_i    (row_drv),
      .rd_grp_i       (group_idx),
      .rd_plane_mask_i(plane_mask),
      .m_valid_o      (m_valid),
      .m_o            (m_data)
  );

  // ------------------------------------------------------------------ [G] shift / accumulate
  logic [W_PCOUNT-1:0] a_row;

  shift_accum #(
      .ROWS_PER_GROUP(ROWS_PER_GROUP)
  ) u_shift_accum (
      .clk_i        (clk_i),
      .rst_n_i      (rst_n_i),
      .clr_i        (acc_clr),
      .iss_valid_i  (rd_valid),
      .iss_bitrow_i (row_drv),
      .iss_grp_i    (group_idx),
      .iss_b_i      (row_sel),
      .iss_last_i   (rd_last),
      .iss_plane0_i (plane_mask[0]),
      .m_valid_i    (m_valid),
      .m_i          (m_data),
      .a_row_o      (a_row),
      .x_o          (x_o),
      .zero_groups_o(zero_groups),
      .assert_fail_o(assert_fail_o[5])
  );

  // ------------------------------------------------------------------ [H] neurons, [I] spike register
  logic [N_NEURONS-1:0] neuron_spike;
  logic upd_done;

  if_neuron_array u_neurons (
      .clk_i          (clk_i),
      .rst_n_i        (rst_n_i),
      .clr_i          (sample_clr),
      .upd_i          (neuron_upd),
      .x_i            (x_o),
      .thresh_i       (thresh_flat),
      .thresh_shared_i(thresh_shared_q),
      .spike_o        (neuron_spike),
      .upd_done_o     (upd_done),
      .v_o            (v_o),
      .assert_fail_o  (assert_fail_o[6])
  );

  spike_reg u_spike_reg (
      .clk_i        (clk_i),
      .rst_n_i      (rst_n_i),
      .clr_i        (sample_clr),
      .load_i       (spike_load),
      .spike_i      (neuron_spike),
      .tstep_i      (ts_idx),
      .spike_o      (spike_o),
      .valid_o      (spike_valid_o),
      .tstep_o      (spike_tstep_o),
      .done_o       (spikes_done),
      .assert_fail_o(assert_fail_o[7])
  );

  // the sample is finished only when the controller is back in DONE (ready for a new start) AND all T spike strobes were produced
  assign done_o = ctrl_done && spikes_done;

  // `a_row` and `upd_done` feed the analog / debug side in later phases; keep them observable in simulation
  logic unused_ok;
  assign unused_ok = &{1'b0, a_row, upd_done, rd_last, top_cfg_fail_q, seq_busy_unused, wl_busy_unused};
  assign top_cfg_fail_q = 1'b0;
endmodule
