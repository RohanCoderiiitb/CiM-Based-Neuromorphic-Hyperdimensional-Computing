// clk_gate.sv - a latch-based clock gate (the structure of an integrated clock-gating cell): the enable is held by a latch that is transparent while the clock is LOW, and the gated
// clock is clk & latch. The enable therefore cannot glitch the clock, and it must be stable before the rising edge, exactly like the D input of a flip-flop.
//
// This is the BEHAVIOURAL model, used by simulation, lint and the generic synthesis checks. The standard-cell flow (scripts/synth_ppa.py) replaces the module by the library's ICG cell
// (synth/icg_map.v, a techmap onto TLATNCAX2); the gate-level simulation uses tb/gl/icg_models.v, which is this same latch + AND.
// The gated clock is formed from `clk_i` by continuous assignments only, so every flip-flop clocked by it samples its inputs in the same active region as the ungated ones: no
// simulation race between the two clock domains in either simulator.
module clk_gate (
    input  logic clk_i,
    input  logic en_i,
    output logic gclk_o
);
  logic en_l;
  always_latch if (!clk_i) en_l = en_i;
  assign gclk_o = clk_i & en_l;
endmodule
