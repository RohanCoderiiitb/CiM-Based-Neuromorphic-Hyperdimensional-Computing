// hdc_score.sv - the two scoring datapaths, combinational. agree_i = XNOR-popcount of the 20-bit spike vector with the (virtual) class slice C_i,t, 0..20.
//
//   FACTORIZED = 0  (a) XNOR-popcount:  agree_i = popcount(~(S ^ slice_i)).
//   FACTORIZED = 1  (b) AND-popcount + bias + sign:  P_i = 20 - |S| - bias_i + 2 q_i  (the XNOR popcount of S with a_i, q_i from the array, bias_i = ||a_i||_1),
//                   agree_i = sign_i ? P_i : 20 - P_i   (C_i,t = XNOR(a_i, b_i[t]): XNOR with a constant bit is the identity or the complement).
// Both are integer-exact: for C = expand(a, b) they return the same agree_i for every S (design/reference_model/model/fixedpoint/hdc_query.py, proven on all 24,000 prefixes).
module hdc_score #(
    parameter int N_CLASSES = 10,
    parameter bit FACTORIZED = 1'b1
) (
    input  logic [              19:0] s_i,       // spike vector
    input  logic [              4:0]  spop_i,    // |S|  (factorized only)
    input  logic [N_CLASSES*5-1:0]    q_i,       // factorized: AND-popcount per class from the array
    input  logic [N_CLASSES*20-1:0]   slice_i,   // unfactorized: class slices of this timestep
    input  logic [N_CLASSES-1:0]      sign_i,    // factorized: b_i[t]
    input  logic [N_CLASSES*5-1:0]    bias_i,    // factorized: ||a_i||_1
    output logic [N_CLASSES*5-1:0]    agree_o
);
  for (genvar i = 0; i < N_CLASSES; i++) begin : g_class
    if (FACTORIZED) begin : g_fact
      logic [7:0] p;  // 0..20 (asserted in hdc_query)
      assign p = 8'd20 - {3'b0, spop_i} - {3'b0, bias_i[i*5+:5]} + 8'd2 * {3'b0, q_i[i*5+:5]};
      assign agree_o[i*5+:5] = sign_i[i] ? p[4:0] : (5'd20 - p[4:0]);
      logic unused_f;
      assign unused_f = &{1'b0, p[7:5], s_i, slice_i};
    end else begin : g_unf
      logic [4:0] pc;
      popcount #(
          .N(20)
      ) u_pc (
          .bits_i (~(s_i ^ slice_i[i*20+:20])),
          .count_o(pc)
      );
      assign agree_o[i*5+:5] = pc;
      logic unused_u;
      assign unused_u = &{1'b0, spop_i, q_i, sign_i, bias_i};
    end
  end
endmodule
