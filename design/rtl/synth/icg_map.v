// icg_map.v - techmap file of the standard-cell flow: the behavioural latch-based clk_gate (rtl/common/clk_gate.sv) becomes the 45 nm library's integrated clock-gating cell.
// Pins of TLATNCAX2: CK (clock), E (enable), ECK (gated clock). Used by scripts/synth_ppa.py between `hierarchy` and `flatten`.
(* blackbox *)
module TLATNCAX2 (input CK, input E, output ECK);
endmodule

module \clk_gate (input clk_i, input en_i, output gclk_o);
  TLATNCAX2 u_icg (.CK(clk_i), .E(en_i), .ECK(gclk_o));
endmodule
