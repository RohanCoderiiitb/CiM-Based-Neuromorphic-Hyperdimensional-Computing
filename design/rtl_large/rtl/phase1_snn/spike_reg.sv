// spike_reg.sv - block I (output side). Holds the 20-bit spike vector S(t) with a ONE-CYCLE valid strobe, the timestep
// index, and `done` after the last timestep (T strobes in a sample).






import cim_neurohdc_pkg::N_NEURONS;
import cim_neurohdc_pkg::N_TIMESTEPS;
import cim_neurohdc_pkg::W_TSTEP;

module spike_reg (
    input  logic                 clk_i,
    input  logic                 rst_n_i,
    input  logic                 clr_i,         // sample start
    input  logic                 load_i,        // capture spike_i for timestep tstep_i (one pulse per timestep)
    input  logic [N_NEURONS-1:0] spike_i,
    input  logic [  W_TSTEP-1:0] tstep_i,
    output logic [N_NEURONS-1:0] spike_o,
    output logic                 valid_o,       // one-cycle strobe, once per timestep
    output logic [  W_TSTEP-1:0] tstep_o,
    output logic                 done_o,        // level: T strobes have been produced
    output logic                 assert_fail_o
);
  logic [N_NEURONS-1:0] spike_q;
  logic                 valid_q;
  logic [  W_TSTEP-1:0] tstep_q;
  logic                 done_q;
  logic [  W_TSTEP-1:0] strobes_q;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i || clr_i) begin
      spike_q   <= '0;
      valid_q   <= 1'b0;
      tstep_q   <= '0;
      done_q    <= 1'b0;
      strobes_q <= '0;
    end else begin
      valid_q <= load_i;
      if (load_i) begin
        spike_q   <= spike_i;
        tstep_q   <= tstep_i;
        strobes_q <= strobes_q + W_TSTEP'(1);
        if (tstep_i == W_TSTEP'(N_TIMESTEPS - 1)) done_q <= 1'b1;
      end
    end
  end

  assign spike_o = spike_q;
  assign valid_o = valid_q;
  assign tstep_o = tstep_q;
  assign done_o  = done_q;

  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  logic valid_prev_q;
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      fail_q       <= 1'b0;
      valid_prev_q <= 1'b0;
    end else begin
      valid_prev_q <= valid_q;
      if (load_i && !(tstep_i < W_TSTEP'(N_TIMESTEPS))) begin
        $display("[ASSERT FAIL] %m: timestep index %0d >= T", tstep_i);
        fail_q <= 1'b1;
      end
      if (load_i && tstep_i != strobes_q) begin
        $display("[ASSERT FAIL] %m: strobe for timestep %0d but %0d strobes so far (exactly one per timestep)", tstep_i, strobes_q);
        fail_q <= 1'b1;
      end
      if (valid_q && valid_prev_q) begin
        $display("[ASSERT FAIL] %m: valid strobe longer than one cycle");
        fail_q <= 1'b1;
      end
      if (load_i && done_q) begin
        $display("[ASSERT FAIL] %m: strobe after done");
        fail_q <= 1'b1;
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
