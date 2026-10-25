// icg_models.v - gate-level simulation model of the 45 nm library's integrated clock-gating cell, for the netlists that `clockgate` produces.
// Yosys' read_liberty cannot turn the cell's statetable into Verilog (cells_fast.v has no TLATNCAX*), so the cell is modelled here exactly as the library describes it:
//   a latch that is transparent while CK is LOW (statetable: CK = L -> EINT follows E; CK = H -> hold) and ECK = CK & EINT  ("clock_gating_integrated_cell : latch_posedge").
// The enable is therefore sampled on the falling edge and cannot glitch the clock; ECK rises with CK in the same time step, through continuous assignments only, so the flip-flops it
// clocks (which sample with non-blocking assignments, like every cell Yosys writes) see the same pre-edge values as the ungated ones: no race with the ungated domain.
// Used ONLY by scripts/synth_power.py; the RTL contains no clock gate (the enables are written as enables and the synthesis flow inserts the cells).
module TLATNCAX2 (
    input  CK,
    input  E,
    output ECK
);
  reg eint;
  always @(CK or E) if (!CK) eint = E;
  assign ECK = CK & eint;
endmodule
