// snn_regress_tb.sv - self-contained regression harness for snn_top, runs unchanged under Verilator (--binary --timing) and Icarus.
//
// It contains NO reference model. It only drives stimulus prepared by tb/common (Python, which imports int_model.py) and logs what the DUT
// produced, one line per timestep; scripts/run_regression.py then compares every timestep's X, V and spikes against int_model.
//
// Job directory (+job=<dir>):
//   job.txt          geometry(0=DVS 1=N-MNIST)  n_samples  gap_mode  seed          (decimal)
//                    then per sample: n_events  thresh[0..19]  gap_seed              (decimal, signed; gap_seed reseeds the idle-gap generator)
//   weights_macro<m>.mem   five 32-bit-per-line hex files, address 0 first (Phase 0 export format)
//   events.bin       big-endian uint16 AER words, samples concatenated
// Output (+out=<file>):  per timestep   TS <sample> <t> <spikes hex> <20 X> <20 V> <stats...>
//                        per sample     END <sample> <cycles> <stall_cycles> <idle_cycles> <events> <assert_bits>
`timescale 1ns / 1ps

module snn_regress_tb;
  import cim_neurohdc_pkg::*;

  parameter int ROWS_PER_GROUP_P = 8;
  parameter int N_PARALLEL_COLS_P = 160;
  parameter bit PLANE_SKIP_EN_P = 1'b1;
  parameter bit INSTRUMENT_EN_P = 1'b1;
  parameter int MAX_EVENTS = 1500000;  // largest DVS sample is 1,385,905 events

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  // DUT interface
  logic cfg_we = 1'b0;
  logic [W_CFG_ADDR-1:0] cfg_addr = '0;
  logic [W_CFG_DATA-1:0] cfg_data = '0;
  logic load_start = 1'b0, wl_valid = 1'b0, start = 1'b0, ingest_en = 1'b1;
  logic [W_WL_WORD-1:0] wl_data = '0;
  logic wl_ready;
  logic ev_valid = 1'b0;
  logic [W_AER-1:0] ev_aer = '0;
  logic ev_ready;
  logic [N_NEURONS-1:0] spike;
  logic spike_valid, done, weights_loaded;
  logic [W_TSTEP-1:0] spike_tstep;
  logic [1:0] state;
  logic rd_valid;
  logic [W_GRP-1:0] group_idx;
  logic [W_BIT_IDX-1:0] bitrow_idx;
  logic [N_NEURONS*W_X-1:0] x_flat;
  logic [N_NEURONS*W_V-1:0] v_flat;
  logic [W_STAT-1:0] ts_events, ts_active, ts_skipped, ts_rows, ts_allcols, ts_plane, ts_issued, ts_zero, ts_fwd, ts_cyc, ts_cyc_ing, cyc_total;
  logic [7:0] assert_fail;

  snn_top #(
      .ROWS_PER_GROUP (ROWS_PER_GROUP_P),
      .N_PARALLEL_COLS(N_PARALLEL_COLS_P),
      .PLANE_SKIP_EN  (PLANE_SKIP_EN_P),
      .INSTRUMENT_EN  (INSTRUMENT_EN_P)
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
      .start_i(start),
      .ingest_en_i(ingest_en),
      .ev_valid_i(ev_valid),
      .ev_aer_i(ev_aer),
      .ev_ready_o(ev_ready),
      .spike_o(spike),
      .spike_valid_o(spike_valid),
      .spike_tstep_o(spike_tstep),
      .done_o(done),
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
      .cyc_total_o(cyc_total),
      .assert_fail_o(assert_fail)
  );

  // ------------------------------------------------------------------ stimulus storage
  logic [15:0] ev_mem[MAX_EVENTS];
  logic [31:0] wmem[N_MACROS*N_INPUTS];  // macro-major, address 0 first
  integer fd_out, fd_job, fd_ev;
  string job_dir, out_name, path;
  integer geometry, n_samples, gap_mode, seed;
  integer n_events, thr[N_NEURONS], gap_seed;
  logic [31:0] lfsr;
  integer k, s, j, m, a, rc;

  // a tiny xorshift32 for reproducible gaps
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
      cfg_addr = addr[W_CFG_ADDR-1:0];
      cfg_data = data[W_CFG_DATA-1:0];
      @(negedge clk);
      cfg_we = 1'b0;
    end
  endtask

  // ------------------------------------------------------------------ cycle accounting (per sample)
  integer cyc_sample, stall_cycles, idle_cycles, errors, ts_seen;
  logic sampling;
  always @(posedge clk) begin
    if (sampling) begin
      cyc_sample <= cyc_sample + 1;
    end
    if (assert_fail != 8'h0 && rst_n) errors <= errors + 1;
  end

  // explicit sign extension (portable across simulators)
  function automatic integer sx_x(input logic [W_X-1:0] v);
    sx_x = {{(32 - W_X) {v[W_X-1]}}, v};
  endfunction
  function automatic integer sx_v(input logic [W_V-1:0] v);
    sx_v = {{(32 - W_V) {v[W_V-1]}}, v};
  endfunction

  // log one line per timestep on the spike strobe
  always @(posedge clk) begin
    if (spike_valid) begin
      $fwrite(fd_out, "TS %0d %0d %05x", s, spike_tstep, spike);
      for (int jj = 0; jj < N_NEURONS; jj++) $fwrite(fd_out, " %0d", sx_x(x_flat[jj*W_X+:W_X]));
      for (int jj = 0; jj < N_NEURONS; jj++) $fwrite(fd_out, " %0d", sx_v(v_flat[jj*W_V+:W_V]));
      $fwrite(fd_out, " %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n", ts_events, ts_active, ts_skipped, ts_rows, ts_allcols, ts_plane, ts_issued, ts_zero, ts_fwd, ts_cyc,
              ts_cyc_ing);
      ts_seen <= ts_seen + 1;
    end
  end

  // ------------------------------------------------------------------ main
  initial begin
    errors = 0;
    ts_seen = 0;
    sampling = 1'b0;
    cyc_sample = 0;
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
    lfsr = 32'(seed) ^ 32'h9E3779B9;  // overwritten per sample by gap_seed
    for (m = 0; m < N_MACROS; m++) begin
      $sformat(path, "%0s/weights_macro%0d.mem", job_dir, m);
      $readmemh(path, wmem, m * N_INPUTS, (m + 1) * N_INPUTS - 1);
    end
    $sformat(path, "%0s/events.bin", job_dir);
    fd_ev = $fopen(path, "rb");

    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    // geometry registers
    cfg_write(CFG_COORD_MUL, geometry == 0 ? COORD_MUL_DVS : COORD_MUL_NMNIST);
    cfg_write(CFG_AER_SHIFT, geometry == 0 ? AER_SHIFT_DVS : AER_SHIFT_NMNIST);

    // weight image through the shift-in path
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

    for (s = 0; s < n_samples; s++) begin
      rc = $fscanf(fd_job, "%d", n_events);
      for (j = 0; j < N_NEURONS; j++) rc = $fscanf(fd_job, "%d", thr[j]);
      rc   = $fscanf(fd_job, "%d", gap_seed);
      lfsr = 32'(gap_seed) ^ 32'h9E3779B9;
      if (n_events > MAX_EVENTS) begin
        $display("FATAL: sample %0d has %0d events > MAX_EVENTS", s, n_events);
        $finish;
      end
      rc = $fread(ev_mem, fd_ev, 0, n_events);
      for (j = 0; j < N_NEURONS; j++) cfg_write(CFG_THRESH_BASE + j, thr[j] & ((1 << W_THRESH) - 1));
      cfg_write(CFG_THRESH_SHARED, 0);
      cfg_write(CFG_N_EVENTS, n_events);
      errors = 0;
      ts_seen = 0;
      cyc_sample = 0;
      stall_cycles = 0;
      idle_cycles = 0;
      @(negedge clk);
      start = 1'b1;
      sampling = 1'b1;
      @(negedge clk);
      start = 1'b0;

      // event driver: present a word, hold it until ready, then idle for a pseudo-random gap
      for (k = 0; k < n_events; k++) begin
        if (gap_mode != 0) begin
          lfsr = xorshift(lfsr);
          if (lfsr[1:0] != 2'b00) begin  // 3 of 4 events are preceded by 0..3 idle cycles
            repeat (int'(lfsr[3:2])) begin
              ev_valid = 1'b0;
              idle_cycles = idle_cycles + 1;
              @(negedge clk);
            end
          end
        end
        ev_valid = 1'b1;
        ev_aer   = ev_mem[k];
        // ready is a registered-state function (it does not depend on valid): sample it 1 ns before the rising edge, which is
        // exactly what the DUT will see at that edge; race-free in both simulators.
        #4;
        while (!ev_ready) begin
          stall_cycles = stall_cycles + 1;
          @(negedge clk);
          #4;
        end
        @(negedge clk);
      end
      ev_valid = 1'b0;
      while (!done) @(negedge clk);
      repeat (3) @(negedge clk);
      sampling = 1'b0;
      $fwrite(fd_out, "END %0d %0d %0d %0d %0d %0d %0d\n", s, cyc_sample, stall_cycles, idle_cycles, n_events, errors, ts_seen);
    end
    $fclose(fd_out);
    $display("RESULT samples=%0d", n_samples);
    $finish;
  end

  // watchdog: no sample may take more than 3 x events + 10M cycles
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
