// hdc_regress_tb.sv - self-contained regression harness for cim_neurohdc_top (SNN -> HDC query -> margin exit), runs unchanged under Verilator (--binary --timing) and Icarus.
//
// Like snn_regress_tb.sv it contains NO reference model: it drives stimulus prepared by tb/common (Python, which imports the Phase 0 / Phase 2-4 reference) and logs what the DUT
// produced, one line per timestep; scripts/run_hdc_regression.py compares every timestep's spikes, X, V, the N prefix scores, the leader, the margin and the exit decision.
//
// Job directory (+job=<dir>):
//   job.txt          geometry  n_samples  gap_mode  seed                                    (decimal)
//                    per sample: n_events  thresh[0..19]  gap_seed  theta  exit_en            (decimal, signed)
//   weights_macro<m>.mem   five 32-bit-per-line hex files (Phase 0 export format)
//   cmain.mem  csign.mem  cbias.mem   the class image (see hdc_pkg): hex words, address 0 first (csign / cbias only when FACTORIZED)
//   events.bin       big-endian uint16 AER words, samples concatenated
// Output (+out=<file>):  per timestep   TS <sample> <t> <spikes hex> <20 X> <20 V> <11 stats> <N scores> <top1_idx> <top1> <top2> <fire>
//                        per sample     END <sample> <cycles_inf> <cycles_ingest> <cycles_query> <events_ingested> <stall> <idle> <events_total> <assert_bits> <hdc_assert> <ts_seen>
//                                           <pred> <early> <pred_tstep> <reload_cycles>
// An early exit leaves the SNN parked in its INGEST state (1E's controller has no abort), so the next sample is preceded by a reset and a reload of the weight and class
// images; those cycles are reported separately (reload_cycles) and are NOT part of the inference.
`timescale 1ns / 1ps

module hdc_regress_tb;
  import cim_neurohdc_pkg::*;
  import hdc_pkg::*;

  parameter int ROWS_PER_GROUP_P = 8;
  parameter int N_PARALLEL_COLS_P = 160;
  parameter bit PLANE_SKIP_EN_P = 1'b1;
  parameter bit INSTRUMENT_EN_P = 1'b1;
  parameter bit FACTORIZED_P = 1'b1;
  parameter bit EARLY_EXIT_EN_P = 1'b1;
  parameter int N_CLASSES_P = 10;
  parameter int MAX_EVENTS = 1500000;  // largest DVS sample is 1,385,905 events

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  logic [W_TOP_CFG_ADDR-1:0] cfg_addr = '0;
  logic cfg_we = 1'b0;
  logic [W_CFG_DATA-1:0] cfg_data = '0;
  logic load_start = 1'b0, wl_valid = 1'b0, start = 1'b0, ingest_en = 1'b1;
  logic [W_WL_WORD-1:0] wl_data = '0;
  logic wl_ready;
  logic cm_we = 1'b0;
  logic [W_CM_SEL-1:0] cm_sel = '0;
  logic [W_TADDR-1:0] cm_addr = '0;
  logic [N_CLASSES_P*20-1:0] cm_data = '0;
  logic ev_valid = 1'b0;
  logic [W_AER-1:0] ev_aer = '0;
  logic ev_ready;
  logic pred_valid, pred_early, inf_done;
  logic [W_CLASS-1:0] pred;
  logic [W_TADDR-1:0] pred_tstep;
  logic [N_NEURONS-1:0] spike;
  logic spike_valid, dec_valid;
  logic [W_TSTEP-1:0] spike_tstep;
  logic [N_CLASSES_P*W_SCORE-1:0] scores;
  logic [W_CLASS-1:0] top1_idx;
  logic [W_SCORE-1:0] top1, top2, margin;
  logic exit_fire, exited;
  logic snn_done, weights_loaded;
  logic [1:0] state;
  logic rd_valid;
  logic [W_GRP-1:0] group_idx;
  logic [W_BIT_IDX-1:0] bitrow_idx;
  logic [N_NEURONS*W_X-1:0] x_flat;
  logic [N_NEURONS*W_V-1:0] v_flat;
  logic [W_STAT-1:0] ts_events, ts_active, ts_skipped, ts_rows, ts_allcols, ts_plane, ts_issued, ts_zero, ts_fwd, ts_cyc, ts_cyc_ing;
  logic [4:0] q_rows_gated;
  logic [W_STAT-1:0] q_reads, cyc_query, cyc_inf, events_ingested;
  logic [7:0] assert_fail;
  logic hdc_assert_fail;

  cim_neurohdc_top #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP_P),
      .N_PARALLEL_COLS(N_PARALLEL_COLS_P),
      .PLANE_SKIP_EN  (PLANE_SKIP_EN_P),
      .INSTRUMENT_EN  (INSTRUMENT_EN_P),
      .N_CLASSES      (N_CLASSES_P),
      .FACTORIZED     (FACTORIZED_P),
      .EARLY_EXIT_EN  (EARLY_EXIT_EN_P)
  ) dut (
      .clk_i(clk),
      .rst_n_i(rst_n),
      .cfg_we_i(cfg_we),
      .cfg_addr_i(cfg_addr),
      .cfg_data_i(cfg_data),
      .load_start_i(load_start),
      .wl_valid_i(wl_valid),
      .wl_data_i(wl_data),
      .wl_ready_o(wl_ready),
      .cm_we_i(cm_we),
      .cm_sel_i(cm_sel),
      .cm_addr_i(cm_addr),
      .cm_data_i(cm_data),
      .start_i(start),
      .ingest_en_i(ingest_en),
      .ev_valid_i(ev_valid),
      .ev_aer_i(ev_aer),
      .ev_ready_o(ev_ready),
      .pred_valid_o(pred_valid),
      .pred_o(pred),
      .pred_tstep_o(pred_tstep),
      .pred_early_o(pred_early),
      .inf_done_o(inf_done),
      .spike_o(spike),
      .spike_valid_o(spike_valid),
      .spike_tstep_o(spike_tstep),
      .dec_valid_o(dec_valid),
      .scores_o(scores),
      .top1_idx_o(top1_idx),
      .top1_o(top1),
      .top2_o(top2),
      .margin_o(margin),
      .exit_fire_o(exit_fire),
      .exited_o(exited),
      .snn_done_o(snn_done),
      .state_o(state),
      .weights_loaded_o(weights_loaded),
      .rd_valid_o(rd_valid),
      .group_idx_o(group_idx),
      .bitrow_idx_o(bitrow_idx),
      .x_o(x_flat),
      .v_o(v_flat),
      .ts_events_o(ts_events),
      .ts_active_o(ts_active),
      .ts_rows_skipped_o(ts_skipped),
      .ts_rows_read_o(ts_rows),
      .ts_reads_allcols_o(ts_allcols),
      .ts_reads_plane_o(ts_plane),
      .ts_reads_issued_o(ts_issued),
      .ts_zero_groups_o(ts_zero),
      .ts_fwd_o(ts_fwd),
      .ts_cycles_o(ts_cyc),
      .ts_cycles_ingest_o(ts_cyc_ing),
      .q_rows_gated_o(q_rows_gated),
      .q_reads_o(q_reads),
      .cyc_query_o(cyc_query),
      .cyc_inf_o(cyc_inf),
      .events_ingested_o(events_ingested),
      .assert_fail_o(assert_fail),
      .hdc_assert_fail_o(hdc_assert_fail)
  );

  // ------------------------------------------------------------------ stimulus storage
  logic [15:0] ev_mem[MAX_EVENTS];
  logic [31:0] wmem[N_MACROS*N_INPUTS];
  logic [N_CLASSES_P*20-1:0] cmain[128];
  logic [N_CLASSES_P-1:0] csign[128];
  logic [N_CLASSES_P*5-1:0] cbias[1];
  integer fd_out, fd_job, fd_ev;
  string job_dir, out_name, path;
  integer geometry, n_samples, gap_mode, seed;
  integer n_events, thr[N_NEURONS], gap_seed, theta, exit_en;
  logic [31:0] lfsr;
  integer k, s, j, m, a, rc;
  integer n_main_words;
  logic [N_CLASSES_P*20-1:0] cm_tmp;

  function automatic logic [31:0] xorshift(input logic [31:0] v);
    logic [31:0] t;
    t = v ^ (v << 13);
    t = t ^ (t >> 17);
    t = t ^ (t << 5);
    return t;
  endfunction

  task automatic cfg_write(input int addr, input int data);
    begin
      @(negedge clk);
      cfg_we   = 1'b1;
      cfg_addr = addr[W_TOP_CFG_ADDR-1:0];
      cfg_data = data[W_CFG_DATA-1:0];
      @(negedge clk);
      cfg_we = 1'b0;
    end
  endtask

  task automatic cm_write(input int sel, input int addr, input logic [N_CLASSES_P*20-1:0] data);
    begin
      @(negedge clk);
      cm_we   = 1'b1;
      cm_sel  = sel[W_CM_SEL-1:0];
      cm_addr = addr[W_TADDR-1:0];
      cm_data = data;
      @(negedge clk);
      cm_we = 1'b0;
    end
  endtask

  // ------------------------------------------------------------------ cycle accounting (per sample)
  integer cyc_sample, stall_cycles, idle_cycles, errors, hdc_errors, ts_seen, reload_cycles;
  logic sampling, reloading;
  always @(posedge clk) begin
    if (sampling) cyc_sample <= cyc_sample + 1;
    if (reloading) reload_cycles <= reload_cycles + 1;
    if (assert_fail != 8'h0 && rst_n) errors <= errors + 1;
    if (hdc_assert_fail && rst_n) hdc_errors <= hdc_errors + 1;
  end

  function automatic integer sx_x(input logic [W_X-1:0] v);
    sx_x = {{(32 - W_X) {v[W_X-1]}}, v};
  endfunction
  function automatic integer sx_v(input logic [W_V-1:0] v);
    sx_v = {{(32 - W_V) {v[W_V-1]}}, v};
  endfunction

  // one line per timestep, on the decision strobe (the spike vector, X, V and the per-timestep SNN counters are all still held at that point)
  always @(posedge clk) begin
    if (dec_valid) begin
      $fwrite(fd_out, "TS %0d %0d %05x", s, spike_tstep, spike);
      for (int jj = 0; jj < N_NEURONS; jj++) $fwrite(fd_out, " %0d", sx_x(x_flat[jj*W_X+:W_X]));
      for (int jj = 0; jj < N_NEURONS; jj++) $fwrite(fd_out, " %0d", sx_v(v_flat[jj*W_V+:W_V]));
      $fwrite(fd_out, " %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d", ts_events, ts_active, ts_skipped, ts_rows, ts_allcols, ts_plane, ts_issued, ts_zero, ts_fwd, ts_cyc, ts_cyc_ing);
      for (int cc = 0; cc < N_CLASSES_P; cc++) $fwrite(fd_out, " %0d", scores[cc*W_SCORE+:W_SCORE]);
      $fwrite(fd_out, " %0d %0d %0d %0d %0d\n", top1_idx, top1, top2, exit_fire, q_rows_gated);
      ts_seen <= ts_seen + 1;
    end
  end

  // ------------------------------------------------------------------ reset + weight image + class image (initial load and after an early exit)
  task automatic bring_up;
    begin
      reloading = 1'b1;
      rst_n = 1'b0;
      repeat (4) @(negedge clk);
      rst_n = 1'b1;
      repeat (2) @(negedge clk);
      cfg_write(CFG_COORD_MUL, geometry == 0 ? COORD_MUL_DVS : COORD_MUL_NMNIST);
      cfg_write(CFG_AER_SHIFT, geometry == 0 ? AER_SHIFT_DVS : AER_SHIFT_NMNIST);
      @(negedge clk);
      load_start = 1'b1;
      @(negedge clk);
      load_start = 1'b0;
      for (m = 0; m < N_MACROS; m++)
      for (a = 0; a < N_INPUTS; a++) begin
        wl_valid = 1'b1;
        wl_data  = wmem[m*N_INPUTS+a];
        #4;
        while (!wl_ready) begin
          @(negedge clk);
          #4;
        end
        @(negedge clk);
      end
      wl_valid = 1'b0;
      while (!weights_loaded) @(negedge clk);
      for (a = 0; a < n_main_words; a++) cm_write(CM_SEL_ARRAY, a, cmain[a]);
      if (FACTORIZED_P) begin
        for (a = 0; a < N_TIMESTEPS; a++) begin
          cm_tmp = '0;
          cm_tmp[N_CLASSES_P-1:0] = csign[a];
          cm_write(CM_SEL_SIGN, a, cm_tmp);
        end
        cm_tmp = '0;
        cm_tmp[N_CLASSES_P*5-1:0] = cbias[0];
        cm_write(CM_SEL_BIAS, 0, cm_tmp);
      end
      reloading = 1'b0;
    end
  endtask

`ifdef VCD_DUMP
  // switching-activity capture for the power estimate (Phase 5): a window of the first sample, +vcd=<file> +vcd_start=<cycle> +vcd_len=<cycles> (cycles counted from start_i)
  string vcd_name;
  integer vcd_start, vcd_len;
  logic vcd_active;
  initial begin
    vcd_active = 1'b0;
    if ($value$plusargs("vcd=%s", vcd_name)) begin
      vcd_active = 1'b1;
      if (!$value$plusargs("vcd_start=%d", vcd_start)) vcd_start = 0;
      if (!$value$plusargs("vcd_len=%d", vcd_len)) vcd_len = 6000;
    end
  end
  always @(posedge clk) begin
    if (vcd_active && sampling) begin
      if (cyc_sample == vcd_start) begin
        $dumpfile(vcd_name);
        $dumpvars(0, dut);
      end
      if (cyc_sample == vcd_start + vcd_len) begin
        $dumpoff;
        vcd_active <= 1'b0;
      end
    end
  end
`endif

  // ------------------------------------------------------------------ main
  logic need_bring_up;
  logic stop_stream;
  initial begin
    errors = 0;
    hdc_errors = 0;
    ts_seen = 0;
    sampling = 1'b0;
    reloading = 1'b0;
    cyc_sample = 0;
    reload_cycles = 0;
    stall_cycles = 0;
    idle_cycles = 0;
    s = 0;
    if (!$value$plusargs("job=%s", job_dir)) begin
      $display("FATAL: +job=<dir> required");
      $finish;
    end
    if (!$value$plusargs("out=%s", out_name)) out_name = {job_dir, "/out.txt"};
    fd_out = $fopen(out_name, "w");
    $sformat(path, "%0s/job.txt", job_dir);
    fd_job = $fopen(path, "r");
    rc = $fscanf(fd_job, "%d %d %d %d\n", geometry, n_samples, gap_mode, seed);
    lfsr = 32'(seed) ^ 32'h9E3779B9;
    for (m = 0; m < N_MACROS; m++) begin
      $sformat(path, "%0s/weights_macro%0d.mem", job_dir, m);
      $readmemh(path, wmem, m * N_INPUTS, (m + 1) * N_INPUTS - 1);
    end
    $sformat(path, "%0s/cmain.mem", job_dir);
    n_main_words = FACTORIZED_P ? 1 : N_TIMESTEPS;
    $readmemh(path, cmain, 0, n_main_words - 1);
    if (FACTORIZED_P) begin
      $sformat(path, "%0s/csign.mem", job_dir);
      $readmemh(path, csign, 0, N_TIMESTEPS - 1);
      $sformat(path, "%0s/cbias.mem", job_dir);
      $readmemh(path, cbias, 0, 0);
    end
    $sformat(path, "%0s/events.bin", job_dir);
    fd_ev = $fopen(path, "rb");

    bring_up();
    need_bring_up = 1'b0;

    for (s = 0; s < n_samples; s++) begin
      rc = $fscanf(fd_job, "%d", n_events);
      for (j = 0; j < N_NEURONS; j++) rc = $fscanf(fd_job, "%d", thr[j]);
      rc = $fscanf(fd_job, "%d %d %d", gap_seed, theta, exit_en);
      lfsr = 32'(gap_seed) ^ 32'h9E3779B9;
      if (n_events > MAX_EVENTS) begin
        $display("FATAL: sample %0d has %0d events > MAX_EVENTS", s, n_events);
        $finish;
      end
      rc = $fread(ev_mem, fd_ev, 0, n_events);
      reload_cycles = 0;
      if (need_bring_up) bring_up();
      for (j = 0; j < N_NEURONS; j++) cfg_write(CFG_THRESH_BASE + j, thr[j] & ((1 << W_THRESH) - 1));
      cfg_write(CFG_THRESH_SHARED, 0);
      cfg_write(CFG_N_EVENTS, n_events);
      cfg_write(CFG_THETA, theta);
      cfg_write(CFG_EXIT_EN, exit_en);
      errors = 0;
      hdc_errors = 0;
      ts_seen = 0;
      cyc_sample = 0;
      stall_cycles = 0;
      idle_cycles = 0;
      stop_stream = 1'b0;
      @(negedge clk);
      start = 1'b1;
      sampling = 1'b1;
      @(negedge clk);
      start = 1'b0;

      // event driver: present a word, hold it until ready (or until the inference is over), then idle for a pseudo-random gap
      for (k = 0; k < n_events && !stop_stream; k++) begin
        if (gap_mode != 0) begin
          lfsr = xorshift(lfsr);
          if (lfsr[1:0] != 2'b00) begin
            repeat (int'(lfsr[3:2])) begin
              ev_valid = 1'b0;
              idle_cycles = idle_cycles + 1;
              @(negedge clk);
            end
          end
        end
        ev_valid = 1'b1;
        ev_aer   = ev_mem[k];
        #4;
        while (!ev_ready && !stop_stream) begin
          stall_cycles = stall_cycles + 1;
          if (exited) stop_stream = 1'b1;
          @(negedge clk);
          #4;
        end
        if (!stop_stream) @(negedge clk);
      end
      ev_valid = 1'b0;
      while (!inf_done) @(negedge clk);
      // let the prediction strobe and (when the sample ran to the end) the SNN's DONE settle
      repeat (4) @(negedge clk);
      sampling = 1'b0;
      $fwrite(fd_out, "END %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n", s, cyc_inf, 0, cyc_query, events_ingested, stall_cycles, idle_cycles, n_events, errors, hdc_errors,
              ts_seen, pred, pred_early, pred_tstep, reload_cycles);
      need_bring_up = exited && !snn_done;
    end
    $fclose(fd_out);
    $display("RESULT samples=%0d", n_samples);
    $finish;
  end

  integer wd;
  always @(posedge clk) begin
    if (!sampling) wd <= 0;
    else wd <= wd + 1;
    if (wd > 40_000_000) begin
      $display("FATAL: watchdog expired in sample %0d", s);
      $finish;
    end
  end
endmodule
