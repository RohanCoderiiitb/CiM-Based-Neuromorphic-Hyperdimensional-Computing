// count_mem.sv - block B. 512 event counters x W_COUNT bits, LANE-PRIVATE: every input lane has its own copy of the counter array, the count of an address is the SUM of its N_LANES lane
// counters. Two sets (ping-pong: the ingest side writes one set while the scan side reads and clears the other); a lane's array of one set is N_COUNT_BANKS single-port SRAM macros
// (count_sram, 128 words each, bank = low address bits), every macro DOUBLE-PUMPED (read first half, write second half of a cycle).
//
// INGEST. Lane k never meets another lane: an accepted event reads its own counter at once (the one bank the address selects; the SRAM registers the address); in the next cycle (s2) the counter + 1 is computed
//   over a FULL cycle and registered (s3); s3 writes it back in the second half of its cycle (only wires between the s3 register and the macro's falling-edge write port).
//   No queue, no dispatch, no merge, no back-pressure: N_LANES events are taken EVERY cycle, and an event address reaches one register and the address pins of one lane's macros.
//   Hazard: an event right behind an event to the same counter in its lane reads the counter before that write lands -> it takes the value from s3 instead (s2_f). Two cycles apart is safe:
//   the write (falling edge) precedes the read capture (rising edge) of the same cycle.
//   dirty: the flag of every counter block (N_DIRTY_GS groups) that received an event, per set; the registers are clocked only when a flag changes.
// SCAN (plane_seq). The sequencer reads one GROUP (row `scan_grp_i` of every bank of every lane of set `scan_set_i`) per cycle; the next cycle q_o holds the group's N_COUNT_BANKS counts
//   (lane sums) with `scan_qv_o`. In that cycle the sequencer says with `scan_clr_i` whether the group is finished (no count bit is left for a later pass); a finished group is cleared in
//   the second half of the following cycle - only the lane counters that are not zero are written. The timestep wipe is a side effect of the scan.
// SWEEP. After reset and after `flush_i` (abort) all macros are cleared by a sweep (one row per cycle); ready_o is low meanwhile and the controller accepts no event.
// Address and data wires of a lane's macros are zero when that lane does not access them; the scan adders see zeros outside a scan.
import cim_neurohdc_pkg::LB_COUNT;
import cim_neurohdc_pkg::N_BANK_WORDS;
import cim_neurohdc_pkg::N_COUNT_BANKS;
import cim_neurohdc_pkg::N_DIRTY_GS;
import cim_neurohdc_pkg::N_LANES;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_BANK_ADDR;
import cim_neurohdc_pkg::W_COUNT;
import cim_neurohdc_pkg::W_NEVENTS;

module count_mem #(
    localparam int N_SG = N_BANK_WORDS / N_DIRTY_GS  // dirty flags per counter set
) (
    input  logic                       clk_i,
    input  logic                       rst_n_i,
    input  logic [      N_LANES-1:0]   ev_valid_i,      // accepted events this cycle (a prefix of the lanes)
    input  logic [N_LANES*W_ADDR-1:0]  ev_addr_i,
    input  logic                       wipe_i,          // ignored: the scan clears what it reads
    input  logic                       flush_i,         // abort: drop the pipeline and clear all counters (sweep)
    input  logic                       ing_sel_i,       // counter set the ingest side uses (ping-pong: the scan works on the other one)
    input  logic                       scan_set_i,      // counter set the scan reads
    // scan port
    input  logic                       scan_re_i,       // read one whole group: row `scan_grp_i` of every bank
    input  logic [W_BANK_ADDR-1:0]     scan_grp_i,
    output logic [N_COUNT_BANKS*W_COUNT-1:0] q_o,       // the group read in the previous cycle (word w = bank w = sum of the lane counters)
    output logic                       scan_qv_o,       // q_o is a new scan group (one cycle after its scan_re_i)
    input  logic                       scan_clr_i,      // with scan_qv_o: the group in q_o is finished, clear it
    output logic [2*N_SG-1:0]          dirty_o,         // per counter set: the counter blocks that received an event since the set was last cleared
    input  logic                       dirty_clr_i,     // the scan of set dirty_clr_set_i is complete: clear its flags
    input  logic                       dirty_clr_set_i,
    output logic                       busy_o,          // an event is still in the read-modify-write pipeline
    output logic                       ready_o,         // no sweep in progress
    output logic                       fwd_o,           // stat pulse of the queued design (always 0: nothing is merged here)
    input  logic                       chk_i,           // assertion strobe: compare the sum of the counters scanned with chk_expected_i
    input  logic [W_NEVENTS-1:0]       chk_expected_i,
    output logic                       assert_fail_o
);
  localparam int NB = N_COUNT_BANKS;
  localparam int NL = N_LANES;
  localparam int LGD = $clog2(N_DIRTY_GS);
  localparam int W_SG = $clog2(N_SG);

  // a + 1 with PARALLEL-PREFIX carries (this sits between the SRAM read data and its write data inside the half cycle of the double-pumped port)
  function automatic logic [W_COUNT-1:0] inc1(input logic [W_COUNT-1:0] a);
    logic [W_COUNT-1:0] m;
    for (int i = 0; i < W_COUNT; i++) begin
      m       = (W_COUNT'(1) << i) - W_COUNT'(1);
      inc1[i] = a[i] ^ ((a & m) == m);  // carry into bit i: all lower bits are 1
    end
  endfunction
  function automatic logic [LB_COUNT-1:0] bank_of(input logic [W_ADDR-1:0] a);
    bank_of = a[LB_COUNT-1:0];
  endfunction
  function automatic logic [W_BANK_ADDR-1:0] idx_of(input logic [W_ADDR-1:0] a);
    idx_of = a[W_ADDR-1:LB_COUNT];
  endfunction

  logic                   sweep_q;
  logic [W_BANK_ADDR-1:0] sweep_cnt_q;

  // ------------------------------------------------------------------ the two pipeline stages of every lane: stage (read) and s2 (write back)
  // the read is issued straight from the accepted event (the SRAM registers its own address): no stage register in front of the macros
  logic [NL-1:0]      st_v_q, s2_v_q, s2_f_q, s3_v_q;
  logic [W_ADDR-1:0]  st_a_q[NL];
  assign st_v_q = ev_valid_i;
  for (genvar k = 0; k < NL; k++) begin : g_st
    assign st_a_q[k] = ev_addr_i[k*W_ADDR+:W_ADDR];
  end
  logic [W_ADDR-1:0]  s2_a_q[NL];
  logic [W_ADDR-1:0]  s3_a_q[NL];
  logic [W_COUNT-1:0] s3_d_q[NL];
  logic [W_COUNT-1:0] sum[NL];
  always_ff @(posedge clk_i) begin
    if (!rst_n_i || flush_i) begin
      s2_v_q <= '0;
      s2_f_q <= '0;
      s3_v_q <= '0;
      for (int k = 0; k < NL; k++) begin
        s2_a_q[k] <= '0;
        s3_a_q[k] <= '0;
        s3_d_q[k] <= '0;
      end
    end else begin
      if ((|st_v_q) || (|s2_v_q)) s2_v_q <= st_v_q;
      if ((|st_v_q) || (|s2_f_q)) for (int k = 0; k < NL; k++) s2_f_q[k] <= st_v_q[k] && s2_v_q[k] && (s2_a_q[k] == st_a_q[k]);
      if ((|s2_v_q) || (|s3_v_q)) s3_v_q <= s2_v_q;
      for (int k = 0; k < NL; k++) begin
        if (st_v_q[k]) s2_a_q[k] <= st_a_q[k];
        if (s2_v_q[k]) begin
          s3_a_q[k] <= s2_a_q[k];
          s3_d_q[k] <= sum[k];
        end
      end
    end
  end
  assign busy_o  = (|s2_v_q) || (|s3_v_q);
  assign ready_o = !sweep_q;
  assign fwd_o   = 1'b0;

  // ------------------------------------------------------------------ dirty flags: one per block of N_DIRTY_GS groups, per set; clocked only when a flag changes
  // PER LANE: a group scan reads only the lanes that received an event in its block (a lane that did not holds zeros there)
  logic [N_SG-1:0] dirty_q[2][NL];
  logic [N_SG-1:0] set_mask[NL];
  logic [NL-1:0]   new_any;
  logic [N_SG-1:0] dirty_or[2];
  always_comb begin
    for (int k = 0; k < NL; k++) begin
      set_mask[k] = '0;
      if (s2_v_q[k]) set_mask[k][W_SG'(idx_of(s2_a_q[k]) >> LGD)] = 1'b1;
      new_any[k] = |(set_mask[k] & ~dirty_q[ing_sel_i][k]);
    end
    for (int st = 0; st < 2; st++) begin
      dirty_or[st] = '0;
      for (int k = 0; k < NL; k++) dirty_or[st] = dirty_or[st] | dirty_q[st][k];
    end
  end
  always_ff @(posedge clk_i) begin
    if (!rst_n_i || flush_i) begin
      for (int st = 0; st < 2; st++) for (int k = 0; k < NL; k++) dirty_q[st][k] <= '0;
    end else begin
      for (int k = 0; k < NL; k++) if (new_any[k]) dirty_q[ing_sel_i][k] <= dirty_q[ing_sel_i][k] | set_mask[k];
      if (dirty_clr_i) for (int k = 0; k < NL; k++) dirty_q[dirty_clr_set_i][k] <= '0;
    end
  end
  assign dirty_o = {dirty_or[1], dirty_or[0]};
  logic [NL-1:0] lsel;  // lanes the group scan reads
  always_comb for (int k = 0; k < NL; k++) lsel[k] = dirty_q[scan_set_i][k][W_SG'(scan_grp_i >> LGD)];

  // ------------------------------------------------------------------ scan registers, the clear of a finished group, sweep
  logic                   scan_re_q, scan_set_q, scan_act_q;
  logic [NL-1:0]          lv_q;  // lanes read by the group scan in q_o
  logic [W_BANK_ADDR-1:0] scan_grp_q;
  logic                   clr_q, clr_set_q;
  logic [W_BANK_ADDR-1:0] clr_grp_q;
  logic [NB-1:0]          nz_q[NL];  // lane counters of the group to clear that are not zero
  logic [W_COUNT-1:0]     rdata[2][NL][NB];
  always_ff @(posedge clk_i) begin
    if (!rst_n_i || flush_i) begin
      scan_re_q  <= 1'b0;
      scan_grp_q <= '0;
      scan_set_q <= 1'b0;
      scan_act_q <= 1'b0;
      lv_q       <= '0;
      clr_q      <= 1'b0;
      clr_set_q  <= 1'b0;
      clr_grp_q  <= '0;
      for (int k = 0; k < NL; k++) nz_q[k] <= '0;
    end else begin
      if (scan_re_i || scan_re_q) scan_re_q <= scan_re_i;
      if (scan_re_i) begin
        scan_grp_q <= scan_grp_i;
        scan_set_q <= scan_set_i;
        scan_act_q <= 1'b1;
        lv_q       <= lsel;
      end else if (dirty_clr_i) scan_act_q <= 1'b0;
      if (clr_q || (scan_re_q && scan_clr_i)) clr_q <= scan_re_q && scan_clr_i;
      if (scan_re_q && scan_clr_i) begin
        clr_set_q <= scan_set_q;
        clr_grp_q <= scan_grp_q;
        for (int k = 0; k < NL; k++) for (int b = 0; b < NB; b++) nz_q[k][b] <= lv_q[k] && (rdata[scan_set_q][k][b] != '0);
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || flush_i) begin
      sweep_q     <= 1'b1;
      sweep_cnt_q <= '0;
    end else if (sweep_q) begin
      sweep_cnt_q <= sweep_cnt_q + W_BANK_ADDR'(1);
      if (sweep_cnt_q == W_BANK_ADDR'(N_BANK_WORDS - 1)) sweep_q <= 1'b0;
    end
  end

  // ------------------------------------------------------------------ ONE incrementer per lane, on the counter the lane read from the ingest set (or the value s3 is writing: hazard)
  logic [W_COUNT-1:0] rd_ing[NL];
  always_comb begin
    for (int k = 0; k < NL; k++) begin
      rd_ing[k] = s2_f_q[k] ? s3_d_q[k] : (s2_v_q[k] ? rdata[ing_sel_i][k][bank_of(s2_a_q[k])] : '0);
      sum[k]    = inc1(rd_ing[k]);
    end
  end

  // ------------------------------------------------------------------ the macros: set x lane x bank
  for (genvar st = 0; st < 2; st++) begin : g_set
    logic ing_in, scan_hit, clr_w;
    assign ing_in   = (ing_sel_i == 1'(st));
    assign scan_hit = scan_re_i && (scan_set_i == 1'(st));  // a group scan hits every bank of the lanes it reads
    assign clr_w    = clr_q && (clr_set_q == 1'(st)) && !sweep_q;
    for (genvar k = 0; k < NL; k++) begin : g_lane
      logic                   l_r, l_w;
      logic [W_BANK_ADDR-1:0] ra, wa;
      logic [   W_COUNT-1:0]  wd;
      assign l_r = ing_in && st_v_q[k];
      assign l_w = ing_in && s3_v_q[k] && !sweep_q && !clr_w;
      // one address / data bus per lane and set, zero when the lane does not use it; write sources are exclusive in time (sweep, the scan's clear, the ingest write-back)
      assign ra  = (scan_hit && lsel[k]) ? scan_grp_i : (l_r ? idx_of(st_a_q[k]) : '0);
      assign wa  = sweep_q ? sweep_cnt_q : (clr_w ? clr_grp_q : (l_w ? idx_of(s3_a_q[k]) : '0));
      assign wd  = l_w ? s3_d_q[k] : '0;
      for (genvar b = 0; b < NB; b++) begin : g_bank
        logic re, we;
        assign re = (scan_hit && lsel[k]) || (l_r && bank_of(st_a_q[k]) == LB_COUNT'(b));
        assign we = sweep_q || (clr_w && nz_q[k][b]) || (l_w && bank_of(s3_a_q[k]) == LB_COUNT'(b));
        count_sram u_sram (
            .clk_i(clk_i),
            .re_i (re),
            .ra_i (ra),
            .we_i (we),
            .wa_i (wa),
            .wd_i (wd),
            .q_o  (rdata[st][k][b])
        );
      end
    end
  end

  // ------------------------------------------------------------------ scan data: the count of an address is the sum of its lane counters
  logic [W_COUNT+1:0] gsum[NB];
  always_comb begin
    for (int b = 0; b < NB; b++) begin
      gsum[b] = '0;
      for (int k = 0; k < NL; k++) gsum[b] = gsum[b] + (W_COUNT + 2)'((scan_act_q && lv_q[k]) ? rdata[scan_set_q][k][b] : '0);
      q_o[b*W_COUNT+:W_COUNT] = gsum[b][W_COUNT-1:0];
    end
  end
  assign scan_qv_o = scan_re_q;

  logic unused_ok;
  assign unused_ok = &{1'b0, wipe_i, chk_i, chk_expected_i};

  // ------------------------------------------------------------------ assertions (simulation only; never disabled)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  logic [W_NEVENTS-1:0] scan_sum_q, grp_sum;
  logic                 grp_ovf, lane_ovf;
  always_comb begin
    grp_sum  = '0;
    grp_ovf  = 1'b0;
    lane_ovf = 1'b0;
    for (int b = 0; b < NB; b++) begin
      grp_sum = grp_sum + W_NEVENTS'(gsum[b]);
      if (gsum[b][W_COUNT+1:W_COUNT] != '0) grp_ovf = 1'b1;
    end
    for (int k = 0; k < NL; k++) if (s2_v_q[k] && !sweep_q && rd_ing[k] == {W_COUNT{1'b1}}) lane_ovf = 1'b1;
  end
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      fail_q     <= 1'b0;
      scan_sum_q <= '0;
    end else begin
      if (lane_ovf || (scan_re_q && grp_ovf)) begin
        $display("[ASSERT FAIL] %m: a counter exceeds its maximum");
        fail_q <= 1'b1;
      end
      if ((|ev_valid_i) && sweep_q) begin
        $display("[ASSERT FAIL] %m: event accepted during the post-reset / post-abort sweep");
        fail_q <= 1'b1;
      end
      for (int k = 1; k < NL; k++) begin
        if (ev_valid_i[k] && !ev_valid_i[k-1]) begin
          $display("[ASSERT FAIL] %m: lane %0d accepted without lane %0d", k, k - 1);
          fail_q <= 1'b1;
        end
      end
      if (scan_re_i && busy_o && (scan_set_i == ing_sel_i)) begin
        $display("[ASSERT FAIL] %m: scan read of the counter set that ingest is writing");
        fail_q <= 1'b1;
      end
      if (scan_clr_i && !scan_re_q) begin
        $display("[ASSERT FAIL] %m: scan_clr_i without a group in q_o");
        fail_q <= 1'b1;
      end
      if (scan_re_q && scan_clr_i) scan_sum_q <= scan_sum_q + grp_sum;  // a group is read by several passes and cleared once
      if (chk_i) begin
        if (scan_sum_q != chk_expected_i) begin
          $display("[ASSERT FAIL] %m: counters scanned sum to %0d, expected %0d events", scan_sum_q, chk_expected_i);
          fail_q <= 1'b1;
        end
        scan_sum_q <= '0;
      end
      if (flush_i) scan_sum_q <= '0;
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
