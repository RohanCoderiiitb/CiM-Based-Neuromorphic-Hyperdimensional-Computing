// count_mem.sv - block B. 512 event counters x W_COUNT bits in ONE single-port SRAM macro (count_sram), double-pumped (read first half, write second half of every cycle).
// (Optimisation item 3. It was 5,632 flip-flops behind a 512-way read multiplexer; the flip-flops, their clock tree and the multiplexer are gone.)
//
// INGEST. One event per cycle, a two-stage pipeline exactly as before: the event address is registered (stage 1) and presented to the macro's read port; at the next edge the macro registers the
// counter and stage 2 holds the address; in that cycle the counter plus one is written back (second half of the cycle). busy_o = either stage valid, as before.
// SCAN (plane_seq). The sequencer reads the 512 counters once per timestep through the same read port (`scan_re_i` / `scan_addr_i`; the word is returned in q_o in the next cycle with
// `scan_qv_o`), and each word it reads is CLEARED in the second half of the cycle in which it arrives: the timestep wipe is a side effect of the scan - there is no bulk clear.
// SWEEP. After reset and after `flush_i` (abort) the 512 words are cleared by a sweep (`sweep_q`, one word per cycle, 512 cycles); ready_o is low meanwhile and the controller accepts no event.
// There is no bulk-clear input any more: `wipe_i` is accepted for interface compatibility and ignored (the scan has already cleared every word).
import cim_neurohdc_pkg::N_INPUTS;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_COUNT;
import cim_neurohdc_pkg::W_NEVENTS;

module count_mem (
    input  logic               clk_i,
    input  logic               rst_n_i,
    input  logic               ev_valid_i,      // accepted event this cycle
    input  logic [ W_ADDR-1:0] ev_addr_i,
    input  logic               wipe_i,          // ignored: the scan clears what it reads
    input  logic               flush_i,         // abort: drop the pipeline and clear all counters (sweep)
    // scan port
    input  logic               scan_re_i,
    input  logic [ W_ADDR-1:0] scan_addr_i,
    output logic [W_COUNT-1:0] q_o,             // the word read in the previous cycle (scan)
    output logic               scan_qv_o,       // q_o is a scan word
    output logic               busy_o,          // an event is still in the read-modify-write pipeline
    output logic               ready_o,         // no sweep in progress
    output logic               fwd_o,           // stat pulse: stage 1 and stage 2 hold the same address
    input  logic               chk_i,           // assertion strobe: compare the sum of the counters scanned with chk_expected_i
    input  logic [W_NEVENTS-1:0] chk_expected_i,
    output logic               assert_fail_o
);
  logic               s1_valid_q;
  logic [ W_ADDR-1:0] s1_addr_q;
  logic               s2_valid_q;
  logic [ W_ADDR-1:0] s2_addr_q;
  logic               scan_re_q;
  logic [ W_ADDR-1:0] scan_addr_q;
  logic               sweep_q;
  logic [ W_ADDR-1:0] sweep_cnt_q;

  assign busy_o  = s1_valid_q || s2_valid_q;
  assign ready_o = !sweep_q;
  assign fwd_o   = s1_valid_q && s2_valid_q && (s2_addr_q == s1_addr_q);

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || flush_i) begin
      s1_valid_q  <= 1'b0;
      s2_valid_q  <= 1'b0;
      s1_addr_q   <= '0;
      s2_addr_q   <= '0;
      scan_re_q   <= 1'b0;
      scan_addr_q <= '0;
    end else begin
      s1_valid_q  <= ev_valid_i;
      s1_addr_q   <= ev_addr_i;
      s2_valid_q  <= s1_valid_q;
      s2_addr_q   <= s1_addr_q;
      scan_re_q   <= scan_re_i;
      scan_addr_q <= scan_addr_i;
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || flush_i) begin
      sweep_q     <= 1'b1;
      sweep_cnt_q <= '0;
    end else if (sweep_q) begin
      sweep_cnt_q <= sweep_cnt_q + W_ADDR'(1);
      if (sweep_cnt_q == W_ADDR'(N_INPUTS - 1)) sweep_q <= 1'b0;
    end
  end

  // ------------------------------------------------------------------ the macro: read port first half, write port second half
  logic [W_COUNT-1:0] rdata;
  logic               re;
  logic [ W_ADDR-1:0] ra;
  logic               we;
  logic [ W_ADDR-1:0] wa;
  logic [W_COUNT-1:0] wd;

  assign re = scan_re_i || s1_valid_q;
  assign ra = scan_re_i ? scan_addr_i : s1_addr_q;
  // write sources are exclusive in time: the sweep (after reset / abort), the scan's clear of the word it just read, the ingest write-back
  always_comb begin
    we = 1'b0;
    wa = s2_addr_q;
    wd = rdata + W_COUNT'(1);
    if (sweep_q) begin
      we = 1'b1;
      wa = sweep_cnt_q;
      wd = '0;
    end else if (scan_re_q) begin
      we = 1'b1;
      wa = scan_addr_q;
      wd = '0;
    end else if (s2_valid_q) begin
      we = 1'b1;
    end
  end

  count_sram u_sram (
      .clk_i(clk_i),
      .re_i (re),
      .ra_i (ra),
      .we_i (we),
      .wa_i (wa),
      .wd_i (wd),
      .q_o  (rdata)
  );
  assign q_o       = rdata;
  assign scan_qv_o = scan_re_q;

  logic unused_ok;
  assign unused_ok = &{1'b0, wipe_i, chk_i, chk_expected_i};

  // ------------------------------------------------------------------ assertions (simulation only; never disabled)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  logic [W_NEVENTS-1:0] scan_sum_q;
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      fail_q     <= 1'b0;
      scan_sum_q <= '0;
    end else begin
      if (s2_valid_q && !sweep_q && !scan_re_q && (rdata == '1)) begin
        $display("[ASSERT FAIL] %m: counter %0d would exceed its maximum", s2_addr_q);
        fail_q <= 1'b1;
      end
      if (ev_valid_i && sweep_q) begin
        $display("[ASSERT FAIL] %m: event accepted during the post-reset / post-abort sweep");
        fail_q <= 1'b1;
      end
      if (scan_re_i && (s1_valid_q || s2_valid_q)) begin
        $display("[ASSERT FAIL] %m: scan read while an event is still in the pipeline");
        fail_q <= 1'b1;
      end
      if (scan_re_q) scan_sum_q <= scan_sum_q + W_NEVENTS'(rdata);
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
