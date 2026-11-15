// shift_accum.sv - block G. Turns crossbar match counts into the contribution of ONE read to the MVM output X (optimisation item 4). The X registers are gone: the neurons (if_neuron_array) add
// each contribution straight into their membrane potential (V + X is formed by accumulation, the same integer), so this block holds only the issue-tag pipeline and the adder trees.
// (Earlier text:)
//   Every read returns, for each neuron j and weight bit-plane k, the match count m[j][k] (0..g) of ONE count bit-plane b over ONE group of rows. Its contribution to X[j] is
//        sum_k sigma(k) * 2^k * m[j][k]  * 2^b          sigma(k) = +1 for k = 0..6 and -1 for k = 7 (the int8 SIGN plane: its contribution is NEGATIVE; tests check -128, -1, 0, +1, +127)
//   evaluated as a tree: the 8 columns of a neuron are combined first (constant shifts only, an 8-operand adder of W_M-bit values), the result is shifted ONCE by b, and added to X[j].
//   (The earlier structure shifted every one of the 160 partial counts by the variable b into 29 bits and kept 1,600 partial-count flip-flops; this one has 20 trees, 20 shifters and the 20 X registers.)
//   X is the same integer sum, so it is bit-identical; it wraps modulo 2^W_X in the middle and is exact at the end (the final value fits W_X by construction).
// The issue-side tag (the plane b) is delayed MACRO_LAT cycles to line up with the result. X is cleared by clr_i (start of an MVM) and changes only on a valid result.
import cim_neurohdc_pkg::N_NEURONS;
import cim_neurohdc_pkg::N_PARALLEL_COLS_DEFAULT;
import cim_neurohdc_pkg::N_WCOLS;
import cim_neurohdc_pkg::ROWS_PER_GROUP_DEFAULT;
import cim_neurohdc_pkg::SIGN_PLANE;
import cim_neurohdc_pkg::S_ROWS;
import cim_neurohdc_pkg::W_BIT_IDX;
import cim_neurohdc_pkg::W_WEIGHT;
import cim_neurohdc_pkg::W_V;

module shift_accum #(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT,
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    localparam int W_M = $clog2(ROWS_PER_GROUP + 1),
    localparam int W_PASS = (N_WCOLS / N_PARALLEL_COLS > 1) ? $clog2(N_WCOLS / N_PARALLEL_COLS) : 1
) (
    input  logic                         clk_i,
    input  logic                         rst_n_i,
    // issue side
    input  logic                         iss_valid_i,
    input  logic [      W_BIT_IDX-1:0]   iss_b_i,
    input  logic [   W_PASS-1:0]         iss_pass_i,
    input  logic [S_ROWS-1:0]            iss_bits_i,     // the row slots driven (assertions only)
    // result side (cim_macro)
    input  logic                         m_valid_i,
    input  logic [N_PARALLEL_COLS*W_M-1:0] m_i,
    // outputs
    output logic                         d_valid_o,      // d_o holds the contribution of a read
    output logic [   W_PASS-1:0]         d_pass_o,       // pass of that read: lane l works on neuron pass*PN + l
    output logic [(N_PARALLEL_COLS/W_WEIGHT)*W_V-1:0] d_o, // signed contribution to X[pass*PN + l] (weighted over the weight bit-planes, shifted by the count bit-plane), flattened
    output logic                         assert_fail_o
);
  localparam int PN = N_PARALLEL_COLS / W_WEIGHT;  // neurons per pass: one lane each (neuron-major columns: a pass senses all 8 weight bit-planes of PN neurons)
  localparam int W_INNER = W_M + W_WEIGHT;  // sum_k +-2^k m lies in [-128 g, 127 g]

  logic                 t_valid_q;
  logic [W_BIT_IDX-1:0] t_b_q;
  logic [W_PASS-1:0] t_pass_q;
  logic [S_ROWS-1:0] t_bits_q;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      t_valid_q <= 1'b0;
      t_b_q     <= '0;
      t_pass_q  <= '0;
      t_bits_q  <= '0;
    end else begin
      t_valid_q <= iss_valid_i;
      if (iss_valid_i) begin
        t_b_q    <= iss_b_i;
        t_pass_q <= iss_pass_i;
        t_bits_q <= iss_bits_i;
      end
    end
  end

  // The result holds PL weight bit-planes per neuron (columns j*PL + q = plane pass*PL + q). Their weighted sum is formed first (constant shifts), then shifted once by b + pass*PL and added to X[j].
  // Plane 7, the int8 sign plane, is the top plane of the LAST pass and counts negatively.
  // (A variant that summed the passes of a read into a 11-bit Y and committed X += Y << b once per read, with operand isolation, was built and measured: it added 220 flip-flops and
  // did not lower the layout power of the scan phase - the switching is in the number of neuron datapaths, not in how often the wide adder fires. Reverted.)
  logic signed [W_INNER-1:0] inner[PN];
  logic signed [W_V-1:0] d[PN];
  always_comb begin
    for (int l = 0; l < PN; l++) begin
      inner[l] = '0;
      for (int q = 0; q < W_WEIGHT; q++) begin
        if (q == W_WEIGHT - 1) inner[l] = inner[l] - (W_INNER'(m_i[(l*W_WEIGHT+q)*W_M+:W_M]) << q);  // plane 7, the int8 sign plane, counts negatively
        else inner[l] = inner[l] + (W_INNER'(m_i[(l*W_WEIGHT+q)*W_M+:W_M]) << q);
      end
      d[l] = W_V'(inner[l]) <<< int'(t_b_q);  // W_V'() of a signed value sign-extends
    end
  end
  assign d_valid_o = m_valid_i;
  assign d_pass_o  = t_pass_q;
  for (genvar l = 0; l < PN; l++) begin : g_d
    assign d_o[l*W_V+:W_V] = d[l];
  end

  // ---------------------------------------------------------------- assertions (simulation only; never disabled)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  function automatic int popc(input logic [S_ROWS-1:0] v);
    int n;
    n = 0;
    for (int i = 0; i < S_ROWS; i++) n += int'(v[i]);
    return n;
  endfunction
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else begin
      if (m_valid_i != t_valid_q) begin
        $display("[ASSERT FAIL] %m: result valid %0b does not line up with the issue tag %0b", m_valid_i, t_valid_q);
        fail_q <= 1'b1;
      end
      if (m_valid_i) begin
        for (int l = 0; l < PN; l++)
        for (int k = 0; k < W_WEIGHT; k++)
          if (int'(m_i[(l*W_WEIGHT+k)*W_M+:W_M]) > popc(t_bits_q)) begin
            $display("[ASSERT FAIL] %m: match count m[%0d][%0d]=%0d outside 0..a=%0d", l, k, m_i[(l*W_WEIGHT+k)*W_M+:W_M], popc(t_bits_q));
            fail_q <= 1'b1;
          end
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
