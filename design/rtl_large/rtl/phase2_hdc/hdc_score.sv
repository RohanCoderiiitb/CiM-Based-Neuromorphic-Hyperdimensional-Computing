// hdc_score.sv - the two scoring datapaths, combinational. agree_i = XNOR-popcount of the 20-bit spike vector with the (virtual) class slice C_i,t, 0..20.
//
//   FACTORIZED = 0  (a) XNOR-popcount:  agree_i = popcount(~(S ^ slice_i)).
//   FACTORIZED = 1  (b) AND-popcount + bias + sign:  P_i = 20 - |S| - bias_i + 2 q_i  (the XNOR popcount of S with a_i, q_i from the array, bias_i = ||a_i||_1),
//                   agree_i = sign_i ? P_i : 20 - P_i   (C_i,t = XNOR(a_i, b_i[t]): XNOR with a constant bit is the identity or the complement).
// Both are integer-exact: for C = expand(a, b) they return the same agree_i for every S (design/reference_model/model/fixedpoint/hdc_query.py, proven on all 24,000 prefixes).
import hdc_pkg::N_SPK;
import hdc_pkg::W_AGREE;
import hdc_pkg::N_CLASSES_DEFAULT;

module hdc_score #(
    parameter int N_CLASSES = N_CLASSES_DEFAULT,
    parameter bit FACTORIZED = 1'b1
) (
    input  logic [N_SPK-1:0]         s_i,       // spike vector
    input  logic [W_AGREE-1:0]       spop_i,    // |S|  (factorized only)
    input  logic [N_CLASSES*W_AGREE-1:0] q_i,       // factorized: AND-popcount per class from the array
    input  logic [N_CLASSES*N_SPK-1:0] slice_i,   // unfactorized: class slices of this timestep
    input  logic [N_CLASSES-1:0]      sign_i,    // factorized: b_i[t]
    input  logic [N_CLASSES*W_AGREE-1:0] bias_i,    // factorized: ||a_i||_1
    output logic [N_CLASSES*W_AGREE-1:0] agree_o
);
  for (genvar i = 0; i < N_CLASSES; i++) begin : g_class
    if (FACTORIZED) begin : g_fact
      localparam int WP = W_AGREE + 3;
      logic [WP-1:0] p;  // 0..N_SPK (asserted in hdc_query)
      assign p = WP'(N_SPK) - {3'b0, spop_i} - {3'b0, bias_i[i*W_AGREE+:W_AGREE]} + WP'(2) * {3'b0, q_i[i*W_AGREE+:W_AGREE]};
      assign agree_o[i*W_AGREE+:W_AGREE] = sign_i[i] ? p[W_AGREE-1:0] : (W_AGREE'(N_SPK) - p[W_AGREE-1:0]);
      logic unused_f;
      assign unused_f = &{1'b0, p[WP-1:W_AGREE], s_i, slice_i};
    end else begin : g_unf
      logic [W_AGREE-1:0] pc;
      popcount #(
          .N(N_SPK)
      ) u_pc (
          .bits_i (~(s_i ^ slice_i[i*N_SPK+:N_SPK])),
          .count_o(pc)
      );
      assign agree_o[i*W_AGREE+:W_AGREE] = pc;
      logic unused_u;
      assign unused_u = &{1'b0, spop_i, q_i, sign_i, bias_i};
    end
  end
endmodule
