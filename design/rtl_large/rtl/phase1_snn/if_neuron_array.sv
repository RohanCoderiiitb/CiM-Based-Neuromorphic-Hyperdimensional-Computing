// if_neuron_array.sv - block H. 20 integrate-and-fire neurons:   Vp = V + X ;  spike = (Vp >= thresh) ;  V = spike ? 0 : Vp
// No leak, no bias, no decay, no shift (F = 0). V is W_V = 26 bits signed in flip-flops (never ReRAM: 2000 writes/inference). V drifts NEGATIVE without bound (hard reset only caps it from above).
// thresh_shared_i: every neuron compares against threshold register 0 (N-MNIST per-tensor quantisation).
// V + X is formed by ACCUMULATION: every crossbar read adds its contribution straight into V (no X register). Neuron-major columns: a pass senses all 8 weight bit-planes of PN = N_PARALLEL_COLS / 8
// neurons, so PN lane adders serve all 20 neurons (lane l works on neuron pass*PN + l) and the threshold compare + reset runs lane by lane over the same N_PASSES cycles (upd_i is held for N_PASSES cycles).
// V wraps modulo 2^W_V in the middle and is exact at the update (V + X fits W_V by construction).
import cim_neurohdc_pkg::F_FRAC;
import cim_neurohdc_pkg::N_PARALLEL_COLS_DEFAULT;
import cim_neurohdc_pkg::W_WEIGHT;
import cim_neurohdc_pkg::N_NEURONS;
import cim_neurohdc_pkg::W_THRESH;
import cim_neurohdc_pkg::W_V;
import cim_neurohdc_pkg::W_X;

module if_neuron_array #(
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    localparam int PN = N_PARALLEL_COLS / W_WEIGHT,
    localparam int NP = (N_NEURONS + PN - 1) / PN,
    localparam int W_PASS = (NP > 1) ? $clog2(NP) : 1
) (
    input  logic                          clk_i,
    input  logic                          rst_n_i,
    input  logic                          clr_i,            // sample start: V = 0
    input  logic                          acc_i,            // add one read's contribution d_i to V of neurons pass*PN .. pass*PN+PN-1
    input  logic [       W_PASS-1:0]      acc_pass_i,
    input  logic [         PN*W_V-1:0]    d_i,
    input  logic                          upd_i,            // end of the MVM: threshold compare and hard reset, lane by lane over NP cycles (held high for NP cycles)
    input  logic [N_NEURONS*W_THRESH-1:0] thresh_i,
    input  logic                          thresh_shared_i,
    output logic [         N_NEURONS-1:0] spike_o,          // registered, valid the cycle after the last upd_i cycle
    output logic                          upd_done_o,       // registered copy of upd_i
    output logic [     N_NEURONS*W_V-1:0] v_o,              // DEBUG_EXPOSE_V
    output logic [     N_NEURONS*W_X-1:0] x_o,              // DEBUG (simulation only): X of the timestep, held from its update; tied to zero in the synthesised chip
    output logic                          assert_fail_o
);
  logic signed [W_V-1:0] v_q[N_NEURONS];
  logic [N_NEURONS-1:0] spike_q;
  logic upd_q;
  logic [W_PASS-1:0] up_cnt_q;  // update lane group

  // ---------------------------------------------------------------- accumulate: PN shared adders
  // (if/else on signed variables, not ?: with an unsized '0 - that would make the expression unsigned)
  logic signed [W_V-1:0] a_sum[PN];
  always_comb begin
    for (int l = 0; l < PN; l++) begin
      int n;
      logic signed [W_V-1:0] vs;
      n = int'(acc_pass_i) * PN + l;
      if (n < N_NEURONS) vs = v_q[n];
      else vs = '0;
      a_sum[l] = vs + signed'(d_i[l*W_V+:W_V]);
    end
  end

  logic [PN-1:0] cmp_d;
  always_comb begin
    for (int l = 0; l < PN; l++) begin
      int n;
      logic signed [W_V-1:0] vs;
      logic signed [W_THRESH-1:0] tj;
      n = int'(up_cnt_q) * PN + l;
      if (n < N_NEURONS && upd_i) vs = v_q[n];  // the comparators see V only during the update (isolation)
      else vs = '0;
      if (thresh_shared_i) tj = thresh_i[0+:W_THRESH];
      else if (n < N_NEURONS) tj = thresh_i[n*W_THRESH+:W_THRESH];
      else tj = '0;
      cmp_d[l] = (n < N_NEURONS) && (vs >= (W_V'(tj) <<< F_FRAC));  // F_FRAC = 0: pure integer compare
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      for (int j = 0; j < N_NEURONS; j++) v_q[j] <= '0;
      spike_q  <= '0;
      upd_q    <= 1'b0;
      up_cnt_q <= '0;
    end else begin
      upd_q <= upd_i;
      if (acc_i) for (int l = 0; l < PN; l++) if (int'(acc_pass_i) * PN + l < N_NEURONS) v_q[int'(acc_pass_i)*PN+l] <= a_sum[l];
      if (upd_i) begin
        up_cnt_q <= up_cnt_q + W_PASS'(1);
        for (int l = 0; l < PN; l++) begin
          if (int'(up_cnt_q) * PN + l < N_NEURONS) begin
            spike_q[int'(up_cnt_q)*PN+l] <= cmp_d[l];
            if (cmp_d[l]) v_q[int'(up_cnt_q)*PN+l] <= '0;
          end
        end
      end else up_cnt_q <= '0;
    end
  end

  assign spike_o    = spike_q;
  assign upd_done_o = upd_q;
  for (genvar j = 0; j < N_NEURONS; j++) begin : g_v
    assign v_o[j*W_V+:W_V] = v_q[j];
  end

  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  // reference X for the regression: V just before the update minus V just after the previous update (or 0 at the sample start)
  logic signed [W_V-1:0] vprev_q[N_NEURONS];
  logic signed [W_X-1:0] xdbg_q[N_NEURONS];
  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      for (int j = 0; j < N_NEURONS; j++) begin
        vprev_q[j] <= '0;
        xdbg_q[j]  <= '0;
      end
    end else if (upd_i) begin
      for (int l = 0; l < PN; l++) begin
        if (int'(up_cnt_q) * PN + l < N_NEURONS) begin
          xdbg_q[int'(up_cnt_q)*PN+l]  <= W_X'(v_q[int'(up_cnt_q)*PN+l] - vprev_q[int'(up_cnt_q)*PN+l]);
          vprev_q[int'(up_cnt_q)*PN+l] <= cmp_d[l] ? '0 : v_q[int'(up_cnt_q)*PN+l];
        end
      end
    end
  end
  for (genvar j = 0; j < N_NEURONS; j++) begin : g_x
    assign x_o[j*W_X+:W_X] = xdbg_q[j];
  end
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else if (upd_i) begin
      for (int l = 0; l < PN; l++) begin
        if (int'(up_cnt_q) * PN + l < N_NEURONS) begin
          if ((v_q[int'(up_cnt_q)*PN+l] - vprev_q[int'(up_cnt_q)*PN+l]) != signed'(W_V'(W_X'(v_q[int'(up_cnt_q)*PN+l] - vprev_q[int'(up_cnt_q)*PN+l])))) begin
            $display("[ASSERT FAIL] %m: X[%0d] does not fit %0d bits", int'(up_cnt_q) * PN + l, W_X);
            fail_q <= 1'b1;
          end
        end
      end
    end
  end
`else
  assign x_o    = '0;
  assign fail_q = 1'b0;
`endif
endmodule
