// count_mem.sv - block B. 512 counters x W_COUNT bits in FLIP-FLOPS (never ReRAM: written thousands of times per timestep).
//
// Per event: read-modify-write, pipelined in two stages
//   stage 1 (cycle after accept): read cnt[addr] (or FORWARD the value stage 2 is about to write) and add 1
//   stage 2 (next cycle)        : write cnt[addr]
// Back-to-back events to the SAME address hit the forwarding path (common in real data: median 3 events/address).
// `wipe_i` clears every counter in one cycle at the timestep boundary (allowed only when the pipeline is empty).
// `row_o` presents count bit-row b (bit b of every counter = 512 bits) combinationally; `row_nz_o` is its 512-bit OR.
module count_mem
  import cim_neurohdc_pkg::*;
(
    input  logic                   clk_i,
    input  logic                   rst_n_i,
    input  logic                   ev_valid_i,    // accepted event this cycle
    input  logic [W_ADDR-1:0]      ev_addr_i,
    input  logic                   wipe_i,
    input  logic [W_BIT_IDX-1:0]   row_sel_i,     // which count bit-row (0 .. W_COUNT-1)
    output logic [N_INPUTS-1:0]    row_o,         // bit `row_sel_i` of every counter
    output logic                   row_nz_o,      // row_o != 0
    output logic [N_INPUTS-1:0]    active_o,      // counter != 0 (instrumentation: active addresses)
    output logic                   busy_o,        // an event is still in the read-modify-write pipeline
    output logic                   fwd_o,         // stat pulse: stage 1 used the forwarded value
    input  logic                   chk_i,         // assertion strobe: compare the counter sum with chk_expected_i
    input  logic [W_NEVENTS-1:0]   chk_expected_i,
    output logic                   assert_fail_o
);
  localparam logic [W_COUNT-1:0] COUNT_MAX = '1;

  logic [W_COUNT-1:0] cnt_q[N_INPUTS];

  logic                s1_valid_q;
  logic [W_ADDR-1:0]   s1_addr_q;
  logic                s2_valid_q;
  logic [W_ADDR-1:0]   s2_addr_q;
  logic [W_COUNT-1:0]  s2_val_q;
  logic                fwd_hit;
  logic [W_COUNT-1:0]  s1_cur;

  assign fwd_hit = s1_valid_q && s2_valid_q && (s2_addr_q == s1_addr_q);
  assign s1_cur  = fwd_hit ? s2_val_q : cnt_q[s1_addr_q];
  assign busy_o  = s1_valid_q || s2_valid_q;
  assign fwd_o   = fwd_hit;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || wipe_i) begin
      for (int a = 0; a < N_INPUTS; a++) cnt_q[a] <= '0;
      s1_valid_q <= 1'b0;
      s2_valid_q <= 1'b0;
      s1_addr_q  <= '0;
      s2_addr_q  <= '0;
      s2_val_q   <= '0;
    end else begin
      s1_valid_q <= ev_valid_i;
      s1_addr_q  <= ev_addr_i;
      s2_valid_q <= s1_valid_q;
      s2_addr_q  <= s1_addr_q;
      s2_val_q   <= s1_cur + W_COUNT'(1);
      if (s2_valid_q) cnt_q[s2_addr_q] <= s2_val_q;
    end
  end

  for (genvar a = 0; a < N_INPUTS; a++) begin : g_row
    assign row_o[a]    = cnt_q[a][row_sel_i];
    assign active_o[a] = |cnt_q[a];
  end
  assign row_nz_o = |row_o;

  // ------------------------------------------------------------------ assertions (simulation only; never disabled)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  function automatic logic [W_NEVENTS-1:0] sum_counters();
    logic [W_NEVENTS-1:0] acc;
    acc = '0;
    for (int a = 0; a < N_INPUTS; a++) acc = acc + W_NEVENTS'(cnt_q[a]);
    return acc;
  endfunction

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else begin
      if (s1_valid_q && (s1_cur == COUNT_MAX)) begin
        $display("[ASSERT FAIL] %m: counter %0d would exceed its maximum %0d", s1_addr_q, COUNT_MAX);
        fail_q <= 1'b1;
      end
      if (wipe_i && busy_o) begin
        $display("[ASSERT FAIL] %m: wipe while an event is still in the pipeline");
        fail_q <= 1'b1;
      end
      if (chk_i) begin
        if (busy_o || sum_counters() != chk_expected_i) begin
          $display("[ASSERT FAIL] %m: counters sum to %0d, expected %0d events (busy=%0b)", sum_counters(), chk_expected_i, busy_o);
          fail_q <= 1'b1;
        end
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
