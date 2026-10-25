// clk_gate_tree.sv - hierarchical clock gating for an array of N independently written words (counters, table rows).
//
// WHY A TREE. A clock gate costs energy every cycle whether it is enabled or not: its own clock pin toggles (about the energy of one flip-flop clock edge). N flat gates therefore cost
// N gate-clockings per cycle although at most one word is written per cycle (measured: 512 flat gates = 161 uW for count_mem alone). In a tree each gate's clock is its PARENT's gated
// clock, so a gate toggles only in cycles in which its parent is enabled: per write, about LEVELS x radix gate-clockings instead of N.
//
// Level k has ceil(N / 2^shift_k) gates; gate g of level k is enabled when  clr_i | (we_i & (addr_i >> shift_k) == g)  and takes the gated clock of gate (g >> (shift_(k-1) - shift_k))
// of level k-1 (level 0: clk_i). The last level (shift 0) has one gate per word: gclk_o[a] is the clock of word a. clr_i enables every gate (reset / bulk clear).
module clk_gate_tree #(
    parameter int N      = 512,
    parameter int LEVELS = 3
) (
    input  logic                        clk_i,
    input  logic                        clr_i,
    input  logic                        we_i,
    input  logic [$clog2(N)-1:0]        addr_i,
    output logic [N-1:0]                gclk_o
);
  localparam int B = $clog2(N);

  function automatic int shift_of(input int k);  // address bits below the index of a level-k gate
    shift_of = B - (B * (k + 1) + LEVELS - 1) / LEVELS;
  endfunction
  function automatic int count_of(input int k);  // gates in level k
    count_of = (N + (1 << shift_of(k)) - 1) >> shift_of(k);
  endfunction

  for (genvar k = 0; k < LEVELS; k++) begin : g_lvl
    localparam int SH = shift_of(k);
    localparam int CNT = count_of(k);
    logic [CNT-1:0] gclk;
    for (genvar g = 0; g < CNT; g++) begin : g_gate
      logic en;
      logic pclk;
      if (k == 0) begin : g_root
        assign pclk = clk_i;
      end else begin : g_child
        assign pclk = g_lvl[k-1].gclk[g>>(shift_of(k-1)-SH)];
      end
      assign en = clr_i | (we_i & ((addr_i >> SH) == B'(g)));
      clk_gate u_cg (
          .clk_i (pclk),
          .en_i  (en),
          .gclk_o(gclk[g])
      );
    end
  end

  assign gclk_o = g_lvl[LEVELS-1].gclk[N-1:0];
endmodule
