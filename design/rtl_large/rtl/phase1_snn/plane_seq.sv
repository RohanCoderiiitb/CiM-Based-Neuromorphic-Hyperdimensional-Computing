// plane_seq.sv - block D. PACKED-ROW scan sequencer: turns the event counters of one timestep into crossbar reads.
//
// A read drives up to S_ROWS (4) ACTIVE rows of ONE count bit-plane that lie in ONE position band of the array. The crossbar is random access, so the rows need not be neighbours: instead of reading a
// fixed group of 4 adjacent rows whenever any of them has the bit (1.6 active rows per read on average) the active rows of a plane are PACKED, 4 per read, in every band (reads: DVS -56 %, N-MNIST -57 %).
// The sum is the same integer (rows commute), so X is bit-identical. Position bands keep the rows of a read within ~2 % of each other in row gain (the gain varies smoothly along the bit-line).
//
//   FETCH   the dirty counter blocks (groups that received an event; two ping-pong sets) are fetched in address order = band by band, one group (4 counters) per cycle.
//   EXTRACT for each of N_PK (4) count bit-planes of the current PASS, the active rows of the arriving group (bit set in the counter) are appended to that plane's packer (7 row slots).
//   ISSUE   when the previous group is done, every packer holding >= S_ROWS rows (or any rows, while being flushed) loads one read into the group (row indices + valid mask; band and plane);
//           the group runs PASS-MAJOR: analog pass 0 of each of its reads, then pass 1, ... (N_PASSES passes per read).
//   FLUSH   at the end of a band (the next group is in another band) and at the end of a pass every packer is drained, partial reads included: reads = sum over bands, planes of ceil(n_active / 4).
//   PASSES  the counters have up to W_COUNT (11) bit-planes; N_PK of them are handled per pass over the dirty groups. The number of passes comes from the OR of every value written to the counter set
//           as the scan goes: a pass is followed by another while some group had a count bit above its planes. A group is cleared (count_mem) when it arrives with no bit left.
import cim_neurohdc_pkg::INSTRUMENT_EN_DEFAULT;
import cim_neurohdc_pkg::N_BANDS;
import cim_neurohdc_pkg::N_DIRTY_GS;
import cim_neurohdc_pkg::N_INPUTS;
import cim_neurohdc_pkg::N_PARALLEL_COLS_DEFAULT;
import cim_neurohdc_pkg::N_PK;
import cim_neurohdc_pkg::N_WCOLS;
import cim_neurohdc_pkg::ROWS_PER_GROUP_DEFAULT;
import cim_neurohdc_pkg::S_ROWS;
import cim_neurohdc_pkg::W_BAND;
import cim_neurohdc_pkg::W_BANK_ADDR;
import cim_neurohdc_pkg::W_BIT_IDX;
import cim_neurohdc_pkg::W_COUNT;
import cim_neurohdc_pkg::W_GRP;
import cim_neurohdc_pkg::W_RB;
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
    input  logic                       start_i,          // begin the scan of one timestep (sequencer idle)
    input  logic                       abort_i,          // drop the scan in progress (no done pulse)
    // event stream (sparse scan: the groups that received an event are remembered)
    input  logic                       ing_sel_i,        // counter set the events of the timestep being ingested go to
    output logic                       scan_set_o,       // counter set this scan reads
    input  logic [2*(N_INPUTS/ROWS_PER_GROUP/N_DIRTY_GS)-1:0] dirty_i,  // per counter set: the counter blocks that hold events (kept by count_mem, next to the counters)
    output logic                       dirty_clr_o,      // the scan of set dirty_clr_set_o is complete: clear its flags
    output logic                       dirty_clr_set_o,
    // count memory scan port
    output logic                       scan_re_o,        // read one whole group of counters (its ROWS_PER_GROUP words come back together, one cycle later)
    output logic                       scan_clr_o,       // with scan_qv_i: the arriving group has no count bit above this pass's planes - count_mem clears it
    output logic [        W_GRP-1:0]   scan_grp_o,
    input  logic [ROWS_PER_GROUP*W_COUNT-1:0] scan_q_i,
    input  logic                       scan_qv_i,
    // crossbar read
    output logic                       rd_valid_o,
    output logic [S_ROWS-1:0]          rd_rv_o,          // which row slots are driven
    output logic [S_ROWS*W_RB-1:0]     rd_rows_o,        // row index of every slot inside the band
    output logic [      W_BAND-1:0]    rd_band_o,
    output logic [    W_BIT_IDX-1:0]   row_sel_o,        // count bit-plane of this read
    output logic [  W_PASS-1:0]        pass_o,           // sensing pass of this read (which PL = W_WEIGHT / N_PASSES weight bit-planes are sensed)
    output logic                       done_o,
    output logic                       busy_o,
    output logic [       W_STAT-1:0]   active_o,           // counters != 0 (this timestep)
    output logic [       W_STAT-1:0]   rows_skipped_o,     // count bit-planes with no bit set in any counter (this timestep)
    output logic [       W_STAT-1:0]   rows_read_o,
    output logic [       W_STAT-1:0]   reads_allcols_o,    // packed reads issued (all passes of one read count once)
    output logic [       W_STAT-1:0]   reads_plane_o,
    output logic [       W_STAT-1:0]   reads_issued_o,     // analog passes issued
    output logic [       W_STAT-1:0]   zero_groups_o,
    output logic                       assert_fail_o
);
  localparam int N_GROUPS = N_INPUTS / ROWS_PER_GROUP;
  localparam int N_PASSES = N_WCOLS / N_PARALLEL_COLS;
  localparam int LGD = $clog2(N_DIRTY_GS);  // group-index bits below a dirty flag
  localparam int N_SG = N_GROUPS / N_DIRTY_GS;  // dirty flags per counter set
  localparam int W_GI = (N_SG > 1) ? $clog2(N_SG) : 1;  // bits of a flag index
  localparam int CAP = S_ROWS + ROWS_PER_GROUP;  // row slots of a packer: up to S_ROWS held + S_ROWS arriving (the accept rule assumes every row of a group is active)
  localparam int W_CN = $clog2(CAP + 1);
  localparam int W_GB = W_BANK_ADDR;  // bits of a group index (7)
  localparam int N_QP = (W_COUNT + N_PK - 1) / N_PK;  // passes over the groups for all count bit-planes
  localparam int W_QP = $clog2(N_QP + 1);
  localparam logic [W_PASS-1:0] LAST_PASS = W_PASS'(N_PASSES - 1);
  localparam logic [W_STAT-1:0] STAT_ONE = W_STAT'(1);

  // ---------------------------------------------------------------- state
  logic                  scan_q;  // a scan is in progress
  logic                  fetch_done_q;  // every dirty group of this pass has been fetched
  logic                  fin_q;  // the last pass is complete and flushed: wait for the last read
  logic [W_GRP-1:0]      fgrp_q;
  logic [W_GI:0]         ptr_q;  // flags below ptr are behind the fetch of this pass
  logic [W_QP-1:0]       qpass_q;  // pass over the groups (count bit-planes N_PK*qpass .. N_PK*qpass + N_PK - 1)
  logic                  more_q;  // a group of this pass has count bits above the pass's planes: another pass is needed
  logic                  done_q;
  logic                  arr_v_q;
  logic [W_GRP-1:0]      arr_grp_q;
  logic                  sset_q;  // counter set of the scan in progress (taken at start_i: the set the ingest side is handing over)
  logic                  sset;
  logic                  prime_q;  // the cycle after start_i: the first dirty block is found (timing: start_i does not reach the find-first)
  logic [W_RB-1:0]       pk_row_q[N_PK][CAP];
  logic [W_CN-1:0]       pk_cnt_q[N_PK];
  logic [W_BAND-1:0]     cur_band_q;  // band of the rows in the packers
  // read GROUP: up to N_PK reads (one per packer, loaded together), issued PASS-MAJOR (pass 0 of every read of the group, then pass 1, ...): the neuron lanes keep the same
  // neurons for up to N_PK consecutive cycles (low activity); the sum is the same integer in any order
  localparam int W_SL = (N_PK > 1) ? $clog2(N_PK) : 1;
  logic [N_PK-1:0]       g_v_q;
  logic [S_ROWS-1:0]     g_rv_q[N_PK];
  logic [W_RB-1:0]       g_row_q[N_PK][S_ROWS];
  logic [W_BAND-1:0]     g_band_q;
  logic [W_QP-1:0]       g_qp_q;  // the pass over the groups the reads come from (plane = N_PK * g_qp + slot)
  logic [W_SL-1:0]       j_q;  // slot being issued
  logic [W_PASS-1:0]     pass_q;

  assign sset = sset_q;
  assign scan_set_o = sset_q;

  // ---------------------------------------------------------------- dirty flags: find-first at or above the pointer, in two levels (timing)
  logic restart;  // a pass starts this cycle (the fetch begins at flag 0)
  logic [W_GI:0] ptr_eff;
  logic [N_SG-1:0] dmask;
  localparam int DB = 8;
  localparam int NBLK = (N_SG + DB - 1) / DB;
  logic [NBLK*DB-1:0] dpad;
  logic [NBLK-1:0] blk_any;
  logic [DB-1:0] blk_bits;
  int blk_first, in_first;
  logic [W_GRP-1:0] dirty_first;
  logic dirty_any;
  assign ptr_eff = restart ? '0 : ptr_q;
  always_comb begin
    for (int j = 0; j < N_SG; j++) dmask[j] = dirty_i[int'(sset)*N_SG+j] && (j >= int'(ptr_eff));
    dpad = '0;
    dpad[N_SG-1:0] = dmask;
    for (int b = 0; b < NBLK; b++) blk_any[b] = |dpad[b*DB+:DB];
    blk_first = 0;
    for (int b = NBLK - 1; b >= 0; b--) if (blk_any[b]) blk_first = b;
    blk_bits = dpad[blk_first*DB+:DB];
    in_first = 0;
    for (int j = DB - 1; j >= 0; j--) if (blk_bits[j]) in_first = j;
    dirty_first = W_GRP'(blk_first * DB + in_first);
  end
  assign dirty_any = |blk_any;

  // ---------------------------------------------------------------- arrival: the group read in the previous cycle
  logic [W_COUNT-1:0] words[ROWS_PER_GROUP];
  logic [W_COUNT-1:0] m_true;
  logic [W_BAND-1:0]  arr_band;
  logic [W_GB-W_BAND-1:0] arr_gib;  // group index inside its band
  always_comb begin
    m_true = '0;
    for (int w = 0; w < ROWS_PER_GROUP; w++) begin
      words[w] = scan_q_i[w*W_COUNT+:W_COUNT];
      m_true   = m_true | words[w];
    end
  end
  assign arr_band = arr_grp_q[W_GB-1-:W_BAND];
  assign arr_gib  = arr_grp_q[W_GB-W_BAND-1:0];

  // active rows of the arriving group per packed plane
  logic [ROWS_PER_GROUP-1:0] act[N_PK];
  logic [W_CN-1:0]           n_new[N_PK];
  always_comb begin
    for (int p = 0; p < N_PK; p++) begin
      n_new[p] = '0;
      for (int w = 0; w < ROWS_PER_GROUP; w++) begin
        act[p][w] = (int'(N_PK) * int'(qpass_q) + p < W_COUNT) ? words[w][(int'(N_PK)*int'(qpass_q)+p)%W_COUNT] : 1'b0;
        n_new[p]  = n_new[p] + W_CN'(act[p][w]);
      end
    end
  end

  logic all_empty, fits, arr_accept, band_ok, flush_need;
  always_comb begin
    all_empty = 1'b1;
    fits      = 1'b1;
    for (int p = 0; p < N_PK; p++) begin
      if (pk_cnt_q[p] != '0) all_empty = 1'b0;
      if (int'(pk_cnt_q[p]) + ROWS_PER_GROUP > CAP) fits = 1'b0;  // worst case (every row of the group active): the accept, and with it the next fetch, does not wait for the data
    end
  end
  assign band_ok    = all_empty || (arr_band == cur_band_q);
  assign arr_accept = arr_v_q && band_ok && fits;
  // flush: the next group is in another band, or the pass has fetched everything
  assign flush_need = (arr_v_q && !band_ok) || (fetch_done_q && !arr_v_q);

  // ---------------------------------------------------------------- issue: load the read buffer from a packer
  logic iss_last, rb_free, any_cand, load_rb, grp_busy, last_in_round;
  logic [N_PK-1:0] cand;
  logic [W_SL-1:0] j_next, j_first_v, j_first_c;
  always_comb begin
    any_cand = 1'b0;
    for (int p = 0; p < N_PK; p++) begin
      cand[p] = (int'(pk_cnt_q[p]) >= S_ROWS) || (flush_need && pk_cnt_q[p] != '0);
      if (cand[p]) any_cand = 1'b1;
    end
    // slot walk: the next valid slot after j, the first valid slot (of the group and of the candidates)
    last_in_round = 1'b1;
    j_next        = j_q;
    for (int p = N_PK - 1; p >= 0; p--) if (p > int'(j_q) && g_v_q[p]) begin
      j_next        = W_SL'(p);
      last_in_round = 1'b0;
    end
    j_first_v = '0;
    j_first_c = '0;
    for (int p = N_PK - 1; p >= 0; p--) begin
      if (g_v_q[p]) j_first_v = W_SL'(p);
      if (cand[p]) j_first_c = W_SL'(p);
    end
  end
  assign grp_busy = |g_v_q;
  assign iss_last = grp_busy && (pass_q == LAST_PASS) && last_in_round;
  assign rb_free  = !grp_busy || iss_last;
  assign load_rb  = rb_free && any_cand && scan_q;

  // next packer state: remove the rows moved to the read buffer, append the arriving rows
  logic [W_RB-1:0] pk_row_n[N_PK][CAP];
  logic [W_CN-1:0] pk_cnt_n[N_PK];
  always_comb begin
    for (int p = 0; p < N_PK; p++) begin
      int rem, base, k;
      rem = (load_rb && cand[p]) ? ((int'(pk_cnt_q[p]) >= S_ROWS) ? S_ROWS : int'(pk_cnt_q[p])) : 0;
      for (int i = 0; i < CAP; i++) pk_row_n[p][i] = (i + rem < CAP) ? pk_row_q[p][i+rem] : '0;
      base = int'(pk_cnt_q[p]) - rem;
      k    = 0;
      if (arr_accept) begin
        for (int w = 0; w < ROWS_PER_GROUP; w++) begin
          if (act[p][w]) begin
            if (base + k < CAP) pk_row_n[p][base+k] = {arr_gib, 2'(w)};
            k = k + 1;
          end
        end
      end
      pk_cnt_n[p] = W_CN'(base + k);
    end
  end

  logic [N_PK-1:0] pk_en;
  always_comb for (int p = 0; p < N_PK; p++) pk_en[p] = (load_rb && cand[p]) || (arr_accept && n_new[p] != '0);

  // ---------------------------------------------------------------- fetch control
  logic arr_free, can_fetch, fetch, blk_last, pass_idle, last_pass;
  assign blk_last  = (fgrp_q[LGD-1:0] == {LGD{1'b1}});
  assign arr_free  = !arr_v_q || arr_accept;
  assign can_fetch = scan_q && !fetch_done_q && !fin_q && arr_free;
  assign fetch     = can_fetch;
  // the pass needs a successor when an arriving group has a bit above its planes; such a group is kept, every other group is cleared as it arrives
  logic hi_bits;
  always_comb begin
    hi_bits = 1'b0;
    for (int b = 0; b < W_COUNT; b++) if (b >= N_PK * (int'(qpass_q) + 1) && m_true[b]) hi_bits = 1'b1;
  end
  assign last_pass = !more_q;
  assign scan_re_o = fetch;
  assign scan_clr_o = scan_qv_i && !hi_bits;
  assign scan_grp_o = fgrp_q;
  assign pass_idle  = scan_q && fetch_done_q && !arr_v_q && all_empty && !fin_q;
  assign busy_o     = scan_q || prime_q;
  assign done_o     = done_q;
  assign restart    = prime_q || (pass_idle && !last_pass);

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || abort_i) begin
      scan_q       <= 1'b0;
      fetch_done_q <= 1'b0;
      fin_q        <= 1'b0;
      fgrp_q       <= '0;
      ptr_q        <= '0;
      qpass_q      <= '0;
      more_q       <= 1'b0;
      done_q       <= 1'b0;
      arr_v_q      <= 1'b0;
      arr_grp_q    <= '0;
      cur_band_q   <= '0;
      g_v_q        <= '0;
      g_band_q     <= '0;
      g_qp_q       <= '0;
      j_q          <= '0;
      for (int p = 0; p < N_PK; p++) g_rv_q[p] <= '0;
      pass_q       <= '0;
      sset_q       <= 1'b0;
      prime_q      <= 1'b0;
      for (int p = 0; p < N_PK; p++) pk_cnt_q[p] <= '0;
    end else begin
      done_q  <= 1'b0;
      prime_q <= 1'b0;
      if (start_i && !scan_q && !prime_q) begin
        sset_q  <= ing_sel_i;
        prime_q <= 1'b1;
      end else if (prime_q) begin
        if (dirty_any) begin
          scan_q       <= 1'b1;
          fetch_done_q <= 1'b0;
          fin_q        <= 1'b0;
          qpass_q      <= '0;
          more_q       <= 1'b0;
          fgrp_q       <= W_GRP'(dirty_first) << LGD;
          ptr_q        <= (W_GI + 1)'(dirty_first) + (W_GI + 1)'(1);
        end else done_q <= 1'b1;  // no event this timestep: nothing to scan
      end else if (scan_q) begin
        // ------------------------------------------------ fetch
        if (fetch) begin
          arr_v_q   <= 1'b1;
          arr_grp_q <= fgrp_q;
          if (!blk_last) fgrp_q <= fgrp_q + W_GRP'(1);
          else if (dirty_any) begin
            fgrp_q <= W_GRP'(dirty_first) << LGD;
            ptr_q  <= (W_GI + 1)'(dirty_first) + (W_GI + 1)'(1);
          end else fetch_done_q <= 1'b1;
        end else if (arr_accept) arr_v_q <= 1'b0;
        if (fetch && arr_accept) arr_v_q <= 1'b1;
        // ------------------------------------------------ packers
        for (int p = 0; p < N_PK; p++) begin
          if (pk_en[p]) begin  // a packer is clocked only when rows arrive for its plane or a read leaves it
            pk_cnt_q[p] <= pk_cnt_n[p];
            for (int i = 0; i < CAP; i++) pk_row_q[p][i] <= pk_row_n[p][i];
          end
        end
        if (arr_accept) cur_band_q <= arr_band;
        if (scan_qv_i && hi_bits) more_q <= 1'b1;
        // ------------------------------------------------ read buffer and the analog passes
        if (grp_busy) begin
          if (!last_in_round) j_q <= j_next;
          else begin
            j_q <= j_first_v;
            if (pass_q != LAST_PASS) pass_q <= pass_q + W_PASS'(1);
            else begin
              pass_q <= '0;
              g_v_q  <= '0;
            end
          end
        end
        if (load_rb) begin
          g_v_q    <= cand;
          j_q      <= j_first_c;
          pass_q   <= '0;
          g_band_q <= cur_band_q;
          g_qp_q   <= qpass_q;
          for (int p = 0; p < N_PK; p++) begin
            if (cand[p]) begin
              for (int i = 0; i < S_ROWS; i++) begin
                g_row_q[p][i] <= (i < int'(pk_cnt_q[p])) ? pk_row_q[p][i] : '0;  // unused slots read as zero
                g_rv_q[p][i]  <= (i < int'(pk_cnt_q[p]));
              end
            end
          end
        end
        // ------------------------------------------------ pass / scan completion
        if (pass_idle) begin
          if (!last_pass) begin
            qpass_q      <= qpass_q + W_QP'(1);
            more_q       <= 1'b0;
            fetch_done_q <= 1'b0;
            fgrp_q       <= W_GRP'(dirty_first) << LGD;
            ptr_q        <= (W_GI + 1)'(dirty_first) + (W_GI + 1)'(1);
          end else begin
            fin_q <= 1'b1;
          end
        end
        if (fin_q && (!grp_busy || iss_last)) begin
          scan_q <= 1'b0;
          fin_q  <= 1'b0;
          done_q <= 1'b1;
        end
      end
    end
  end

  assign dirty_clr_o     = pass_idle && last_pass;
  assign dirty_clr_set_o = sset_q;
  assign rd_valid_o = grp_busy;
  assign rd_band_o  = g_band_q;
  assign row_sel_o  = W_BIT_IDX'(N_PK * int'(g_qp_q) + int'(j_q));
  assign pass_o     = W_PASS'(pass_q);
  assign rd_rv_o    = g_rv_q[j_q];
  always_comb begin
    for (int i = 0; i < S_ROWS; i++) rd_rows_o[i*W_RB+:W_RB] = g_row_q[j_q][i];
  end

  // ------------------------------------------------------------------ access counters (instrumentation: INSTRUMENT_EN = 0 builds none of them)
  if (INSTRUMENT_EN) begin : g_instr
    logic [W_STAT-1:0] active_q, allcols_q, plane_q, issued_q;
    logic [W_COUNT-1:0] seen_q;
    logic [W_STAT-1:0] n_nz;  // non-zero counters of the group that arrives
    always_comb begin
      n_nz = '0;
      for (int w = 0; w < ROWS_PER_GROUP; w++) if (words[w] != '0) n_nz = n_nz + STAT_ONE;
    end
    always_ff @(posedge clk_i) begin
      if (!rst_n_i || (start_i && !scan_q)) begin
        active_q  <= '0;
        allcols_q <= '0;
        plane_q   <= '0;
        issued_q  <= '0;
        seen_q    <= '0;
      end else begin
        if (arr_accept && qpass_q == '0) begin
          active_q <= active_q + n_nz;
          seen_q   <= seen_q | m_true;
        end
        if (load_rb) begin
          allcols_q <= allcols_q + W_STAT'($countones(cand));
          plane_q   <= plane_q + W_STAT'(W_WEIGHT) * W_STAT'($countones(cand));
        end
        if (grp_busy) issued_q <= issued_q + STAT_ONE;
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
    assign zero_groups_o   = '0;
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
  assign unused_ok = 1'b0;

  // ------------------------------------------------------------------ assertions (simulation only)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  initial begin
    if (S_ROWS < ROWS_PER_GROUP || $clog2(S_ROWS + 1) > $clog2(ROWS_PER_GROUP + 1)) $fatal(1, "plane_seq: the packed-row scan needs ROWS_PER_GROUP <= S_ROWS < 2^W_M (the 4 counters of a group are the 4 banks)");
    if (N_INPUTS / N_BANDS != 128) $fatal(1, "plane_seq: band size assumed 128 rows");
  end
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else begin
      if (start_i && (scan_q || prime_q)) begin
        $display("[ASSERT FAIL] %m: start while the scan is busy");
        fail_q <= 1'b1;
      end
      for (int p = 0; p < N_PK; p++) begin
        if (int'(pk_cnt_n[p]) > CAP) begin
          $display("[ASSERT FAIL] %m: packer %0d overflow", p);
          fail_q <= 1'b1;
        end
      end
      if (scan_q && fin_q && (!all_empty || arr_v_q)) begin
        $display("[ASSERT FAIL] %m: pass finished with rows left in the packers");
        fail_q <= 1'b1;
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
