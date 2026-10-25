// count_sram.sv - BEHAVIOURAL MODEL of the count-memory SRAM macro (optimisation item 3): 512 words x W_COUNT bits, ONE 6T array with ONE port, DOUBLE-PUMPED.
//
// A single-port array cannot read and write in the same clock cycle, and the ingest path needs both (read the counter, write it back plus one, one event per cycle). The port is therefore used
// twice per cycle: the READ takes the first half (address `ra_i` is captured on the rising edge, `q_o` is registered on it) and the WRITE takes the second half (`wa_i` / `wd_i` / `we_i` are
// captured on the FALLING edge). Inside the macro the two addresses share the array's one decoder, selected by the clock level; at the 100 MHz clock a half cycle is 5 ns against the
// 0.5 - 0.8 ns access time of a 1 kB 45 nm array (CACTI, synth/macro/count_sram.*), so the array runs far inside its capability. A write at the falling edge of cycle k is seen by a read
// captured at the rising edge of cycle k+1: a counter is updated 0.5 cycle after its read data is registered, which makes back-to-back events to the same address safe with no forwarding.
//
// Under SYNTHESIS this module is a BLACKBOX (like cim_macro): its LEF, Liberty (timing, leakage) and energy come from synth/analog_macros.py (CACTI numbers, tagged [ASSUM]).
import cim_neurohdc_pkg::N_INPUTS;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_COUNT;

`ifdef SYNTHESIS
(* blackbox *)
module count_sram (
    input  logic               clk_i,
    input  logic               re_i,
    input  logic [W_ADDR-1:0]  ra_i,
    input  logic               we_i,
    input  logic [W_ADDR-1:0]  wa_i,
    input  logic [W_COUNT-1:0] wd_i,
    output logic [W_COUNT-1:0] q_o
);
endmodule
`else
module count_sram (
    input  logic               clk_i,
    input  logic               re_i,   // read: capture mem[ra_i] on the rising edge
    input  logic [W_ADDR-1:0]  ra_i,
    input  logic               we_i,   // write: mem[wa_i] <= wd_i on the falling edge
    input  logic [W_ADDR-1:0]  wa_i,
    input  logic [W_COUNT-1:0] wd_i,
    output logic [W_COUNT-1:0] q_o
);
  logic [W_COUNT-1:0] mem[N_INPUTS];
  logic [W_COUNT-1:0] q_q;
  always_ff @(posedge clk_i) if (re_i) q_q <= mem[ra_i];
  always_ff @(negedge clk_i) if (we_i) mem[wa_i] <= wd_i;
  assign q_o = q_q;
endmodule
`endif
