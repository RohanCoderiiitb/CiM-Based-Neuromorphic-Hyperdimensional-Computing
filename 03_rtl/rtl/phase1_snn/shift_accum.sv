// shift_accum.sv - block G. Turns crossbar match counts into the MVM output X.
//   1. group counts of one bit-row are added into a full-array count      P[j][k] = sum over groups of m[j][k]
//   2. when the bit-row's last read arrives the row is folded:           X[j] += sum_k  sigma(k) * 2^(b+k) * P[j][k]
//      sigma(k) = +1 for k = 0..6 and **-1 for k = 7**: weight bit-plane 7 is the SIGN bit of an int8, so its contribution is
//      NEGATIVE. (Getting this backwards gives plausible wrong answers; tests/test_shift_accum.py checks -128,-1,0,+1,+127.)
// It also computes `a`, the active-row count: one 512-bit popcount of the bit-row (a_row_o) shared by all columns, plus the
// per-group count used to check m <= a (the analog side recovers m from 2m - a).
//
// Issue side (same cycle as the read goes to cim_macro): tags and `a` are registered for MACRO_LAT cycles so they line up with the
// result side (m_valid_i). All arithmetic is exact two's-complement; X is W_X bits and an overflow is an assertion failure.
module shift_accum
  import cim_neurohdc_pkg::*;
#(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT
) (
    input  logic                                            clk_i,
    input  logic                                            rst_n_i,
    input  logic                                            clr_i,            // zero X and the partial counts (start of an MVM)
    // issue side
    input  logic                                            iss_valid_i,
    input  logic [N_INPUTS-1:0]                             iss_bitrow_i,
    input  logic [W_GRP-1:0]                                iss_grp_i,
    input  logic [W_BIT_IDX-1:0]                            iss_b_i,
    input  logic                                            iss_last_i,
    input  logic                                            iss_plane0_i,     // this read senses weight plane 0 (once per (bit-row, group))
    // result side (cim_macro)
    input  logic                                            m_valid_i,
    input  logic [N_NEURONS-1:0][W_WEIGHT-1:0][W_MATCH-1:0] m_i,
    // outputs
    output logic [W_PCOUNT-1:0]                             a_row_o,          // active rows of the current bit-row
    output logic [N_NEURONS*W_X-1:0]                        x_o,              // signed X[j], flattened
    output logic [W_STAT-1:0]                               zero_groups_o,    // groups with a = 0 (could be skipped); this timestep
    output logic                                            assert_fail_o
);
  // ---------------------------------------------------------------- issue side
  logic [ROWS_PER_GROUP-1:0] grp_bits;
  logic [W_PCOUNT-1:0] a_grp;

  always_comb begin
    grp_bits = '0;
    for (int r = 0; r < ROWS_PER_GROUP; r++) begin
      automatic int idx = int'(iss_grp_i) * ROWS_PER_GROUP + r;
      if (idx < N_INPUTS) grp_bits[r] = iss_bitrow_i[idx];
    end
  end

  popcount #(.N(N_INPUTS)) u_a_row (.bits_i(iss_bitrow_i), .count_o(a_row_o));
  popcount #(.N(ROWS_PER_GROUP), .W(W_PCOUNT)) u_a_grp (.bits_i(grp_bits), .count_o(a_grp));

  logic                 t_valid_q;
  logic [W_BIT_IDX-1:0] t_b_q;
  logic                 t_last_q;
  logic [W_PCOUNT-1:0]  t_a_grp_q;
  logic [W_PCOUNT-1:0]  t_a_row_q;
  logic [W_STAT-1:0]    zero_q;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      t_valid_q <= 1'b0;
      t_b_q     <= '0;
      t_last_q  <= 1'b0;
      t_a_grp_q <= '0;
      t_a_row_q <= '0;
      zero_q    <= '0;
    end else begin
      t_valid_q <= iss_valid_i;
      t_b_q     <= iss_b_i;
      t_last_q  <= iss_last_i;
      t_a_grp_q <= a_grp;
      t_a_row_q <= a_row_o;
      if (clr_i) zero_q <= '0;
      else if (iss_valid_i && iss_plane0_i && a_grp == '0) zero_q <= zero_q + W_STAT'(1);
    end
  end
  assign zero_groups_o = zero_q;

  // ---------------------------------------------------------------- result side: accumulate + fold
  logic [W_PCOUNT-1:0] p_q[N_NEURONS][W_WEIGHT];
  logic [W_PCOUNT-1:0] p_next[N_NEURONS][W_WEIGHT];
  logic signed [W_X-1:0] x_q[N_NEURONS];
  logic signed [W_FOLD-1:0] fold[N_NEURONS];
  logic signed [W_FOLD-1:0] x_wide[N_NEURONS];

  always_comb begin
    for (int j = 0; j < N_NEURONS; j++) begin
      fold[j] = '0;
      for (int k = 0; k < W_WEIGHT; k++) begin
        p_next[j][k] = p_q[j][k] + (m_valid_i ? m_i[j][k][W_PCOUNT-1:0] : '0);
        if (k == SIGN_PLANE) fold[j] = fold[j] - (W_FOLD'(p_next[j][k]) << (int'(t_b_q) + k));
        else fold[j] = fold[j] + (W_FOLD'(p_next[j][k]) << (int'(t_b_q) + k));
      end
      x_wide[j] = W_FOLD'(x_q[j]) + fold[j];   // W_FOLD'() of a signed value sign-extends
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      for (int j = 0; j < N_NEURONS; j++) begin
        x_q[j] <= '0;
        for (int k = 0; k < W_WEIGHT; k++) p_q[j][k] <= '0;
      end
    end else if (m_valid_i) begin
      for (int j = 0; j < N_NEURONS; j++) begin
        for (int k = 0; k < W_WEIGHT; k++) p_q[j][k] <= t_last_q ? '0 : p_next[j][k];
        if (t_last_q) x_q[j] <= x_wide[j][W_X-1:0];
      end
    end
  end

  for (genvar j = 0; j < N_NEURONS; j++) begin : g_x
    assign x_o[j*W_X+:W_X] = x_q[j];
  end

  // ---------------------------------------------------------------- assertions (simulation only; never disabled)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  logic [W_PCOUNT-1:0] a_sum_q;   // sum of per-group `a` over the groups issued so far in the current bit-row
  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      fail_q  <= fail_q && rst_n_i;
      a_sum_q <= '0;
    end else begin
      // group counts of a row add up to the row's popcount (checked at the row's last issue)
      if (iss_valid_i && iss_plane0_i) begin
        if (iss_last_i) begin
          if (a_sum_q + a_grp != a_row_o) begin
            $display("[ASSERT FAIL] %m: sum of group active-counts %0d != row popcount %0d", a_sum_q + a_grp, a_row_o);
            fail_q <= 1'b1;
          end
          a_sum_q <= '0;
        end else a_sum_q <= a_sum_q + a_grp;
      end else if (iss_valid_i && iss_last_i) begin
        // serial-plane mode: the last read belongs to the last plane pass; the row sum was closed on its plane-0 pass
        a_sum_q <= '0;
      end
      if (m_valid_i != t_valid_q) begin
        $display("[ASSERT FAIL] %m: result valid %0b does not line up with the issue tag %0b", m_valid_i, t_valid_q);
        fail_q <= 1'b1;
      end
      if (m_valid_i) begin
        for (int j = 0; j < N_NEURONS; j++)
          for (int k = 0; k < W_WEIGHT; k++) begin
            if (m_i[j][k] > W_MATCH'(ROWS_PER_GROUP) || m_i[j][k] > W_MATCH'(t_a_grp_q)) begin
              $display("[ASSERT FAIL] %m: match count m[%0d][%0d]=%0d outside 0..min(g=%0d, a=%0d)", j, k, m_i[j][k], ROWS_PER_GROUP, t_a_grp_q);
              fail_q <= 1'b1;
            end
            if (p_next[j][k] > t_a_row_q) begin
              $display("[ASSERT FAIL] %m: full-array count %0d exceeds active rows %0d", p_next[j][k], t_a_row_q);
              fail_q <= 1'b1;
            end
          end
        if (t_last_q)
          for (int j = 0; j < N_NEURONS; j++)
            if (x_wide[j][W_FOLD-1:W_X-1] != {(W_FOLD - W_X + 1) {x_wide[j][W_X-1]}}) begin
              $display("[ASSERT FAIL] %m: X[%0d] overflows %0d bits", j, W_X);
              fail_q <= 1'b1;
            end
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
