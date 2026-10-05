// if_neuron_array.sv - block H. 20 integrate-and-fire neurons updating in parallel in ONE cycle:
//     Vp = V + X ;  spike = (Vp >= thresh) ;  V = spike ? 0 : Vp
// No leak, no bias, no decay, no shift (F = 0). V is W_V = 26 bits signed in flip-flops (never ReRAM: 2000 writes/inference).
// V drifts NEGATIVE without bound (hard reset only caps it from above) - that is what sets the width.
// thresh_shared_i: every neuron compares against threshold register 0 (N-MNIST per-tensor quantisation).






import cim_neurohdc_pkg::F_FRAC;
import cim_neurohdc_pkg::N_NEURONS;
import cim_neurohdc_pkg::W_THRESH;
import cim_neurohdc_pkg::W_V;
import cim_neurohdc_pkg::W_X;

module if_neuron_array (
    input  logic                          clk_i,
    input  logic                          rst_n_i,
    input  logic                          clr_i,            // sample start: V = 0
    input  logic                          upd_i,            // one update with x_i
    input  logic [     N_NEURONS*W_X-1:0] x_i,
    input  logic [N_NEURONS*W_THRESH-1:0] thresh_i,
    input  logic                          thresh_shared_i,
    output logic [         N_NEURONS-1:0] spike_o,          // registered, valid the cycle after upd_i
    output logic                          upd_done_o,       // registered copy of upd_i
    output logic [     N_NEURONS*W_V-1:0] v_o,              // DEBUG_EXPOSE_V
    output logic                          assert_fail_o
);
  localparam int W_VP = W_V + 1;  // one guard bit to detect overflow

  logic signed [W_V-1:0] v_q[N_NEURONS];
  logic signed [W_VP-1:0] vp[N_NEURONS];
  logic [N_NEURONS-1:0] spike_d;
  logic [N_NEURONS-1:0] spike_q;
  logic upd_q;

  for (genvar j = 0; j < N_NEURONS; j++) begin : g_cmp
    logic signed [W_X-1:0] xj;
    logic signed [W_THRESH-1:0] tj;
    assign xj         = x_i[j*W_X+:W_X];
    assign tj         = thresh_shared_i ? thresh_i[0+:W_THRESH] : thresh_i[j*W_THRESH+:W_THRESH];
    assign vp[j]      = W_VP'(v_q[j]) + W_VP'(xj);
    assign spike_d[j] = (vp[j] >= (W_VP'(tj) <<< F_FRAC));  // F_FRAC = 0: pure integer compare
  end

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      for (int j = 0; j < N_NEURONS; j++) v_q[j] <= '0;
      spike_q <= '0;
      upd_q   <= 1'b0;
    end else begin
      upd_q <= upd_i;
      if (upd_i) begin
        spike_q <= spike_d;
        for (int j = 0; j < N_NEURONS; j++) v_q[j] <= spike_d[j] ? '0 : vp[j][W_V-1:0];
      end
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
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else begin
      for (int j = 0; j < N_NEURONS; j++) begin
        if (upd_i && (vp[j][W_VP-1] != vp[j][W_V-1])) begin
          $display("[ASSERT FAIL] %m: V[%0d] + X overflows %0d bits", j, W_V);
          fail_q <= 1'b1;
        end
        if (spike_q[j] && v_q[j] != '0) begin
          $display("[ASSERT FAIL] %m: V[%0d] != 0 in the cycle after a spike", j);
          fail_q <= 1'b1;
        end
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
