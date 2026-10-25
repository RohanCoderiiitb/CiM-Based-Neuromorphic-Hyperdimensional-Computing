// clk_gate_icg.v - the clock gate of rtl/common/clk_gate.sv as the PDK's integrated clock-gating cell, instantiated structurally.
// For the Genus / Innovus flow (prepare_rtl.py puts this file in place of rtl/common/clk_gate.sv): the simulation model of clk_gate.sv is a latch + AND, which a synthesis tool would
// map onto a latch and a gate, not onto the ICG; Yosys' flow does the same replacement with synth/icg_map.v. TLATNCAX2 (gsclib045: CK, E, ECK; latch transparent while CK is low,
// clock_gating_integrated_cell : latch_posedge) is the cell that was used for the pre-route numbers. Same ports as clk_gate.sv.
module clk_gate (
    input  wire clk_i,
    input  wire en_i,
    output wire gclk_o
);
  TLATNCAX2 u_icg (
      .CK (clk_i),
      .E  (en_i),
      .ECK(gclk_o)
  );
endmodule
