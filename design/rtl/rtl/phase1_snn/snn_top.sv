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
import cim_neurohdc_pkg::CLOCK_GATING_DEFAULT;
import cim_neurohdc_pkg::INSTRUMENT_EN_DEFAULT;
import cim_neurohdc_pkg::OPERAND_ISOLATION_DEFAULT;
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
import cim_neurohdc_pkg::N_DIRTY_GS;
import cim_neurohdc_pkg::N_LANES;
import cim_neurohdc_pkg::N_XL;
import cim_neurohdc_pkg::ST_RUN;
import cim_neurohdc_pkg::S_ROWS;
import cim_neurohdc_pkg::W_BAND;
import cim_neurohdc_pkg::W_RB;
import cim_neurohdc_pkg::W_BANK_ADDR;
import cim_neurohdc_pkg::W_LANES;
import cim_neurohdc_pkg::W_GRP;
import cim_neurohdc_pkg::W_MACRO_IDX;
import cim_neurohdc_pkg::N_WCOLS;
import cim_neurohdc_pkg::W_COUNT;
import cim_neurohdc_pkg::W_NEVENTS;
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
    parameter bit PLANE_SKIP_EN = PLANE_SKIP_EN_DEFAULT,  // reserved: the scan sequencer never reads an empty (bit-plane, group)
    parameter bit INSTRUMENT_EN = INSTRUMENT_EN_DEFAULT,
    parameter bit CLOCK_GATING = CLOCK_GATING_DEFAULT,
    parameter bit OPERAND_ISOLATION = OPERAND_ISOLATION_DEFAULT,
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
    input  logic                     abort_i,         // one-cycle request: RUN -> IDLE from any run state, per-sample state cleared, weights kept
    // AER event stream (valid/ready)
    input  logic                     ev_valid_i,
    input  logic [        W_AER-1:0] ev_aer_i,
    output logic                     ev_ready_o,
    // extra lanes: the next events of the stream, consumed in the same cycle as lane 0 (a prefix: lane k only if lanes below it are) or not at all
    input  logic [          N_XL-1:0] evx_valid_i,
    input  logic [   N_XL*W_AER-1:0] evx_aer_i,
    output logic [          N_XL-1:0] evx_ready_o,
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
  // ------------------------------------------------------------------ clock domains (module-level gating: the always-on trunk only feeds the ingest logic and the controller)
  logic clk_scan, clk_cfg, scan_clk_en, cfg_clk_en;
  if (CLOCK_GATING) begin : g_cg
    clk_gate u_cg_scan (
        .clk_i (clk_i),
        .en_i  (scan_clk_en),
        .gclk_o(clk_scan)
    );
    clk_gate u_cg_cfg (
        .clk_i (clk_i),
        .en_i  (cfg_clk_en),
        .gclk_o(clk_cfg)
    );
  end else begin : g_no_cg
    assign clk_scan = clk_i;
    assign clk_cfg  = clk_i;
  end

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

  always_ff @(posedge clk_cfg) begin
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
  logic geom_dvs;  // the configured AER field width selects the geometry (128x128 or 34x34)
  logic [W_ADDR-1:0] ev_addr;
  assign geom_dvs = (aer_shift_q == W_BIT_IDX'(AER_SHIFT_DVS));

  addr_gen u_addr_gen (
      .aer_i     (ev_aer_i),
      .geom_dvs_i(geom_dvs),
      .addr_o    (ev_addr)
  );

  // extra lanes: one address generator each
  logic [N_LANES*W_ADDR-1:0] lane_addr;
  assign lane_addr[0+:W_ADDR] = ev_addr;
  for (genvar k = 0; k < N_XL; k++) begin : g_xl
    addr_gen u_addr_gen (
        .aer_i     (evx_aer_i[k*W_AER+:W_AER]),
        .geom_dvs_i(geom_dvs),
        .addr_o    (lane_addr[(k+1)*W_ADDR+:W_ADDR])
    );
  end

  // ------------------------------------------------------------------ control
  logic ev_accept, sample_clr, wl_start, wl_done;
  logic [N_LANES-1:0] acc_vec, bnd_pre;
  logic cm_in_ready, dirty_clr, dirty_clr_set;
  assign cm_in_ready = 1'b1;  // count_mem takes N_LANES events every cycle (lane-private counters)
  logic [2*(N_INPUTS/ROWS_PER_GROUP/N_DIRTY_GS)-1:0] dirty;
  logic [W_LANES-1:0] n_acc;
  logic bnd_acc;
  logic [W_NEVENTS-1:0] ev_n, ev_total;
  logic [W_TSTEP-1:0] ev_tstep;
  logic sample_done;
  logic ctrl_done, spikes_done, seq_busy_unused, wl_busy_unused;
  localparam int W_M = $clog2(ROWS_PER_GROUP + 1);  // bits of one match count: 0..g
  logic cm_busy, cm_fwd, cm_wipe;
  logic ing_sel, scan_set;
  logic ctr_ready;
  logic cm_ready;                       // declared before the controller instance that reads it (Icarus does not accept use before declaration)
  logic [W_STAT-1:0] sq_active;
  logic [W_NEVENTS-1:0] cm_chk_expected;
  logic seq_start, seq_done, acc_clr, neuron_upd, spike_load;
  logic [W_TSTEP-1:0] ts_idx;
  logic [W_STAT-1:0] sq_skipped, sq_rows, sq_allcols, sq_plane, sq_issued, zero_groups;

  snn_ctrl #(
      .INSTRUMENT_EN(INSTRUMENT_EN),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_ctrl (
      .clk_i              (clk_i),
      .rst_n_i            (rst_n_i),
      .load_start_i       (load_start_i),
      .start_i            (start_i),
      .ingest_en_i        (ingest_en_i),
      .abort_i            (abort_i),
      .ev_valid_i         (ev_valid_i),
      .ev_ready_o         (ev_ready_o),
      .ev_accept_o        (ev_accept),
      .n_acc_i            (n_acc),
      .bnd_acc_i          (bnd_acc),
      .ev_n_i             (ev_n),
      .ev_tstep_i         (ev_tstep),
      .ev_total_i         (ev_total),
      .sample_done_i      (sample_done),
      .wl_start_o         (wl_start),
      .wl_done_i          (wl_done),
      .sample_clr_o       (sample_clr),
      .cm_busy_i          (cm_busy),
      .cm_fwd_i           (cm_fwd),
      .scan_clk_en_o      (scan_clk_en),
      .cfg_clk_en_o       (cfg_clk_en),
      .cm_wipe_o          (cm_wipe),
      .ing_sel_o          (ing_sel),
      .cm_chk_expected_o  (cm_chk_expected),
      .cm_ready_i         (cm_ready && cm_in_ready && ctr_ready),
      .seq_active_i       (sq_active),
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

  // lane k > 0 is consumed together with the lanes below it, never behind a timestep boundary, and only if the count memory has room for it
  always_comb begin
    acc_vec[0] = ev_accept;
    for (int k = 1; k < N_LANES; k++) acc_vec[k] = acc_vec[k-1] && evx_valid_i[k-1] && !bnd_pre[k-1];
    n_acc = '0;
    for (int k = 0; k < N_LANES; k++) n_acc = n_acc + W_LANES'(acc_vec[k]);
  end
  assign evx_ready_o = acc_vec[N_LANES-1:1];

  // ------------------------------------------------------------------ [C] event counter
  event_ctr u_event_ctr (
      .clk_i        (clk_i),
      .rst_n_i      (rst_n_i),
      .clr_i        (sample_clr),
      .cfg_n_we_i   (cfg_n_we),
      .cfg_n_i      (cfg_data_i),
      .n_acc_i      (n_acc),
      .bnd_pre_o    (bnd_pre),
      .bnd_acc_o    (bnd_acc),
      .ready_o      (ctr_ready),
      .tstep_o      (ev_tstep),
      .n_o          (ev_n),
      .ev_total_o   (ev_total),
      .sample_done_o(sample_done),
      .assert_fail_o(assert_fail_o[1])
  );

  // ------------------------------------------------------------------ [B] counters (SRAM macro), [D] scan sequencer
  logic [ROWS_PER_GROUP*W_COUNT-1:0] scan_q;
  logic scan_qv, scan_re;
  logic [W_GRP-1:0] scan_grp;

  count_mem u_count_mem (
      .clk_i         (clk_i),
      .rst_n_i       (rst_n_i),
      .ev_valid_i    (acc_vec),
      .ev_addr_i     (lane_addr),
      .wipe_i        (cm_wipe),
      .flush_i       (abort_i),
      .ing_sel_i     (ing_sel),
      .scan_set_i    (scan_set),
      .scan_re_i     (scan_re),
      .scan_clr_i    (scan_clr),
      .scan_grp_i    (scan_grp[W_BANK_ADDR-1:0]),
      .q_o           (scan_q),
      .scan_qv_o     (scan_qv),
      .busy_o        (cm_busy),
      .ready_o       (cm_ready),
      .dirty_o       (dirty),
      .dirty_clr_i   (dirty_clr),
      .dirty_clr_set_i(dirty_clr_set),
      .fwd_o         (cm_fwd),
      .chk_i         (seq_done),
      .chk_expected_i(cm_chk_expected),
      .assert_fail_o (assert_fail_o[2])
  );

  logic rd_valid, scan_clr;
  logic [S_ROWS-1:0] rd_rv;
  logic [S_ROWS*W_RB-1:0] rd_rows;
  logic [W_BAND-1:0] rd_band;
  logic [$clog2(N_WCOLS / N_PARALLEL_COLS > 1 ? N_WCOLS / N_PARALLEL_COLS : 2)-1:0] rd_pass;
  logic [W_BIT_IDX-1:0] row_sel;

  plane_seq #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS),
      .INSTRUMENT_EN  (INSTRUMENT_EN)
  ) u_plane_seq (
      .clk_i          (clk_scan),
      .rst_n_i        (rst_n_i),
      .start_i        (seq_start),
      .abort_i        (abort_i),
      .ing_sel_i      (ing_sel),
      .scan_set_o     (scan_set),
      .dirty_i        (dirty),
      .dirty_clr_o    (dirty_clr),
      .dirty_clr_set_o(dirty_clr_set),
      .scan_re_o      (scan_re),
      .scan_clr_o     (scan_clr),
      .scan_grp_o     (scan_grp),
      .scan_q_i       (scan_q),
      .scan_qv_i      (scan_qv),
      .rd_valid_o     (rd_valid),
      .rd_rv_o        (rd_rv),
      .rd_rows_o      (rd_rows),
      .rd_band_o      (rd_band),
      .row_sel_o      (row_sel),
      .pass_o         (rd_pass),
      .done_o         (seq_done),
      .busy_o         (seq_busy_unused),
      .active_o       (sq_active),
      .rows_skipped_o (sq_skipped),
      .rows_read_o    (sq_rows),
      .reads_allcols_o(sq_allcols),
      .reads_plane_o  (sq_plane),
      .reads_issued_o (sq_issued),
      .zero_groups_o  (zero_groups),
      .assert_fail_o  (assert_fail_o[3])
  );
  assign rd_valid_o   = rd_valid;
  assign group_idx_o  = W_GRP'(rd_band);
  assign bitrow_idx_o = row_sel;

  // ------------------------------------------------------------------ [F] weight load + [E] behavioural crossbar
  logic wr_en;
  logic [W_MACRO_IDX-1:0] wr_macro;
  logic [W_ADDR-1:0] wr_addr;
  logic [W_WL_WORD-1:0] wr_data;
  logic m_valid;
  logic acc_valid;
  logic [(N_PARALLEL_COLS/W_WEIGHT)*W_V-1:0] acc_d;
  logic [$clog2(N_WCOLS / N_PARALLEL_COLS > 1 ? N_WCOLS / N_PARALLEL_COLS : 2)-1:0] acc_pass;
  logic [N_PARALLEL_COLS*W_M-1:0] m_data;

  weight_load u_weight_load (
      .clk_i        (clk_cfg),
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
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_cim_macro (
      .clk_i          (clk_scan),
      .rst_n_i        (rst_n_i),
      .wr_en_i        (wr_en),
      .wr_macro_i     (wr_macro),
      .wr_addr_i      (wr_addr),
      .wr_data_i      (wr_data),
      .rd_valid_i     (rd_valid),
      .rd_rv_i        (rd_rv),
      .rd_rows_i      (rd_rows),
      .rd_band_i      (rd_band),
      .rd_pass_i      (rd_pass),
      .m_valid_o      (m_valid),
      .m_o            (m_data)
  );

  // ------------------------------------------------------------------ [G] shift / accumulate
  shift_accum #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_shift_accum (
      .clk_i        (clk_scan),
      .rst_n_i      (rst_n_i),
      .iss_valid_i  (rd_valid),
      .iss_b_i      (row_sel),
      .iss_pass_i   (rd_pass),
      .iss_bits_i   (rd_rv),
      .m_valid_i    (m_valid),
      .m_i          (m_data),
      .d_valid_o    (acc_valid),
      .d_pass_o     (acc_pass),
      .d_o          (acc_d),
      .assert_fail_o(assert_fail_o[5])
  );

  // ------------------------------------------------------------------ [H] neurons, [I] spike register
  logic [N_NEURONS-1:0] neuron_spike;
  logic upd_done;

  if_neuron_array #(
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_neurons (
      .clk_i          (clk_scan),
      .rst_n_i        (rst_n_i),
      .clr_i          (sample_clr),
      .acc_i          (acc_valid),
      .acc_pass_i     (acc_pass),
      .d_i            (acc_d),
      .upd_i          (neuron_upd),
      .thresh_i       (thresh_flat),
      .thresh_shared_i(thresh_shared_q),
      .spike_o        (neuron_spike),
      .upd_done_o     (upd_done),
      .v_o            (v_o),
      .x_o            (x_o),
      .assert_fail_o  (assert_fail_o[6])
  );

  spike_reg u_spike_reg (
      .clk_i        (clk_scan),
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

  logic unused_ok;
  assign unused_ok = &{1'b0, coord_mul_q, upd_done, top_cfg_fail_q, seq_busy_unused, wl_busy_unused, PLANE_SKIP_EN, OPERAND_ISOLATION};
`ifndef SYNTHESIS
  always_ff @(posedge clk_i) begin
    if (rst_n_i && state_o == ST_RUN && !((aer_shift_q == W_BIT_IDX'(AER_SHIFT_DVS) && coord_mul_q == W_COORD_MUL'(COORD_MUL_DVS)) || (aer_shift_q == W_BIT_IDX'(AER_SHIFT_NMNIST) && coord_mul_q == W_COORD_MUL'(COORD_MUL_NMNIST))))
      $display("[ASSERT FAIL] %m: geometry (field width %0d, multiplier %0d) is not one of the two supported ones (7 / 128, 6 / 482)", aer_shift_q, coord_mul_q);
  end
`endif
  assign top_cfg_fail_q = 1'b0;
endmodule
