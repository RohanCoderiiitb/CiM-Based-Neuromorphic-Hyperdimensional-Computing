// weight_load.sv - block F. Shift-in path that writes the weight image into the crossbar once at startup (slow is fine).
// Words are W_WL_WORD = 32 bits, macro-major: macro 0 addresses 0..511, then macro 1, ... macro 4 (the same order as
// the Phase 0 export files weights_seed<k>_macro<m>_32b.mem). Word bit (j%4)*8+k = plane k of neuron 4m + j%4.
// The bit-plane rearrangement is done by the Phase 0 export script, NOT here.






import cim_neurohdc_pkg::N_INPUTS;
import cim_neurohdc_pkg::N_MACROS;
import cim_neurohdc_pkg::N_WL_WORDS;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_MACRO_IDX;
import cim_neurohdc_pkg::W_WL_WORD;

module weight_load (
    input  logic                   clk_i,
    input  logic                   rst_n_i,
    input  logic                   start_i,       // begin a load (resets the word counter)
    input  logic                   wl_valid_i,
    input  logic [  W_WL_WORD-1:0] wl_data_i,
    output logic                   wl_ready_o,
    output logic                   wr_en_o,       // to cim_macro
    output logic [W_MACRO_IDX-1:0] wr_macro_o,
    output logic [     W_ADDR-1:0] wr_addr_o,
    output logic [  W_WL_WORD-1:0] wr_data_o,
    output logic                   busy_o,
    output logic                   done_o,        // level: image complete since the last start
    output logic                   assert_fail_o
);
  localparam logic [W_ADDR-1:0] LAST_ADDR = W_ADDR'(N_INPUTS - 1);
  localparam logic [W_MACRO_IDX-1:0] LAST_MACRO = W_MACRO_IDX'(N_MACROS - 1);

  logic                   busy_q;
  logic                   done_q;
  logic [W_MACRO_IDX-1:0] macro_q;
  logic [     W_ADDR-1:0] addr_q;

  assign wl_ready_o = busy_q;
  assign wr_en_o    = busy_q && wl_valid_i;
  assign wr_macro_o = macro_q;
  assign wr_addr_o  = addr_q;
  assign wr_data_o  = wl_data_i;
  assign busy_o     = busy_q;
  assign done_o     = done_q;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      busy_q  <= 1'b0;
      done_q  <= 1'b0;
      macro_q <= '0;
      addr_q  <= '0;
    end else if (start_i) begin
      busy_q  <= 1'b1;
      done_q  <= 1'b0;
      macro_q <= '0;
      addr_q  <= '0;
    end else if (wr_en_o) begin
      if (addr_q == LAST_ADDR) begin
        addr_q <= '0;
        if (macro_q == LAST_MACRO) begin
          busy_q <= 1'b0;
          done_q <= 1'b1;
        end else macro_q <= macro_q + W_MACRO_IDX'(1);
      end else addr_q <= addr_q + W_ADDR'(1);
    end
  end

  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  int unsigned words_q;
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      fail_q  <= 1'b0;
      words_q <= 0;
    end else begin
      if (start_i) words_q <= 0;
      else if (wr_en_o) words_q <= words_q + 1;
      if (wl_valid_i && !busy_q) begin
        $display("[ASSERT FAIL] %m: weight word presented while no load is in progress");
        fail_q <= 1'b1;
      end
      if (wr_en_o && done_q) begin
        $display("[ASSERT FAIL] %m: weight word accepted after the image is complete");
        fail_q <= 1'b1;
      end
      if (done_q && words_q != N_WL_WORDS) begin
        $display("[ASSERT FAIL] %m: image complete after %0d words, expected %0d", words_q, N_WL_WORDS);
        fail_q <= 1'b1;
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
