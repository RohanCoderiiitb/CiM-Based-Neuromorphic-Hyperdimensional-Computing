// cim_macro.sv - block E. BEHAVIOURAL MODEL of the ReRAM crossbar. Input bits in, exact match count out.
// No currents, no resistances, no comparators, no electrical behaviour of any kind: this is what keeps the digital
// regression bit-exact. The circuit track separately proves the real array computes this same function inside its
// margin; neither proof works if the two are mixed.
//
// Storage: 512 rows x 160 bit-plane columns (bit j*8+k = plane k of neuron j, plane 7 = int8 sign bit).
// One read: for the g rows of group `grp`, m[j][k] = popcount(input_bit[row] & stored_bit[row][j*8+k]).
// Under SYNTHESIS this module is a BLACKBOX: it is a simulation model, expected to be unsynthesizable.
`ifdef SYNTHESIS
(* blackbox *)
module cim_macro
  import cim_neurohdc_pkg::*;
#(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT
) (
    input  logic                                        clk_i,
    input  logic                                        rst_n_i,
    input  logic                                        wr_en_i,
    input  logic [W_MACRO_IDX-1:0]                      wr_macro_i,
    input  logic [W_ADDR-1:0]                           wr_addr_i,
    input  logic [W_WL_WORD-1:0]                        wr_data_i,
    input  logic                                        rd_valid_i,
    input  logic [N_INPUTS-1:0]                         rd_bitrow_i,
    input  logic [W_GRP-1:0]                            rd_grp_i,
    input  logic [W_WEIGHT-1:0]                         rd_plane_mask_i,
    output logic                                        m_valid_o,
    output logic [N_NEURONS-1:0][W_WEIGHT-1:0][W_MATCH-1:0] m_o
);
endmodule
`else
module cim_macro
  import cim_neurohdc_pkg::*;
#(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT
) (
    input  logic                                        clk_i,
    input  logic                                        rst_n_i,
    // weight write port (weight_load)
    input  logic                                        wr_en_i,
    input  logic [W_MACRO_IDX-1:0]                      wr_macro_i,
    input  logic [W_ADDR-1:0]                           wr_addr_i,
    input  logic [W_WL_WORD-1:0]                        wr_data_i,
    // read: one group of the current count bit-row
    input  logic                                        rd_valid_i,
    input  logic [N_INPUTS-1:0]                         rd_bitrow_i,
    input  logic [W_GRP-1:0]                            rd_grp_i,
    input  logic [W_WEIGHT-1:0]                         rd_plane_mask_i,   // planes sensed by this read
    output logic                                        m_valid_o,
    output logic [N_NEURONS-1:0][W_WEIGHT-1:0][W_MATCH-1:0] m_o
);
  logic [N_WCOLS-1:0] w_q[N_INPUTS];
  logic [N_NEURONS-1:0][W_WEIGHT-1:0][W_MATCH-1:0] m_d;

  always_comb begin
    m_d = '0;
    for (int r = 0; r < ROWS_PER_GROUP; r++) begin
      automatic int idx = int'(rd_grp_i) * ROWS_PER_GROUP + r;
      if (idx < N_INPUTS && rd_valid_i && rd_bitrow_i[idx]) begin
        automatic logic [N_WCOLS-1:0] row_w = w_q[idx];
        for (int j = 0; j < N_NEURONS; j++)
          for (int k = 0; k < W_WEIGHT; k++)
            if (rd_plane_mask_i[k] && row_w[j*W_WEIGHT+k]) m_d[j][k] = m_d[j][k] + W_MATCH'(1);
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (wr_en_i) w_q[wr_addr_i][int'(wr_macro_i)*W_WL_WORD+:W_WL_WORD] <= wr_data_i;
    m_valid_o <= rst_n_i && rd_valid_i;
    m_o       <= m_d;
  end
endmodule
`endif
