// hdc_query.sv - Phase 2: the HDC query stage. Consumes the 20-bit spike vector of one timestep (valid strobe + timestep index), keeps N prefix scores, and presents the leader,
// the second-largest score and the leader's index once per timestep.
//
//   cycle 0  spike_valid_i      spike vector captured (s_q, t_q)
//   cycle 1  v1_q               array read: row enables = the spikes (hdc_class_array), registered
//   cycle 2  arr_valid          agree_i from the datapath of the chosen mapping; score_i += agree_i (registered)
//   cycle 3  v3_q               top-2 tournament over the N scores (registered)
//   cycle 4  dec_valid_o        top1_idx_o / top1_o / top2_o valid (one cycle); the exit controller compares the margin here
// busy_o is high from cycle 0 to cycle 4 inclusive: the integration holds the SNN's event intake for exactly that long, so timestep t's spikes are consumed (and the exit
// decision taken) before any event of timestep t+1 is accepted.
//
// Mapping (FACTORIZED): 0 = unfactorized 2000 x N class memory + XNOR-popcount; 1 = R=1 factorized (20 x N stationary array + T x N sign table + N bias registers) + AND-popcount.
// Class image: cm_we_i / cm_sel_i / cm_addr_i / cm_data_i (see hdc_pkg). Simulation-only checks (ifndef SYNTHESIS): agree in range, and the unipolar identity of README Phase 2:
// argmax_i [ 2 S.C_i - ||C_i||_1 ] (prefix) == argmax of the XNOR score at EVERY timestep, plus the exact offset relation score_i = uni_i + sum_t (20 - |S_t|).
import hdc_pkg::*;

module hdc_query #(
    parameter int N_CLASSES = N_CLASSES_DEFAULT,
    parameter bit FACTORIZED = FACTORIZED_DEFAULT,
    parameter bit CHECK_UNIPOLAR = CHECK_UNIPOLAR_DEFAULT,
    parameter bit INSTRUMENT_EN = 1'b1
) (
    input  logic                       clk_i,
    input  logic                       rst_n_i,
    input  logic                       clr_i,         // sample start: scores to zero
    // class image
    input  logic                       cm_we_i,
    input  logic [      W_CM_SEL-1:0]  cm_sel_i,
    input  logic [       W_TADDR-1:0]  cm_addr_i,
    input  logic [N_CLASSES*20-1:0]    cm_data_i,
    // spike waist
    input  logic                       spike_valid_i,
    input  logic [               19:0] spike_i,
    input  logic [   W_TADDR-1:0]      tstep_i,
    output logic                       busy_o,
    output logic                       dec_valid_o,
    output logic [   W_TADDR-1:0]      dec_tstep_o,
    output logic [N_CLASSES*W_SCORE-1:0] scores_o,
    output logic [      W_CLASS-1:0]   top1_idx_o,
    output logic [      W_SCORE-1:0]   top1_o,
    output logic [      W_SCORE-1:0]   top2_o,
    // instrumentation (valid with dec_valid_o)
    output logic [                4:0] rows_gated_o,  // spike-gated row enables of this timestep = |S|
    output logic [               31:0] reads_o,       // array reads since clr_i
    output logic                       assert_fail_o
);
  localparam int NTS = 100;
  logic [19:0] s_q;
  logic [W_TADDR-1:0] t_q;
  logic v1_q, v3_q, v4_q;  // stage valids; stage 2 is arr_valid (the array's registered read-valid)
  logic [N_CLASSES*W_SCORE-1:0] score_q;
  logic [W_SCORE-1:0] top1_q, top2_q;
  logic [W_CLASS-1:0] idx_q;
  logic [4:0] spop;

  popcount #(
      .N(20)
  ) u_spop (
      .bits_i (s_q),
      .count_o(spop)
  );

  // ------------------------------------------------------------------ class array (analog block: behavioural model / blackbox)
  logic arr_valid;
  logic [N_CLASSES*5-1:0] arr_q;
  logic [N_CLASSES*20-1:0] arr_slice;
  hdc_class_array #(
      .N_CLASSES (N_CLASSES),
      .FACTORIZED(FACTORIZED)
  ) u_array (
      .clk_i     (clk_i),
      .rst_n_i   (rst_n_i),
      .cm_we_i   (cm_we_i && cm_sel_i == W_CM_SEL'(CM_SEL_ARRAY)),
      .cm_addr_i (FACTORIZED ? 7'd0 : cm_addr_i),
      .cm_data_i (cm_data_i),
      .rd_valid_i(v1_q),
      .rd_addr_i (t_q),
      .rd_rows_i (s_q),
      .rd_valid_o(arr_valid),
      .q_o       (arr_q),
      .slice_o   (arr_slice)
  );

  // ------------------------------------------------------------------ digital side tables of the factorized mapping: sign table (T x N) and bias registers (N x 5)
  logic [N_CLASSES-1:0] sign_row;
  logic [N_CLASSES*5-1:0] bias_flat;
  if (FACTORIZED) begin : g_fact_tables
    logic [N_CLASSES-1:0] sign_q[NTS];
    logic [N_CLASSES*5-1:0] bias_q;
    always_ff @(posedge clk_i) begin
      if (cm_we_i && cm_sel_i == W_CM_SEL'(CM_SEL_SIGN)) sign_q[cm_addr_i] <= cm_data_i[N_CLASSES-1:0];
      if (cm_we_i && cm_sel_i == W_CM_SEL'(CM_SEL_BIAS)) bias_q <= cm_data_i[N_CLASSES*5-1:0];
    end
    assign sign_row  = sign_q[t_q];
    assign bias_flat = bias_q;
  end else begin : g_no_tables
    assign sign_row  = '0;
    assign bias_flat = '0;
  end

  // ------------------------------------------------------------------ scoring datapath of the chosen mapping
  logic [N_CLASSES*5-1:0] agree;
  hdc_score #(
      .N_CLASSES (N_CLASSES),
      .FACTORIZED(FACTORIZED)
  ) u_score (
      .s_i    (s_q),
      .spop_i (spop),
      .q_i    (arr_q),
      .slice_i(arr_slice),
      .sign_i (sign_row),
      .bias_i (bias_flat),
      .agree_o(agree)
  );

  // ------------------------------------------------------------------ top-2 tournament over the registered scores
  logic [W_SCORE-1:0] t_v1, t_v2;
  logic [W_CLASS-1:0] t_i1;
  top2_tree #(
      .N (N_CLASSES),
      .W (W_SCORE),
      .WI(W_CLASS)
  ) u_top2 (
      .scores_i(score_q),
      .v1_o    (t_v1),
      .i1_o    (t_i1),
      .v2_o    (t_v2)
  );

  logic [31:0] reads_q;
  if (INSTRUMENT_EN) begin : g_instr
    always_ff @(posedge clk_i) begin
      if (!rst_n_i || clr_i) reads_q <= '0;
      else if (v1_q) reads_q <= reads_q + 32'd1;
    end
  end else begin : g_no_instr
    assign reads_q = '0;
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      s_q     <= '0;
      t_q     <= '0;
      v1_q    <= 1'b0;
      v3_q    <= 1'b0;
      v4_q    <= 1'b0;
      score_q <= '0;
      top1_q  <= '0;
      top2_q  <= '0;
      idx_q   <= '0;
    end else begin
      v1_q <= spike_valid_i;
      v3_q <= arr_valid;
      v4_q <= v3_q;
      if (spike_valid_i) begin
        s_q <= spike_i;
        t_q <= tstep_i;
      end
      if (arr_valid) begin
        for (int i = 0; i < N_CLASSES; i++) score_q[i*W_SCORE+:W_SCORE] <= score_q[i*W_SCORE+:W_SCORE] + W_SCORE'(agree[i*5+:5]);
      end
      if (v3_q) begin
        top1_q <= t_v1;
        top2_q <= t_v2;
        idx_q  <= t_i1;
      end
    end
  end

  assign busy_o      = spike_valid_i | v1_q | arr_valid | v3_q | v4_q;
  assign dec_valid_o = v4_q;
  assign dec_tstep_o = t_q;
  assign scores_o    = score_q;
  assign top1_idx_o  = idx_q;
  assign top1_o      = top1_q;
  assign top2_o      = top2_q;
  assign rows_gated_o = spop;
  assign reads_o     = reads_q;

  logic unused_ok;
  assign unused_ok = &{1'b0, cm_addr_i[0]};

`ifndef SYNTHESIS
  // ------------------------------------------------------------------ simulation-only checks (never present in synthesis, never disabled in a run)
  logic fail_q;
  logic [N_CLASSES*20-1:0] sh_main[128];  // shadow of the class image (the array is a blackbox in synthesis)
  logic [N_CLASSES-1:0] sh_sign[NTS];
  always_ff @(posedge clk_i) begin
    if (cm_we_i && cm_sel_i == W_CM_SEL'(CM_SEL_ARRAY)) sh_main[FACTORIZED ? 7'd0 : cm_addr_i] <= cm_data_i;
    if (cm_we_i && cm_sel_i == W_CM_SEL'(CM_SEL_SIGN)) sh_sign[cm_addr_i] <= cm_data_i[N_CLASSES-1:0];
  end

  function automatic int pc20(input logic [19:0] v);
    int n;
    n = 0;
    for (int j = 0; j < 20; j++) n = n + int'(v[j]);
    return n;
  endfunction

  // the unipolar form of README Phase 2: per class and timestep  2 S.C_i,t - ||C_i,t||_1 ; C_i,t from the SHADOW image (XNOR(a, b) when factorized)
  int uni_add[N_CLASSES];
  always_comb begin
    for (int i = 0; i < N_CLASSES; i++) begin
      logic [19:0] cls;
      cls        = FACTORIZED ? ~(sh_main[0][i*20+:20] ^ {20{sh_sign[t_q][i]}}) : sh_main[t_q][i*20+:20];
      uni_add[i] = 2 * pc20(cls & s_q) - pc20(cls);
    end
  end

  // argmax (lowest index) of the unipolar prefix
  int uni_q[N_CLASSES];
  int off_q;
  int uni_arg;
  always_comb begin
    int best;
    uni_arg = 0;
    best    = uni_q[0];
    for (int i = 1; i < N_CLASSES; i++) begin
      if (uni_q[i] > best) begin
        best    = uni_q[i];
        uni_arg = i;
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    if (!rst_n_i || clr_i) begin
      for (int i = 0; i < N_CLASSES; i++) uni_q[i] <= 0;
      off_q <= 0;
    end else if (arr_valid) begin
      for (int i = 0; i < N_CLASSES; i++) begin
        if (int'(agree[i*5+:5]) > 20) begin
          $display("[ASSERT FAIL] %m: agree_%0d = %0d outside 0..20 (class image or bias register inconsistent)", i, agree[i*5+:5]);
          fail_q <= 1'b1;
        end
        if (CHECK_UNIPOLAR) uni_q[i] <= uni_q[i] + uni_add[i];
      end
      if (CHECK_UNIPOLAR) off_q <= off_q + 20 - int'(spop);
    end
    // argmax of the unipolar prefix must equal the XNOR leader, and score_i == uni_i + offset EXACTLY, at every timestep
    if (v4_q && CHECK_UNIPOLAR) begin
      if (uni_arg != int'(idx_q)) begin
        $display("[ASSERT FAIL] %m: unipolar argmax %0d != XNOR argmax %0d at timestep %0d", uni_arg, idx_q, t_q);
        fail_q <= 1'b1;
      end
      for (int i = 0; i < N_CLASSES; i++) begin
        if (int'(score_q[i*W_SCORE+:W_SCORE]) != uni_q[i] + off_q) begin
          $display("[ASSERT FAIL] %m: class %0d score %0d != unipolar %0d + offset %0d at timestep %0d", i, score_q[i*W_SCORE+:W_SCORE], uni_q[i], off_q, t_q);
          fail_q <= 1'b1;
        end
      end
    end
    if (spike_valid_i && (v1_q | arr_valid | v3_q | v4_q)) begin
      $display("[ASSERT FAIL] %m: a spike vector arrived while the previous timestep was still being scored (the integration must hold the SNN)");
      fail_q <= 1'b1;
    end
  end
  assign assert_fail_o = fail_q;
`else
  assign assert_fail_o = 1'b0;
`endif
endmodule
