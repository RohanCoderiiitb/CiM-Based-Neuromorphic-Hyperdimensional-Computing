// plane_seq.sv - block D. Scan sequencer of one timestep (optimisation items 1 and 3): reads the 512 event counters out of the count-memory SRAM, group by group, and issues one crossbar read for
// every (count bit-plane b, group) that has an active row - the all-zero (b, group) reads are never issued (the a = 0 skip).
//
//   FETCH   reads the counters of group j (ROWS_PER_GROUP consecutive addresses) one per cycle, through the SRAM's read port, into one of two group buffers (ping-pong). The words arrive a cycle
//           after their read (count_mem registers them and clears them in place: the scan IS the timestep wipe). When the last word of a group has arrived the bit-plane mask is formed:
//           mask[b] = OR over the group's counters of bit b. A group whose mask is zero (all its counters are zero) is dropped on the spot and its buffer stays free.
//   ISSUE   takes the oldest full buffer and issues one crossbar read per set mask bit (lowest plane first): row bits = bit b of each of the group's counters, the group index, the plane b
//           (shift_accum shifts by it); the buffer is freed with its last read. N_PARALLEL_COLS < 160 repeats each read N_WCOLS / N_PARALLEL_COLS times (4 passes of 40 columns = 2 weight bit-planes each, the supply-limited design of 1F; 8 passes of 20).
//   The two run concurrently: while group j's planes are issued, group j+1's counters are fetched. Fetching a group's first word needs a free buffer (credit counter `occ_q`: full buffers +
//   the group in flight), so the pipeline never overwrites a buffer that still holds reads to issue.
//
// The plane order differs from the earlier plane-major walk (all groups of plane 0, then plane 1 ...); X is the same sum, shift_accum adds each read's contribution as it arrives.
// `done_o` (one-cycle pulse) comes when all 512 counters have been read and cleared and every read has been issued.
import cim_neurohdc_pkg::INSTRUMENT_EN_DEFAULT;
import cim_neurohdc_pkg::N_INPUTS;
import cim_neurohdc_pkg::N_PARALLEL_COLS_DEFAULT;
import cim_neurohdc_pkg::N_WCOLS;
import cim_neurohdc_pkg::ROWS_PER_GROUP_DEFAULT;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_BIT_IDX;
import cim_neurohdc_pkg::W_COUNT;
import cim_neurohdc_pkg::W_GRP;
import cim_neurohdc_pkg::W_STAT;
import cim_neurohdc_pkg::W_WEIGHT;

module plane_seq #(
    parameter int ROWS_PER_GROUP  = ROWS_PER_GROUP_DEFAULT,
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    parameter bit INSTRUMENT_EN   = INSTRUMENT_EN_DEFAULT,  // 0: the access counters are not built (their outputs are zero)
    localparam int W_PASS         = (N_WCOLS / N_PARALLEL_COLS > 1) ? $clog2(N_WCOLS / N_PARALLEL_COLS) : 1
) (
    input  logic                       clk_i,
    input  logic                       rst_n_i,
    input  logic                       start_i,          // begin the scan of one timestep (sequencer idle, count memory quiet)
    input  logic                       abort_i,          // drop the scan in progress (no done pulse)
    // count memory scan port
    output logic                       scan_re_o,
    output logic [       W_ADDR-1:0]   scan_addr_o,
    input  logic [     W_COUNT-1:0]    scan_q_i,
    input  logic                       scan_qv_i,
    // crossbar read
    output logic                       rd_valid_o,
    output logic [ROWS_PER_GROUP-1:0]  rd_bits_o,        // bit b of each counter of the group
    output logic [        W_GRP-1:0]   group_idx_o,
    output logic [    W_BIT_IDX-1:0]   row_sel_o,        // count bit-plane b of this read
    output logic [  W_PASS-1:0]        pass_o,           // sensing pass of this read (which PL = W_WEIGHT / N_PASSES weight bit-planes are sensed)
    output logic                       done_o,
    output logic                       busy_o,
    output logic [       W_STAT-1:0]   active_o,           // counters != 0 (this timestep)
    output logic [       W_STAT-1:0]   rows_skipped_o,     // count bit-planes with no bit set in any counter (this timestep)
    output logic [       W_STAT-1:0]   rows_read_o,
    output logic [       W_STAT-1:0]   reads_allcols_o,    // (bit-plane, group) reads with an active row: 11 x 512/g form minus the empty groups
    output logic [       W_STAT-1:0]   reads_plane_o,
    output logic [       W_STAT-1:0]   reads_issued_o,
    output logic [       W_STAT-1:0]   zero_groups_o,      // empty groups of the non-empty bit-planes (jumped over)
    output logic                       assert_fail_o
);
  localparam int N_GROUPS = N_INPUTS / ROWS_PER_GROUP;
  localparam int N_PASSES = N_WCOLS / N_PARALLEL_COLS;
  localparam int W_FW = (ROWS_PER_GROUP > 1) ? $clog2(ROWS_PER_GROUP) : 1;
  localparam logic [W_BIT_IDX-1:0] LAST_PASS = W_BIT_IDX'(N_PASSES - 1);
  localparam logic [W_STAT-1:0] STAT_ONE = W_STAT'(1);

  // ---------------------------------------------------------------- state
  logic                  scan_q;  // a scan is in progress
  logic                  fetch_done_q;  // every read of the scan has been issued
  logic [    W_ADDR-1:0] faddr_q;
  logic [       W_FW-1:0] fw_q;  // word index within the group being fetched
  logic [     W_GRP-1:0] fgrp_q;
  logic                  fb_q;  // buffer the next group to arrive fills
  logic                  ib_q;  // buffer the issue side serves
  logic [           1:0] full_q;
  logic [  W_COUNT-1:0]  mask_q[2];
  logic [     W_GRP-1:0] gidx_q[2];
  logic [  W_COUNT-1:0]  buf_q[2][ROWS_PER_GROUP];
  logic [           1:0] occ_q;  // buffers reserved: full + the group in flight
  logic [W_BIT_IDX-1:0]  pass_q;
  logic                  done_q;
  // arrival pipeline (the word read in the previous cycle)
  logic                  arr_v_q;
  logic [       W_FW-1:0] arr_w_q;
  logic                  arr_last_q;
  logic [     W_GRP-1:0] arr_grp_q;

  // ---------------------------------------------------------------- issue side
  logic            iss_full;
  logic [W_COUNT-1:0] iss_mask;
  logic [W_BIT_IDX-1:0] iss_plane;
  logic            iss_last_plane;  // after this read the buffer is empty
  logic            iss_last;  // this read frees the buffer
  logic            issue;

  always_comb begin
    iss_full = full_q[ib_q];
    iss_mask = mask_q[ib_q];
    iss_plane = '0;
    for (int p = W_COUNT - 1; p >= 0; p--) if (iss_mask[p]) iss_plane = W_BIT_IDX'(p);
  end
  assign iss_last_plane = ((iss_mask & (iss_mask - W_COUNT'(1))) == '0);
  assign issue          = iss_full;
  assign iss_last       = issue && iss_last_plane && (pass_q == LAST_PASS);

  assign rd_valid_o     = issue;
  assign group_idx_o    = gidx_q[ib_q];
  assign row_sel_o      = iss_plane;
  assign pass_o         = W_PASS'(pass_q);
  always_comb begin
    for (int r = 0; r < ROWS_PER_GROUP; r++) rd_bits_o[r] = buf_q[ib_q][r][iss_plane];
  end

  // ---------------------------------------------------------------- fetch side
  logic            word0;
  logic            can_fetch;
  logic            fetch;
  assign word0     = (fw_q == W_FW'(0));
  // a new group needs a free buffer; a buffer freed by this cycle's last read counts as free (the group's first word arrives a cycle later)
  assign can_fetch = scan_q && !fetch_done_q && (!word0 || occ_q != 2'd2 || iss_last);
  assign fetch     = can_fetch;
  assign scan_re_o   = fetch;
  assign scan_addr_o = faddr_q;
  assign busy_o      = scan_q;
  assign done_o      = done_q;

  // group completion (comb, in the cycle the last word arrives)
  logic [W_COUNT-1:0] words[ROWS_PER_GROUP];
  logic [W_COUNT-1:0] m_true;
  always_comb begin
    for (int w = 0; w < ROWS_PER_GROUP; w++) words[w] = (w == ROWS_PER_GROUP - 1) ? scan_q_i : buf_q[fb_q][w];
    m_true = '0;
    for (int w = 0; w < ROWS_PER_GROUP; w++) m_true = m_true | words[w];
  end
  logic complete, keep;
  assign complete = arr_v_q && arr_last_q;
  assign keep     = complete && (m_true != '0);

  // will the buffers be empty at the end of this cycle?
  logic [1:0] full_next;
  always_comb begin
    full_next = full_q;
    if (iss_last) full_next[ib_q] = 1'b0;
    if (keep) full_next[fb_q] = 1'b1;
  end
  logic quiet_next;
  assign quiet_next = scan_q && fetch_done_q && !(arr_v_q && !arr_last_q) && !complete && (full_next == 2'b00) && !(fetch);

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || abort_i) begin
      scan_q       <= 1'b0;
      fetch_done_q <= 1'b0;
      faddr_q      <= '0;
      fw_q         <= '0;
      fgrp_q       <= '0;
      fb_q         <= 1'b0;
      ib_q         <= 1'b0;
      full_q       <= '0;
      occ_q        <= '0;
      pass_q       <= '0;
      done_q       <= 1'b0;
      arr_v_q      <= 1'b0;
      arr_w_q      <= '0;
      arr_last_q   <= 1'b0;
      arr_grp_q    <= '0;
    end else begin
      done_q <= 1'b0;
      if (start_i && !scan_q) begin
        scan_q       <= 1'b1;
        fetch_done_q <= 1'b0;
        faddr_q      <= '0;
        fw_q         <= '0;
        fgrp_q       <= '0;
        occ_q        <= '0;
      end else if (scan_q) begin
        // fetch
        if (fetch) begin
          faddr_q <= faddr_q + W_ADDR'(1);
          if (fw_q == W_FW'(ROWS_PER_GROUP - 1)) begin
            fw_q   <= '0;
            fgrp_q <= fgrp_q + W_GRP'(1);
          end else fw_q <= fw_q + W_FW'(1);
          if (faddr_q == W_ADDR'(N_INPUTS - 1)) fetch_done_q <= 1'b1;
        end
        arr_v_q    <= fetch;
        arr_w_q    <= fw_q;
        arr_last_q <= fetch && (fw_q == W_FW'(ROWS_PER_GROUP - 1));
        arr_grp_q  <= fgrp_q;
        // arrival: words go into the buffer; the last word completes the group
        if (keep) begin
          full_q[fb_q] <= 1'b1;
          mask_q[fb_q] <= m_true;
          gidx_q[fb_q] <= arr_grp_q;
          fb_q              <= ~fb_q;
        end
        // issue
        if (issue) begin
          if (pass_q != LAST_PASS) pass_q <= pass_q + W_BIT_IDX'(1);
          else begin
            pass_q <= '0;
            mask_q[ib_q] <= iss_mask & (iss_mask - W_COUNT'(1));
            if (iss_last_plane) begin
              full_q[ib_q] <= (keep && (fb_q == ib_q)) ? 1'b1 : 1'b0;
              ib_q         <= ~ib_q;
            end
          end
        end
        // reservation counter: +1 when a new group's first word is read, -1 when a group is dropped or a buffer is freed
        occ_q <= occ_q + ((fetch && word0) ? 2'd1 : 2'd0) - ((complete && !keep) ? 2'd1 : 2'd0) - (iss_last ? 2'd1 : 2'd0);
        if (quiet_next) begin
          scan_q <= 1'b0;
          done_q <= 1'b1;
        end
      end
    end
  end

  // word capture (no reset: a buffer's contents only matter between its arrival and its last read)
  always_ff @(posedge clk_i) begin
    if (arr_v_q) buf_q[fb_q][arr_w_q] <= scan_q_i;
  end

  // ------------------------------------------------------------------ access counters (instrumentation: INSTRUMENT_EN = 0 builds none of them)
  if (INSTRUMENT_EN) begin : g_instr
    logic [W_STAT-1:0] active_q, allcols_q, plane_q, issued_q;
    logic [W_COUNT-1:0] seen_q;
    always_ff @(posedge clk_i) begin
      if (!rst_n_i || (start_i && !scan_q)) begin
        active_q  <= '0;
        allcols_q <= '0;
        plane_q   <= '0;
        issued_q  <= '0;
        seen_q    <= '0;
      end else begin
        if (arr_v_q && (scan_q_i != '0)) active_q <= active_q + STAT_ONE;
        if (complete) seen_q <= seen_q | m_true;
        if (issue) begin
          issued_q <= issued_q + STAT_ONE;
          if (pass_q == '0) begin
            allcols_q <= allcols_q + STAT_ONE;
            plane_q   <= plane_q + W_STAT'(W_WEIGHT);
          end
        end
      end
    end
    logic [W_STAT-1:0] n_seen;
    always_comb begin
      n_seen = '0;
      for (int p = 0; p < W_COUNT; p++) n_seen = n_seen + W_STAT'(seen_q[p]);
    end
    assign active_o        = active_q;
    assign rows_read_o     = n_seen;
    assign rows_skipped_o  = W_STAT'(W_COUNT) - n_seen;
    assign reads_allcols_o = allcols_q;
    assign reads_plane_o   = plane_q;
    assign reads_issued_o  = issued_q;
    assign zero_groups_o   = n_seen * W_STAT'(N_GROUPS) - allcols_q;
  end else begin : g_no_instr
    assign active_o        = '0;
    assign rows_read_o     = '0;
    assign rows_skipped_o  = '0;
    assign reads_allcols_o = '0;
    assign reads_plane_o   = '0;
    assign reads_issued_o  = '0;
    assign zero_groups_o   = '0;
  end

  logic unused_ok;
  assign unused_ok = &{1'b0, scan_qv_i};

  // ------------------------------------------------------------------ assertions (simulation only)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  initial begin
    if (N_INPUTS % ROWS_PER_GROUP != 0) $fatal(1, "plane_seq: ROWS_PER_GROUP %0d does not divide %0d", ROWS_PER_GROUP, N_INPUTS);
  end
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else begin
      if (start_i && scan_q) begin
        $display("[ASSERT FAIL] %m: start while the scan is busy");
        fail_q <= 1'b1;
      end
      if (arr_v_q && arr_last_q && (fb_q == ib_q) && full_q[fb_q] && !iss_last) begin
        $display("[ASSERT FAIL] %m: a group completed into a buffer that still holds reads");
        fail_q <= 1'b1;
      end
      if (arr_v_q && !scan_qv_i) begin
        $display("[ASSERT FAIL] %m: arrival without a scan word");
        fail_q <= 1'b1;
      end
      if (occ_q > 2'd2) begin
        $display("[ASSERT FAIL] %m: buffer reservation counter overflow");
        fail_q <= 1'b1;
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
