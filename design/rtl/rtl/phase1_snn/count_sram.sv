// count_sram.sv - BEHAVIOURAL MODEL of ONE BANK of the count-memory SRAM (optimisation item 3, banked in the third pass): N_BANK_WORDS words x W_COUNT bits, ONE 6T array with ONE port, DOUBLE-PUMPED.
//
// A single-port array cannot read and write in the same clock cycle, and the ingest path needs both (read the counter, write it back plus one, one event per bank per cycle). The port is therefore used
// twice per cycle: the READ takes the first half (address `ra_i` is captured on the rising edge, `q_o` is registered on it) and the WRITE takes the second half (`wa_i` / `wd_i` / `we_i` are
// captured on the FALLING edge). Inside the macro the two addresses share the array's one decoder, selected by the clock level; at the 100 MHz clock a half cycle is 5 ns against the
// 0.3 - 0.5 ns access time of a 45 nm array of this size (CACTI, synth/macro/count_sram.*), so the array runs far inside its capability. A write at the falling edge of cycle k is seen by a read
// captured at the rising edge of cycle k+1: a counter is updated 0.5 cycle after its read data is registered, which makes back-to-back events to the same address safe with no forwarding.
//
// The 512 counters are split over N_COUNT_BANKS (4) such banks by the low address bits (count_mem): each bank is 128 words, the 256 B CACTI point (area, energy per access and leakage of `sign_sram`'s size).
//
// Under SYNTHESIS this module is a BLACKBOX (like cim_macro): its LEF, Liberty (timing, leakage) and energy come from synth/opt/gen_macros.py (CACTI numbers, tagged [ASSUM]).
import cim_neurohdc_pkg::N_BANK_WORDS;
import cim_neurohdc_pkg::W_BANK_ADDR;
import cim_neurohdc_pkg::W_COUNT;

`ifdef SYNTHESIS
(* blackbox *)
module count_sram (
    input  logic                   clk_i,
    input  logic                   re_i,
    input  logic [W_BANK_ADDR-1:0] ra_i,
    input  logic                   we_i,
    input  logic [W_BANK_ADDR-1:0] wa_i,
    input  logic [   W_COUNT-1:0]  wd_i,
    output logic [   W_COUNT-1:0]  q_o
);
endmodule
`else
module count_sram (
    input  logic                   clk_i,
    input  logic                   re_i,   // read: capture mem[ra_i] on the rising edge
    input  logic [W_BANK_ADDR-1:0] ra_i,
    input  logic                   we_i,   // write: mem[wa_i] <= wd_i on the falling edge
    input  logic [W_BANK_ADDR-1:0] wa_i,
    input  logic [   W_COUNT-1:0]  wd_i,
    output logic [   W_COUNT-1:0]  q_o
);
  logic [W_COUNT-1:0] mem[N_BANK_WORDS];
  logic [W_COUNT-1:0] q_q;
  always_ff @(posedge clk_i) if (re_i) q_q <= mem[ra_i];
  always_ff @(negedge clk_i) if (we_i) mem[wa_i] <= wd_i;
  assign q_o = q_q;
endmodule
`endif
