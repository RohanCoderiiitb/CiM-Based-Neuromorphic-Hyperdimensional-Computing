// hdc_class_array.sv - BEHAVIOURAL MODEL of the class-hypervector CIM array (the HDC counterpart of cim_macro). No currents, no ladders: exact counts out.
//
//   FACTORIZED = 1  the 20 x N stationary array a (a_i[j] = 1 == +1). One read with the spike vector on the 20 row lines (ROW ENABLE = spike) and all N columns sensed gives
//                   q_i = popcount(S & a_i), the AND-popcount, 0..20.        rd_addr_i is ignored (the array is stationary: that is the point of the factorization).
//   FACTORIZED = 0  the 2000 x N class memory: T slices of N x 20 bits. A read returns the N class slices of timestep rd_addr_i (20 rows x N columns), for the digital
//                   XNOR-popcount of hdc_score. The spike-gated row count is reported by hdc_query either way.
// Write port: cm_we_i / cm_addr_i / cm_data_i (word = N x 20 bits, class i at [20 i +: 20]); the stationary array is address 0. One-cycle registered read.
// Under SYNTHESIS this module is a BLACKBOX (analog array, like cim_macro); area and energy come from the analog models, not from synthesis.
`ifdef SYNTHESIS
(* blackbox *)
module hdc_class_array #(
    parameter int N_CLASSES = 10,
    parameter bit FACTORIZED = 1'b1
) (
    input  logic                       clk_i,
    input  logic                       rst_n_i,
    input  logic                       cm_we_i,
    input  logic [                6:0] cm_addr_i,
    input  logic [N_CLASSES*20-1:0]    cm_data_i,
    input  logic                       rd_valid_i,
    input  logic [                6:0] rd_addr_i,
    input  logic [               19:0] rd_rows_i,
    output logic                       rd_valid_o,
    output logic [N_CLASSES*5-1:0]     q_o,
    output logic [N_CLASSES*20-1:0]    slice_o
);
endmodule
`else
module hdc_class_array #(
    parameter int N_CLASSES = 10,
    parameter bit FACTORIZED = 1'b1
) (
    input  logic                       clk_i,
    input  logic                       rst_n_i,
    input  logic                       cm_we_i,
    input  logic [                6:0] cm_addr_i,
    input  logic [N_CLASSES*20-1:0]    cm_data_i,
    input  logic                       rd_valid_i,
    input  logic [                6:0] rd_addr_i,
    input  logic [               19:0] rd_rows_i,
    output logic                       rd_valid_o,
    output logic [N_CLASSES*5-1:0]     q_o,
    output logic [N_CLASSES*20-1:0]    slice_o
);
  logic [N_CLASSES*20-1:0] mem_q[128];  // [20 rows x N columns] per address; only address 0 is used when FACTORIZED
  logic [N_CLASSES*5-1:0] q_d;
  logic [N_CLASSES*20-1:0] slice_d;
  logic [19:0] word_t;
  int cnt_t;

  always_comb begin
    q_d     = '0;
    slice_d = '0;
    word_t  = '0;
    cnt_t   = 0;
    if (rd_valid_i) begin
      if (FACTORIZED) begin
        for (int i = 0; i < N_CLASSES; i++) begin
          word_t = mem_q[0][i*20+:20] & rd_rows_i;
          cnt_t  = 0;
          for (int j = 0; j < 20; j++) cnt_t = cnt_t + int'(word_t[j]);
          q_d[i*5+:5] = 5'(cnt_t);
        end
      end else begin
        slice_d = mem_q[rd_addr_i];
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (cm_we_i) mem_q[cm_addr_i] <= cm_data_i;
    rd_valid_o <= rst_n_i && rd_valid_i;
    q_o        <= q_d;
    slice_o    <= slice_d;
  end
endmodule
`endif
