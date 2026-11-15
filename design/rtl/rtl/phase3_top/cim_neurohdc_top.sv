// cim_neurohdc_top.sv - Phase 3 integration: the Phase 1E SNN (snn_top, UNCHANGED) -> 20-bit spike waist -> Phase 2 HDC query -> Phase 4 margin exit.
//
//   events --> [snn_top] --spike_o / spike_valid_o / spike_tstep_o--> [hdc_query] --top1, top2, idx--> [exit_ctrl] --> prediction
//                  ^ ingest_en_i = external enable AND NOT (query busy) AND NOT (exited)         <------------- the handshake
//
// Handshake (no FIFO). snn_top presents each timestep's spike vector with a one-cycle strobe and has no "ready" input; what it has is the event-intake gate ingest_en_i. The
// integration drives it low from the strobe cycle until the query stage has scored the timestep and the exit decision is taken (busy_o: strobe + 5 cycles), and for good after
// an exit. So (a) the query consumes timestep t's spikes before any event of timestep t+1 is accepted (the spike register could not change anyway before the next EMIT, which
// needs >= N_e accepted events), (b) after the exit decision NO further event is accepted - the saving is real - and (c) nothing is ever buffered: back-pressure reaches the
// event source through ev_ready_o exactly as in 1E. A FIFO would only be needed if the source could not be stalled (a live sensor); that is a system decision, not a handshake need.
//
// After an early exit snn_top is parked in its INGEST state with the intake closed (both arrays idle: no read, no accumulate). 1E's controller has no abort, so the next sample
// needs a reset of this module and a weight reload (the weights are a ReRAM image in the real part; in this model the reload is the shift-in of weight_load). The
// testbench accounts that separately; adding an abort input to snn_ctrl is the recorded follow-up (2 states) and is out of scope here (1E RTL unchanged).
import cim_neurohdc_pkg::N_NEURONS;
import cim_neurohdc_pkg::N_PARALLEL_COLS_DEFAULT;
import cim_neurohdc_pkg::N_TIMESTEPS;
import cim_neurohdc_pkg::PLANE_SKIP_EN_DEFAULT;
import cim_neurohdc_pkg::ROWS_PER_GROUP_DEFAULT;
import cim_neurohdc_pkg::CLOCK_GATING_DEFAULT;
import cim_neurohdc_pkg::ST_RUN;
import cim_neurohdc_pkg::INSTRUMENT_EN_DEFAULT;
import cim_neurohdc_pkg::OPERAND_ISOLATION_DEFAULT;
import cim_neurohdc_pkg::GEOM_NMNIST_DEFAULT;
import cim_neurohdc_pkg::N_XL;
import cim_neurohdc_pkg::W_AER;
import cim_neurohdc_pkg::W_BIT_IDX;
import cim_neurohdc_pkg::W_CFG_ADDR;
import cim_neurohdc_pkg::W_CFG_DATA;
import cim_neurohdc_pkg::W_GRP;
import cim_neurohdc_pkg::W_STAT;
import cim_neurohdc_pkg::W_TSTEP;
import cim_neurohdc_pkg::W_V;
import cim_neurohdc_pkg::W_WL_WORD;
import cim_neurohdc_pkg::W_X;
import hdc_pkg::*;
import cim_neurohdc_pkg::LOCAL_QUERY_BUSY;
import cim_neurohdc_pkg::EXIT_CLK_FREE;

module cim_neurohdc_top #(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT,
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    parameter bit PLANE_SKIP_EN = PLANE_SKIP_EN_DEFAULT,
    parameter bit INSTRUMENT_EN = INSTRUMENT_EN_DEFAULT,
    parameter bit CLOCK_GATING = CLOCK_GATING_DEFAULT,
    parameter bit OPERAND_ISOLATION = OPERAND_ISOLATION_DEFAULT,
    parameter bit GEOM_NMNIST = GEOM_NMNIST_DEFAULT,
    parameter int N_CLASSES = N_CLASSES_DEFAULT,
    parameter bit FACTORIZED = FACTORIZED_DEFAULT,
    parameter bit EARLY_EXIT_EN = EARLY_EXIT_EN_DEFAULT,
    parameter bit CHECK_UNIPOLAR = CHECK_UNIPOLAR_DEFAULT
) (
    input  logic                         clk_i,
    input  logic                         rst_n_i,
    // configuration: 0..31 -> snn_top registers, CFG_THETA / CFG_EXIT_EN -> this module
    input  logic                         cfg_we_i,
    input  logic [  W_TOP_CFG_ADDR-1:0]  cfg_addr_i,
    input  logic [      W_CFG_DATA-1:0]  cfg_data_i,
    // SNN weight image shift-in
    input  logic                         load_start_i,
    input  logic                         wl_valid_i,
    input  logic [       W_WL_WORD-1:0]  wl_data_i,
    output logic                         wl_ready_o,
    // class image
    input  logic                         cm_we_i,
    input  logic [        W_CM_SEL-1:0]  cm_sel_i,
    input  logic [         W_TADDR-1:0]  cm_addr_i,
    input  logic [N_CLASSES*N_SPK-1:0]   cm_data_i,
    // run control and the AER stream
    input  logic                         start_i,
    input  logic                         ingest_en_i,
    input  logic                         abort_i,              // one-cycle request: drop the sample in progress (or an early-exited one), keep the weights and class image
    input  logic                         ev_valid_i,
    input  logic [          W_AER-1:0]   ev_aer_i,
    output logic                         ev_ready_o,
    input  logic [          N_XL-1:0]    evx_valid_i,          // extra lanes: the next events of the stream, consumed together with lane 0 (a prefix of the lanes) or not at all
    input  logic [   N_XL*W_AER-1:0]     evx_aer_i,
    output logic [          N_XL-1:0]    evx_ready_o,
    // result
    output logic                         pred_valid_o,
    output logic [        W_CLASS-1:0]   pred_o,
    output logic [         W_TADDR-1:0]  pred_tstep_o,
    output logic                         pred_early_o,
    output logic                         inf_done_o,           // level: the inference has ended (exit or last timestep scored)
    // the spike waist and the per-timestep decision (testbench / instrumentation)
    output logic [       N_NEURONS-1:0]  spike_o,
    output logic                         spike_valid_o,
    output logic [         W_TSTEP-1:0]  spike_tstep_o,
    output logic                         dec_valid_o,
    output logic [N_CLASSES*W_SCORE-1:0] scores_o,
    output logic [        W_CLASS-1:0]   top1_idx_o,
    output logic [        W_SCORE-1:0]   top1_o,
    output logic [        W_SCORE-1:0]   top2_o,
    output logic [        W_SCORE-1:0]   margin_o,
    output logic                         exit_fire_o,
    output logic                         exited_o,
    // SNN status and instrumentation (as snn_top)
    output logic                         snn_done_o,
    output logic [                  1:0] state_o,
    output logic                         weights_loaded_o,
    output logic                         rd_valid_o,
    output logic [          W_GRP-1:0]   group_idx_o,
    output logic [      W_BIT_IDX-1:0]   bitrow_idx_o,
    output logic [  N_NEURONS*W_X-1:0]   x_o,
    output logic [  N_NEURONS*W_V-1:0]   v_o,
    output logic [         W_STAT-1:0]   ts_events_o,
    output logic [         W_STAT-1:0]   ts_active_o,
    output logic [         W_STAT-1:0]   ts_rows_skipped_o,
    output logic [         W_STAT-1:0]   ts_rows_read_o,
    output logic [         W_STAT-1:0]   ts_reads_allcols_o,
    output logic [         W_STAT-1:0]   ts_reads_plane_o,
    output logic [         W_STAT-1:0]   ts_reads_issued_o,
    output logic [         W_STAT-1:0]   ts_zero_groups_o,
    output logic [         W_STAT-1:0]   ts_fwd_o,
    output logic [         W_STAT-1:0]   ts_cycles_o,
    output logic [         W_STAT-1:0]   ts_cycles_ingest_o,
    // HDC instrumentation
    output logic [          W_AGREE-1:0] q_rows_gated_o,
    output logic [         W_STAT-1:0]   q_reads_o,
    output logic [         W_STAT-1:0]   cyc_query_o,       // cycles the SNN intake was held by the query stage / the exit
    output logic [         W_STAT-1:0]   cyc_inf_o,         // cycles from start_i to the prediction strobe
    output logic [         W_STAT-1:0]   events_ingested_o,
    output logic [                  7:0] assert_fail_o,     // snn_top's 8 sticky bits (one per 1E block)
    output logic                         hdc_assert_fail_o   // the query stage's sticky bit
);
`ifndef SYNTHESIS
  // the two packages must describe the same chip (hdc_pkg holds literals because Yosys cannot read one package from another)
  initial begin
    if (N_SPK != N_NEURONS || T_HDC != N_TIMESTEPS || CFG_THETA != (1 << W_CFG_ADDR))
      $fatal(1, "hdc_pkg (N_SPK %0d, T_HDC %0d, CFG_THETA %0d) disagrees with cim_neurohdc_pkg (N_NEURONS %0d, N_TIMESTEPS %0d, 1 << W_CFG_ADDR = %0d)", N_SPK, T_HDC, CFG_THETA, N_NEURONS, N_TIMESTEPS, 1 << W_CFG_ADDR);
  end
`endif

  // ------------------------------------------------------------------ configuration
  logic [W_THETA-1:0] theta_q;
  logic exit_en_q;
  logic snn_cfg_we;
  assign snn_cfg_we = cfg_we_i && (cfg_addr_i[W_TOP_CFG_ADDR-1:W_CFG_ADDR] == '0);
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      theta_q   <= W_THETA'(THETA_NEVER);
      exit_en_q <= 1'b1;
    end else if (cfg_we_i) begin
      if (cfg_addr_i == W_TOP_CFG_ADDR'(CFG_THETA)) theta_q <= cfg_data_i[W_THETA-1:0];
      if (cfg_addr_i == W_TOP_CFG_ADDR'(CFG_EXIT_EN)) exit_en_q <= cfg_data_i[0];
    end
  end

  // ------------------------------------------------------------------ the handshake
  logic q_busy, exited;
  logic sp_valid_w;  // declared before the busy replica that reads it
  logic sp_valid_fast;  // = sp_valid_w (snn_top: a free-clock copy on the large chip)
  logic ingest_en_snn;
  // abort is REGISTERED at the chip boundary (timing: a request arriving late in the cycle must not fan out into every reset/enable); the intake closes and the reset follows one cycle later (anything accepted in the request cycle itself is flushed by that reset; no combinational path from abort_i to the handshake outputs)
  logic abort_q;
  always_ff @(posedge clk_i) abort_q <= rst_n_i && abort_i;
  // the host's intake enable is registered at the chip boundary as well (a quasi-static control: one cycle of latency, no input-to-handshake path)
  logic ingest_en_q;
  always_ff @(posedge clk_i) ingest_en_q <= rst_n_i && ingest_en_i;
  // LOCAL_QUERY_BUSY (the large chip): the intake hold is computed here from a replica of the query stage's six valid flops instead of being wired from the query stage, whose logic
  // sits beside the class memory, far from the SNN control on a large die. The replica follows the same strobe and clears, so it equals hdc_query.busy_o in every cycle (asserted below).
  logic q_busy_hold;
  if (LOCAL_QUERY_BUSY) begin : g_local_busy
    logic r_v1, r_arr_raw, r_clr, r_va, r_v3, r_v35, r_v4, r_arr, r_clr_now;
    assign r_clr_now = start_i || abort_q;
    assign r_arr = r_arr_raw && !r_clr;
    always_ff @(posedge clk_i) begin
      r_arr_raw <= rst_n_i && r_v1;
      r_clr     <= rst_n_i && r_clr_now;
      if (!rst_n_i || r_clr_now) {r_v1, r_va, r_v3, r_v35, r_v4} <= '0;
      else begin
        r_v1  <= sp_valid_fast;
        r_va  <= AGREE_PIPE ? r_arr : 1'b0;
        r_v3  <= AGREE_PIPE ? r_va : r_arr;
        r_v35 <= r_v3;
        r_v4  <= r_v35;
      end
    end
    assign q_busy_hold = sp_valid_fast | r_v1 | r_arr | r_va | r_v3 | r_v35 | r_v4;
`ifndef SYNTHESIS
    always_ff @(posedge clk_i) if (rst_n_i && q_busy_hold !== q_busy) $display("[ASSERT FAIL] %m: local query-busy replica %0b != hdc_query busy %0b", q_busy_hold, q_busy);
`endif
  end else begin : g_wired_busy
    assign q_busy_hold = q_busy;
  end
  assign ingest_en_snn = ingest_en_q && !q_busy_hold && !exited && !abort_q;

  // clock of the HDC query stage and the exit controller: only around a spike strobe (5-cycle scoring pipeline plus a two-cycle tail), on clears and class-image writes, and whenever the
  // SNN is not in RUN. An extra enabled cycle is always safe (every register keeps its own enable).
  logic clk_hdc, hdc_clk_en;
  logic [1:0] hdc_tail_q;
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) hdc_tail_q <= '1;
    else hdc_tail_q <= {hdc_tail_q[0], sp_valid_w || q_busy || start_i || abort_q};
  end
  assign hdc_clk_en = !rst_n_i || (state_o != ST_RUN) || sp_valid_w || q_busy || (|hdc_tail_q) || abort_q || start_i || cm_we_i || cfg_we_i;
  if (CLOCK_GATING) begin : g_cg_hdc
    clk_gate u_cg_hdc (
        .clk_i (clk_i),
        .en_i  (hdc_clk_en),
        .gclk_o(clk_hdc)
    );
  end else begin : g_no_cg_hdc
    assign clk_hdc = clk_i;
  end

  // ------------------------------------------------------------------ [Phase 1E] SNN, unchanged
  logic [N_NEURONS-1:0] sp;
  logic sp_valid, snn_ev_ready;
  logic [W_TSTEP-1:0] sp_t;
  snn_top #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP),
      .N_PARALLEL_COLS(N_PARALLEL_COLS),
      .PLANE_SKIP_EN  (PLANE_SKIP_EN),
      .INSTRUMENT_EN  (INSTRUMENT_EN),
      .CLOCK_GATING   (CLOCK_GATING),
      .OPERAND_ISOLATION(OPERAND_ISOLATION),
      .GEOM_NMNIST    (GEOM_NMNIST)
  ) u_snn (
      .clk_i             (clk_i),
      .rst_n_i           (rst_n_i),
      .cfg_we_i          (snn_cfg_we),
      .cfg_addr_i        (cfg_addr_i[W_CFG_ADDR-1:0]),
      .cfg_data_i        (cfg_data_i),
      .load_start_i      (load_start_i),
      .wl_valid_i        (wl_valid_i),
      .wl_data_i         (wl_data_i),
      .wl_ready_o        (wl_ready_o),
      .start_i           (start_i),
      .ingest_en_i       (ingest_en_snn),
      .abort_i           (abort_q),
      .ev_valid_i        (ev_valid_i),
      .ev_aer_i          (ev_aer_i),
      .ev_ready_o        (snn_ev_ready),
      .evx_valid_i       (evx_valid_i),
      .evx_aer_i         (evx_aer_i),
      .evx_ready_o       (evx_ready_o),
      .spike_o           (sp),
      .spike_valid_o     (sp_valid),
      .spike_valid_fast_o(sp_valid_fast),
      .spike_tstep_o     (sp_t),
      .done_o            (snn_done_o),
      .state_o           (state_o),
      .weights_loaded_o  (weights_loaded_o),
      .rd_valid_o        (rd_valid_o),
      .group_idx_o       (group_idx_o),
      .bitrow_idx_o      (bitrow_idx_o),
      .x_o               (x_o),
      .v_o               (v_o),
      .ts_events_o       (ts_events_o),
      .ts_active_o       (ts_active_o),
      .ts_rows_skipped_o (ts_rows_skipped_o),
      .ts_rows_read_o    (ts_rows_read_o),
      .ts_reads_allcols_o(ts_reads_allcols_o),
      .ts_reads_plane_o  (ts_reads_plane_o),
      .ts_reads_issued_o (ts_reads_issued_o),
      .ts_zero_groups_o  (ts_zero_groups_o),
      .ts_fwd_o          (ts_fwd_o),
      .ts_cycles_o       (ts_cycles_o),
      .ts_cycles_ingest_o(ts_cycles_ingest_o),
      .cyc_total_o       (),
      .assert_fail_o     (assert_fail_o)
  );
  assign ev_ready_o    = snn_ev_ready;
  assign spike_o       = sp;
  assign spike_valid_o = sp_valid;
  assign sp_valid_w    = sp_valid;
  assign spike_tstep_o = sp_t;

  // ------------------------------------------------------------------ [Phase 2] HDC query
  logic [W_TADDR-1:0] dec_t;
  logic q_clr;
  assign q_clr = start_i || abort_q;
  hdc_query #(
      .N_CLASSES     (N_CLASSES),
      .FACTORIZED    (FACTORIZED),
      .CHECK_UNIPOLAR(CHECK_UNIPOLAR),
      .INSTRUMENT_EN (INSTRUMENT_EN),
      .CLOCK_GATING  (CLOCK_GATING)
  ) u_query (
      .clk_i        (clk_hdc),
      .rst_n_i      (rst_n_i),
      .clr_i        (q_clr),
      .cm_we_i      (cm_we_i),
      .cm_sel_i     (cm_sel_i),
      .cm_addr_i    (cm_addr_i),
      .cm_data_i    (cm_data_i),
      .spike_valid_i(sp_valid),
      .spike_i      (sp),
      .tstep_i      (W_TADDR'(sp_t)),
      .busy_o       (q_busy),
      .dec_valid_o  (dec_valid_o),
      .dec_tstep_o  (dec_t),
      .scores_o     (scores_o),
      .top1_idx_o   (top1_idx_o),
      .top1_o       (top1_o),
      .top2_o       (top2_o),
      .rows_gated_o (q_rows_gated_o),
      .reads_o      (q_reads_o),
      .assert_fail_o(hdc_assert_fail_o)
  );

  // ------------------------------------------------------------------ [Phase 4] margin exit
  logic fin;
  exit_ctrl #(
      .EARLY_EXIT_EN(EARLY_EXIT_EN),
      .N_TS         (N_TIMESTEPS)
  ) u_exit (
      .clk_i       (EXIT_CLK_FREE ? clk_i : clk_hdc),
      .rst_n_i     (rst_n_i),
      .clr_i       (q_clr),
      .dec_valid_i (dec_valid_o),
      .dec_tstep_i (dec_t),
      .top1_idx_i  (top1_idx_o),
      .top1_i      (top1_o),
      .top2_i      (top2_o),
      .theta_i     (theta_q),
      .exit_en_i   (exit_en_q),
      .fire_o      (exit_fire_o),
      .margin_o    (margin_o),
      .exited_q_o  (exited),
      .pred_valid_o(pred_valid_o),
      .pred_o      (pred_o),
      .pred_tstep_o(pred_tstep_o),
      .pred_early_o(pred_early_o),
      .finished_o  (fin)
  );
  assign exited_o   = exited;
  assign inf_done_o = fin;

  // ------------------------------------------------------------------ cycle accounting
  logic [W_STAT-1:0] cq_q, ci_q, ev_q;
  logic running;
  if (INSTRUMENT_EN) begin : g_cyc
    always_ff @(posedge clk_i) begin
      if (!rst_n_i) begin
        cq_q    <= '0;
        ci_q    <= '0;
        ev_q    <= '0;
        running <= 1'b0;
      end else begin
        if (start_i) begin
          cq_q    <= '0;
          ci_q    <= '0;
          ev_q    <= '0;
          running <= 1'b1;
        end else if (abort_q) begin
          running <= 1'b0;
        end else if (running) begin
          if (!fin) ci_q <= ci_q + W_STAT'(1);
          if (q_busy && !fin) cq_q <= cq_q + W_STAT'(1);
          if (ev_valid_i && snn_ev_ready) ev_q <= ev_q + W_STAT'(1) + W_STAT'($countones(evx_ready_o));
          if (pred_valid_o) running <= 1'b0;
        end
      end
    end
  end else begin : g_no_cyc
    assign cq_q    = '0;
    assign ci_q    = '0;
    assign ev_q    = '0;
    assign running = 1'b0;
    logic unused_cyc;
    assign unused_cyc = &{1'b0, running, cq_q[0], ci_q[0], ev_q[0]};
  end
  assign cyc_query_o       = cq_q;
  assign cyc_inf_o         = ci_q;
  assign events_ingested_o = ev_q;
  // the last timestep's query cycles are part of the inference (the prediction strobe follows the decision); q_busy is low after fin, which is set at the decision cycle's end

  logic unused_ok;
  assign unused_ok = &{1'b0, sp_t[0]};
endmodule
