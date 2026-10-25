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
  localparam int W_M = $clog2(ROWS_PER_GROUP + 1);  // bits of one match count: 0..g
  logic cm_busy, cm_fwd, cm_wipe;
  logic cm_ready;                       // declared before the controller instance that reads it (Icarus does not accept use before declaration)
  logic [W_STAT-1:0] sq_active;
  logic [W_NEVENTS-1:0] cm_chk_expected;
  logic seq_start, seq_done, acc_clr, neuron_upd, spike_load;
  logic [W_TSTEP-1:0] ts_idx;
  logic [W_STAT-1:0] sq_skipped, sq_rows, sq_allcols, sq_plane, sq_issued, zero_groups;

  snn_ctrl #(
      .INSTRUMENT_EN(INSTRUMENT_EN)
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
      .cm_chk_expected_o  (cm_chk_expected),
      .cm_ready_i         (cm_ready),
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

  // ------------------------------------------------------------------ [B] counters (SRAM macro), [D] scan sequencer
  logic [W_COUNT-1:0] scan_q;
  logic scan_qv, scan_re;
  logic [W_ADDR-1:0] scan_addr;

  count_mem u_count_mem (
      .clk_i         (clk_i),
      .rst_n_i       (rst_n_i),
      .ev_valid_i    (ev_accept),
      .ev_addr_i     (ev_addr),
      .wipe_i        (cm_wipe),
      .flush_i       (abort_i),
      .scan_re_i     (scan_re),
      .scan_addr_i   (scan_addr),
      .q_o           (scan_q),
      .scan_qv_o     (scan_qv),
      .busy_o        (cm_busy),
      .ready_o       (cm_ready),
      .fwd_o         (cm_fwd),
      .chk_i         (seq_done),
      .chk_expected_i(cm_chk_expected),
      .assert_fail_o (assert_fail_o[2])
  );

  logic rd_valid;
  logic [ROWS_PER_GROUP-1:0] rd_bits;
  logic [W_GRP-1:0] group_idx;
  logic [$clog2(N_WCOLS / N_PARALLEL_COLS > 1 ? N_WCOLS / N_PARALLEL_COLS : 2)-1:0] rd_pass;
  logic [W_BIT_IDX-1:0] row_sel;

  plane_seq #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS),
      .INSTRUMENT_EN  (INSTRUMENT_EN)
  ) u_plane_seq (
      .clk_i          (clk_i),
      .rst_n_i        (rst_n_i),
      .start_i        (seq_start),
      .abort_i        (abort_i),
      .scan_re_o      (scan_re),
      .scan_addr_o    (scan_addr),
      .scan_q_i       (scan_q),
      .scan_qv_i      (scan_qv),
      .rd_valid_o     (rd_valid),
      .rd_bits_o      (rd_bits),
      .group_idx_o    (group_idx),
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
  assign group_idx_o  = group_idx;
  assign bitrow_idx_o = row_sel;

  // ------------------------------------------------------------------ [F] weight load + [E] behavioural crossbar
  logic wr_en;
  logic [W_MACRO_IDX-1:0] wr_macro;
  logic [W_ADDR-1:0] wr_addr;
  logic [W_WL_WORD-1:0] wr_data;
  logic m_valid;
  logic [N_PARALLEL_COLS*W_M-1:0] m_data;

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
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_cim_macro (
      .clk_i          (clk_i),
      .rst_n_i        (rst_n_i),
      .wr_en_i        (wr_en),
      .wr_macro_i     (wr_macro),
      .wr_addr_i      (wr_addr),
      .wr_data_i      (wr_data),
      .rd_valid_i     (rd_valid),
      .rd_bits_i      (rd_bits),
      .rd_grp_i       (group_idx[$clog2(N_INPUTS / ROWS_PER_GROUP)-1:0]),
      .rd_pass_i      (rd_pass),
      .m_valid_o      (m_valid),
      .m_o            (m_data)
  );

  // ------------------------------------------------------------------ [G] shift / accumulate
  shift_accum #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS)
  ) u_shift_accum (
      .clk_i        (clk_i),
      .rst_n_i      (rst_n_i),
      .clr_i        (acc_clr || abort_i),
      .iss_valid_i  (rd_valid),
      .iss_b_i      (row_sel),
      .iss_pass_i   (rd_pass),
      .iss_bits_i   (rd_bits),
      .m_valid_i    (m_valid),
      .m_i          (m_data),
      .x_o          (x_o),
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

  logic unused_ok;
  assign unused_ok = &{1'b0, upd_done, top_cfg_fail_q, seq_busy_unused, wl_busy_unused, PLANE_SKIP_EN, CLOCK_GATING, OPERAND_ISOLATION};
  assign top_cfg_fail_q = 1'b0;
endmodule
