// snn_ctrl.sv - block I (control). Top-level FSM  IDLE -> LOAD -> RUN -> DONE, and inside RUN the per-timestep loop:
//
//   INGEST  accept events until the event counter flags the last event of the timestep
//   DRAIN   let the count_mem read-modify-write pipeline empty
//   CHECK   assertion strobe (counter sum), clear the accumulator, start the crossbar reads
//   MVM     plane_seq walks bit-rows / groups; shift_accum builds X
//   UPDATE  all 20 neurons update in one cycle
//   EMIT    capture S(t) in spike_reg (valid strobe the next cycle)
//   WIPE    bulk-clear the counters, next timestep
//
// EVENTS ARRIVING MID-READ ARE STALLED, NOT BUFFERED: ev_ready_o is high only in INGEST (and only while ingest_en_i is high), so a
// source holding `valid` is back-pressured and no event can be lost - the assertions check that every event is counted exactly once
// and that the counters sum to the timestep's event count at every boundary.
// ingest_en_i gates event intake (nothing drives it low in 1E; Phase 4 early exit will).
//
// abort_i (digital-energy pass): a one-cycle request that returns RUN -> IDLE from ANY run sub-state. The weights, the configuration and `loaded_q` are kept (a real part keeps its
// weights in ReRAM); the per-sample state (counters, sequencer, accumulator, query stage) is cleared by the blocks that see the same strobe, and a new start_i begins a clean sample.
// It is how an early exit hands the datapath over without a reset and a 2,560-cycle weight reload. Ignored outside RUN.
//
// INSTRUMENT_EN = 0 removes every debug counter (cycle / event / forward / per-timestep latches) from the netlist: the ts_*_o outputs are then constant zero.






import cim_neurohdc_pkg::DRAIN_CYCLES;
import cim_neurohdc_pkg::INSTRUMENT_EN_DEFAULT;
import cim_neurohdc_pkg::N_TIMESTEPS;
import cim_neurohdc_pkg::ST_DONE;
import cim_neurohdc_pkg::ST_IDLE;
import cim_neurohdc_pkg::ST_LOAD;
import cim_neurohdc_pkg::ST_RUN;
import cim_neurohdc_pkg::W_NEVENTS;
import cim_neurohdc_pkg::W_STAT;
import cim_neurohdc_pkg::W_TOP_STATE;
import cim_neurohdc_pkg::W_TSTEP;

module snn_ctrl #(
    parameter bit INSTRUMENT_EN = INSTRUMENT_EN_DEFAULT
) (
    input  logic                 clk_i,
    input  logic                 rst_n_i,
    // host
    input  logic                 load_start_i,
    input  logic                 start_i,
    input  logic                 ingest_en_i,
    input  logic                 abort_i,
    // event handshake
    input  logic                 ev_valid_i,
    output logic                 ev_ready_o,
    output logic                 ev_accept_o,
    // event_ctr
    input  logic                 boundary_i,
    input  logic [W_NEVENTS-1:0] ev_n_i,
    input  logic [  W_TSTEP-1:0] ev_tstep_i,
    input  logic [W_NEVENTS-1:0] ev_total_i,
    input  logic                 sample_done_i,
    // weight_load
    output logic                 wl_start_o,
    input  logic                 wl_done_i,
    // sample start pulse (clears event_ctr, neurons, spike_reg)
    output logic                 sample_clr_o,
    // count_mem
    input  logic                 cm_busy_i,
    input  logic                 cm_fwd_i,
    output logic                 cm_wipe_o,
    output logic [W_NEVENTS-1:0] cm_chk_expected_o,
    input  logic                 cm_ready_i,    // the count memory is not sweeping (after reset / abort)
    input  logic [   W_STAT-1:0] seq_active_i,   // counters != 0 this timestep (scan)
    // plane_seq / shift_accum
    output logic                 seq_start_o,
    input  logic                 seq_done_i,
    input  logic [   W_STAT-1:0] seq_rows_skipped_i,
    input  logic [   W_STAT-1:0] seq_rows_read_i,
    input  logic [   W_STAT-1:0] seq_reads_allcols_i,
    input  logic [   W_STAT-1:0] seq_reads_plane_i,
    input  logic [   W_STAT-1:0] seq_reads_issued_i,
    input  logic [   W_STAT-1:0] zero_groups_i,
    output logic                 acc_clr_o,
    // neurons / spike_reg
    output logic                 neuron_upd_o,
    output logic                 spike_load_o,
    output logic [  W_TSTEP-1:0] ts_idx_o,
    input  logic                 spike_valid_i,
    // status
    output logic [          1:0] state_o,
    output logic                 weights_loaded_o,
    output logic                 done_o,
    // per-timestep instrumentation, held from the spike strobe until the next one
    output logic [   W_STAT-1:0] ts_events_o,
    output logic [   W_STAT-1:0] ts_active_o,
    output logic [   W_STAT-1:0] ts_rows_skipped_o,
    output logic [   W_STAT-1:0] ts_rows_read_o,
    output logic [   W_STAT-1:0] ts_reads_allcols_o,
    output logic [   W_STAT-1:0] ts_reads_plane_o,
    output logic [   W_STAT-1:0] ts_reads_issued_o,
    output logic [   W_STAT-1:0] ts_zero_groups_o,
    output logic [   W_STAT-1:0] ts_fwd_o,
    output logic [   W_STAT-1:0] ts_cycles_o,
    output logic [   W_STAT-1:0] ts_cycles_ingest_o,
    output logic [   W_STAT-1:0] cyc_total_o,
    output logic                 assert_fail_o
);
  localparam int POST_DONE_WAIT = DRAIN_CYCLES - 2;  // cycles between plane_seq's done pulse and X being final (0 for the 1+1 pipeline)
  localparam logic [W_STAT-1:0] ONE = W_STAT'(1);

  typedef enum logic [3:0] {
    R_INGEST,
    R_DRAIN,
    R_CHECK,
    R_MVM,
    R_MVM_WAIT,
    R_UPDATE,
    R_EMIT,
    R_WIPE
  } run_state_e;

  logic       [W_TOP_STATE-1:0] top_q;
  run_state_e                   run_q;
  logic                         loaded_q;
  logic       [    W_TSTEP-1:0] ts_idx_q;
  logic       [     W_STAT-1:0] ev_in_ts_q;  // events of this timestep: the assertions' reference count (only the instrumentation outputs make it visible in a netlist)
  logic       [     W_STAT-1:0] wait_q;

  logic in_run;
  logic can_start;
  logic boundary_acc;
  logic abort_run;
  logic run_start;

  assign in_run            = (top_q == ST_RUN);
  assign can_start         = (top_q == ST_IDLE || top_q == ST_DONE);
  assign abort_run         = abort_i && in_run;
  assign sample_clr_o      = start_i && can_start && loaded_q;
  assign run_start         = can_start && !load_start_i && start_i && loaded_q;
  assign wl_start_o        = load_start_i && can_start;
  assign ev_ready_o        = in_run && (run_q == R_INGEST) && ingest_en_i && !abort_i && cm_ready_i;
  assign ev_accept_o       = ev_valid_i && ev_ready_o;
  assign boundary_acc      = ev_accept_o && boundary_i;

  assign cm_wipe_o         = in_run && (run_q == R_WIPE);
  assign cm_chk_expected_o = W_NEVENTS'(ev_in_ts_q);
  assign seq_start_o       = in_run && (run_q == R_CHECK);
  assign acc_clr_o         = in_run && (run_q == R_CHECK);
  assign neuron_upd_o      = in_run && (run_q == R_UPDATE) && !abort_i;
  assign spike_load_o      = in_run && (run_q == R_EMIT) && !abort_i;
  assign ts_idx_o          = ts_idx_q;
  assign state_o           = top_q;
  assign weights_loaded_o  = loaded_q;
  assign done_o            = (top_q == ST_DONE);

  // ------------------------------------------------------------------ control state (always built)
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      top_q      <= ST_IDLE;
      run_q      <= R_INGEST;
      loaded_q   <= 1'b0;
      ts_idx_q   <= '0;
      ev_in_ts_q <= '0;
      wait_q     <= '0;
    end else if (abort_run) begin
      top_q <= ST_IDLE;
      run_q <= R_INGEST;
    end else begin
      // ------------------------------------------------ top-level state
      unique case (top_q)
        ST_IDLE, ST_DONE: begin
          if (load_start_i) top_q <= ST_LOAD;
          else if (start_i && loaded_q) begin
            top_q      <= ST_RUN;
            run_q      <= R_INGEST;
            ts_idx_q   <= '0;
            ev_in_ts_q <= '0;
          end
        end
        ST_LOAD: begin
          if (wl_done_i) begin
            top_q    <= ST_IDLE;
            loaded_q <= 1'b1;
          end
        end
        ST_RUN: begin
          if (ev_accept_o) ev_in_ts_q <= ev_in_ts_q + ONE;
          unique case (run_q)
            R_INGEST: if (boundary_acc) run_q <= R_DRAIN;
            R_DRAIN:  if (!cm_busy_i) run_q <= R_CHECK;
            R_CHECK:  run_q <= R_MVM;
            R_MVM: begin
              if (seq_done_i) begin
                if (POST_DONE_WAIT <= 0) run_q <= R_UPDATE;
                else begin
                  run_q  <= R_MVM_WAIT;
                  wait_q <= W_STAT'(POST_DONE_WAIT);
                end
              end
            end
            R_MVM_WAIT: begin
              wait_q <= wait_q - ONE;
              if (wait_q == ONE) run_q <= R_UPDATE;
            end
            R_UPDATE: run_q <= R_EMIT;
            R_EMIT:   run_q <= R_WIPE;
            R_WIPE: begin
              ts_idx_q   <= ts_idx_q + W_TSTEP'(1);
              ev_in_ts_q <= '0;
              if (ts_idx_q == W_TSTEP'(N_TIMESTEPS - 1)) top_q <= ST_DONE;
              run_q <= R_INGEST;
            end
            default:  run_q <= R_INGEST;
          endcase
        end
        default: top_q <= ST_IDLE;
      endcase
    end
  end

  // ------------------------------------------------------------------ instrumentation (debug state: INSTRUMENT_EN = 0 builds none of it)
  if (INSTRUMENT_EN) begin : g_instr
    logic [W_STAT-1:0] fwd_q, cyc_ts_q, cyc_ing_q, cyc_total_q;
    logic [W_STAT-1:0] l_events_q, l_active_q, l_skipped_q, l_rows_q, l_allcols_q, l_plane_q, l_issued_q, l_zero_q, l_fwd_q, l_cyc_q, l_cyc_ing_q;

    always_ff @(posedge clk_i) begin
      if (!rst_n_i) begin
        fwd_q       <= '0;
        cyc_ts_q    <= '0;
        cyc_ing_q   <= '0;
        cyc_total_q <= '0;
        l_events_q  <= '0;
        l_active_q  <= '0;
        l_skipped_q <= '0;
        l_rows_q    <= '0;
        l_allcols_q <= '0;
        l_plane_q   <= '0;
        l_issued_q  <= '0;
        l_zero_q    <= '0;
        l_fwd_q     <= '0;
        l_cyc_q     <= '0;
        l_cyc_ing_q <= '0;
      end else if (!abort_run) begin
        if (run_start) begin
          fwd_q       <= '0;
          cyc_ts_q    <= '0;
          cyc_ing_q   <= '0;
          cyc_total_q <= '0;
        end
        if (in_run) begin
          cyc_ts_q    <= cyc_ts_q + ONE;
          cyc_total_q <= cyc_total_q + ONE;
          if (run_q == R_INGEST) cyc_ing_q <= cyc_ing_q + ONE;
          if (cm_fwd_i) fwd_q <= fwd_q + ONE;
          if (run_q == R_EMIT) begin
            l_events_q  <= ev_in_ts_q;
            l_active_q  <= seq_active_i;
            l_skipped_q <= seq_rows_skipped_i;
            l_rows_q    <= seq_rows_read_i;
            l_allcols_q <= seq_reads_allcols_i;
            l_plane_q   <= seq_reads_plane_i;
            l_issued_q  <= seq_reads_issued_i;
            l_zero_q    <= zero_groups_i;
            l_fwd_q     <= fwd_q;
            l_cyc_q     <= cyc_ts_q + ONE;
            l_cyc_ing_q <= cyc_ing_q;
          end
          if (run_q == R_WIPE) begin
            fwd_q     <= '0;
            cyc_ts_q  <= '0;
            cyc_ing_q <= '0;
          end
        end
      end
    end

    assign ts_events_o        = l_events_q;
    assign ts_active_o        = l_active_q;
    assign ts_rows_skipped_o  = l_skipped_q;
    assign ts_rows_read_o     = l_rows_q;
    assign ts_reads_allcols_o = l_allcols_q;
    assign ts_reads_plane_o   = l_plane_q;
    assign ts_reads_issued_o  = l_issued_q;
    assign ts_zero_groups_o   = l_zero_q;
    assign ts_fwd_o           = l_fwd_q;
    assign ts_cycles_o        = l_cyc_q;
    assign ts_cycles_ingest_o = l_cyc_ing_q;
    assign cyc_total_o        = cyc_total_q;
  end else begin : g_no_instr
    assign ts_events_o        = '0;
    assign ts_active_o        = '0;
    assign ts_rows_skipped_o  = '0;
    assign ts_rows_read_o     = '0;
    assign ts_reads_allcols_o = '0;
    assign ts_reads_plane_o   = '0;
    assign ts_reads_issued_o  = '0;
    assign ts_zero_groups_o   = '0;
    assign ts_fwd_o           = '0;
    assign ts_cycles_o        = '0;
    assign ts_cycles_ingest_o = '0;
    assign cyc_total_o        = '0;
    logic unused_instr;
    assign unused_instr = &{1'b0, run_start, cm_fwd_i, seq_active_i, seq_rows_skipped_i, seq_rows_read_i, seq_reads_allcols_i, seq_reads_plane_i, seq_reads_issued_i, zero_groups_i};
  end

  // ------------------------------------------------------------------ assertions (simulation only; never disabled)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  // exact event count of timestep t of an n-event sample: ceil((t+1)n/T) - ceil(t n/T)   (N_e or N_e + 1)
  function automatic longint unsigned bin_size(input longint unsigned n, input longint unsigned t);
    longint unsigned t_total;
    t_total = longint'(N_TIMESTEPS);
    return ((t + 1) * n + t_total - 1) / t_total - (t * n + t_total - 1) / t_total;
  endfunction

  logic [W_STAT-1:0] accepted_q;  // independent count of handshakes in this sample
  logic              strobe_prev_q;
  logic [W_STAT-1:0] strobes_q;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      fail_q        <= 1'b0;
      accepted_q    <= '0;
      strobe_prev_q <= 1'b0;
      strobes_q     <= '0;
    end else begin
      strobe_prev_q <= spike_valid_i;
      if (sample_clr_o) begin
        accepted_q <= '0;
        strobes_q  <= '0;
      end
      if (start_i && can_start && !loaded_q) begin
        $display("[ASSERT FAIL] %m: start before the weights are loaded");
        fail_q <= 1'b1;
      end
      if (ev_accept_o && !ingest_en_i) begin
        $display("[ASSERT FAIL] %m: event accepted while ingest_en is low");
        fail_q <= 1'b1;
      end
      if (ev_accept_o) accepted_q <= accepted_q + ONE;
      if (in_run && accepted_q != W_STAT'(ev_total_i) && run_q != R_INGEST) begin
        $display("[ASSERT FAIL] %m: %0d events accepted but the event counter saw %0d (an event was lost)", accepted_q, ev_total_i);
        fail_q <= 1'b1;
      end
      if (in_run && run_q == R_CHECK) begin
        if (longint'(ev_in_ts_q) != longint'(bin_size(longint'(ev_n_i), longint'(ts_idx_q)))) begin
          $display("[ASSERT FAIL] %m: timestep %0d holds %0d events, floor(k*T/n) rule requires %0d", ts_idx_q, ev_in_ts_q, bin_size(longint'(ev_n_i), longint'(ts_idx_q)));
          fail_q <= 1'b1;
        end
        if (longint'(ev_in_ts_q) != longint'(ev_n_i) / longint'(N_TIMESTEPS) && longint'(ev_in_ts_q) != longint'(ev_n_i) / longint'(N_TIMESTEPS) + 1) begin
          $display("[ASSERT FAIL] %m: timestep %0d event count %0d is neither N_e nor N_e+1", ts_idx_q, ev_in_ts_q);
          fail_q <= 1'b1;
        end
        if (ev_tstep_i != ts_idx_q + W_TSTEP'(1)) begin
          $display("[ASSERT FAIL] %m: event counter timestep %0d inconsistent with controller timestep %0d", ev_tstep_i, ts_idx_q);
          fail_q <= 1'b1;
        end
      end
      if (spike_load_o) strobes_q <= strobes_q + ONE;
      if (spike_valid_i && strobe_prev_q) begin
        $display("[ASSERT FAIL] %m: spike valid strobe is not a single cycle");
        fail_q <= 1'b1;
      end
      if (in_run && run_q == R_WIPE && ts_idx_q == W_TSTEP'(N_TIMESTEPS - 1)) begin
        if (!sample_done_i || ev_total_i != ev_n_i || strobes_q != W_STAT'(N_TIMESTEPS)) begin
          $display("[ASSERT FAIL] %m: sample ended with %0d/%0d events, %0d strobes (T = %0d), done=%0b", ev_total_i, ev_n_i, strobes_q, N_TIMESTEPS, sample_done_i);
          fail_q <= 1'b1;
        end
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
