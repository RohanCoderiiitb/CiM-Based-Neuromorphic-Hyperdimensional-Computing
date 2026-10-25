// cim_macro.sv - block E. BEHAVIOURAL MODEL of the ReRAM crossbar. Input bits in, exact match count out.
// No currents, no resistances, no comparators, no electrical behaviour of any kind: this is what keeps the digital
// regression bit-exact. The circuit track separately proves the real array computes this same function inside its
// margin; neither proof works if the two are mixed.
//
// Storage: 512 rows x 160 bit-plane columns (bit j*8+k = plane k of neuron j, plane 7 = int8 sign bit).
// One read: the g rows of group `grp` are driven with `rd_bits_i` (one bit per row of the group; the macro decodes the group index itself, so only g + log2(512/g) row wires cross the macro
// boundary, not 512); m[j][k] = popcount(rd_bits[row] & stored_bit[row][j*8+k]), 0..g, so W_M = clog2(g+1) bits per column (3 at g = 4): the boundary carries 160 x W_M bits, not 160 x 10.
// The result register holds its value between reads (it changes only when a read is issued).
// Under SYNTHESIS this module is a BLACKBOX: it is a simulation model, expected to be unsynthesizable.
import cim_neurohdc_pkg::N_INPUTS;
import cim_neurohdc_pkg::N_NEURONS;
import cim_neurohdc_pkg::N_WCOLS;
import cim_neurohdc_pkg::N_PARALLEL_COLS_DEFAULT;
import cim_neurohdc_pkg::ROWS_PER_GROUP_DEFAULT;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_MACRO_IDX;
import cim_neurohdc_pkg::W_WEIGHT;
import cim_neurohdc_pkg::W_WL_WORD;

`ifdef SYNTHESIS
(* blackbox *)
module cim_macro #(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT,
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    localparam int W_M = $clog2(ROWS_PER_GROUP + 1),
    localparam int W_G = $clog2(N_INPUTS / ROWS_PER_GROUP),
    localparam int W_PASS = (N_WCOLS / N_PARALLEL_COLS > 1) ? $clog2(N_WCOLS / N_PARALLEL_COLS) : 1
) (
    input  logic                       clk_i,
    input  logic                       rst_n_i,
    input  logic                       wr_en_i,
    input  logic [W_MACRO_IDX-1:0]     wr_macro_i,
    input  logic [     W_ADDR-1:0]     wr_addr_i,
    input  logic [  W_WL_WORD-1:0]     wr_data_i,
    input  logic                       rd_valid_i,
    input  logic [ROWS_PER_GROUP-1:0]  rd_bits_i,
    input  logic [        W_G-1:0]     rd_grp_i,
    input  logic [    W_PASS-1:0]      rd_pass_i,
    output logic                       m_valid_o,
    output logic [N_PARALLEL_COLS*W_M-1:0] m_o
);
endmodule
`else
module cim_macro #(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT,
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    localparam int W_M = $clog2(ROWS_PER_GROUP + 1),
    localparam int W_G = $clog2(N_INPUTS / ROWS_PER_GROUP),
    localparam int W_PASS = (N_WCOLS / N_PARALLEL_COLS > 1) ? $clog2(N_WCOLS / N_PARALLEL_COLS) : 1
) (
    input  logic                       clk_i,
    input  logic                       rst_n_i,
    // weight write port (weight_load)
    input  logic                       wr_en_i,
    input  logic [W_MACRO_IDX-1:0]     wr_macro_i,
    input  logic [     W_ADDR-1:0]     wr_addr_i,
    input  logic [  W_WL_WORD-1:0]     wr_data_i,
    // read: one (bit-plane, group) of the count memory
    input  logic                       rd_valid_i,
    input  logic [ROWS_PER_GROUP-1:0]  rd_bits_i,
    input  logic [        W_G-1:0]     rd_grp_i,
    input  logic [    W_PASS-1:0]      rd_pass_i,        // sensing pass: result columns j*PL+q are weight plane pass*PL+q of neuron j, PL = N_PARALLEL_COLS / 20
    output logic                       m_valid_o,
    output logic [N_PARALLEL_COLS*W_M-1:0] m_o
);
  logic [N_WCOLS-1:0] w_q[N_INPUTS];
  localparam int PL = N_PARALLEL_COLS / N_NEURONS;  // weight bit-planes sensed per pass
  logic [N_PARALLEL_COLS*W_M-1:0] m_d;

  int idx_t;
  logic [N_WCOLS-1:0] row_w_t;

  always_comb begin
    m_d     = '0;
    row_w_t = '0;
    idx_t   = 0;
    for (int r = 0; r < ROWS_PER_GROUP; r++) begin
      idx_t   = int'(rd_grp_i) * ROWS_PER_GROUP + r;
      row_w_t = '0;
      if (idx_t < N_INPUTS && rd_valid_i && rd_bits_i[r]) begin
        row_w_t = w_q[idx_t];
        for (int j = 0; j < N_NEURONS; j++)
        for (int q = 0; q < PL; q++)
        if (row_w_t[j*W_WEIGHT+int'(rd_pass_i)*PL+q]) m_d[(j*PL+q)*W_M+:W_M] = m_d[(j*PL+q)*W_M+:W_M] + W_M'(1);
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (wr_en_i) w_q[wr_addr_i][int'(wr_macro_i)*W_WL_WORD+:W_WL_WORD] <= wr_data_i;
    m_valid_o <= rst_n_i && rd_valid_i;
    if (rd_valid_i) m_o <= m_d;
  end
endmodule
`endif
