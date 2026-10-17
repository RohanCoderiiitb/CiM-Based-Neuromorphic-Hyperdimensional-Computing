// event_ctr.sv - block C. Decides when a timestep ends: event k belongs to timestep floor(k*T/n), so a timestep holds
// N_e or N_e+1 events - never a fixed count.   (The earlier spec's "every N_e events" rule was wrong.)
//
//   on sample start (clr_i):  acc = 0
//   per accepted event:       acc += T ; if (acc >= n) { acc -= n ; boundary }
//
// One adder, one subtractor, one comparator, two registers (acc, timestep). No divider.
// The loop `while (acc >= n)` can fire more than once only when n < T. That case is REJECTED loudly (assertion
// `n >= T at sample start`), not silently treated as single-fire.






import cim_neurohdc_pkg::N_TIMESTEPS;
import cim_neurohdc_pkg::W_ACC;
import cim_neurohdc_pkg::W_NEVENTS;
import cim_neurohdc_pkg::W_TSTEP;

module event_ctr (
    input  logic                 clk_i,
    input  logic                 rst_n_i,
    input  logic                 clr_i,          // sample start: acc = 0, timestep = 0
    input  logic                 cfg_n_we_i,     // write the sample's event count n
    input  logic [W_NEVENTS-1:0] cfg_n_i,
    input  logic                 ev_valid_i,     // an event is accepted this cycle
    output logic                 boundary_o,     // this event is the LAST of its timestep (combinational)
    output logic [  W_TSTEP-1:0] tstep_o,        // timestep this event belongs to
    output logic [W_NEVENTS-1:0] n_o,
    output logic [W_NEVENTS-1:0] ev_total_o,     // events accepted so far in this sample
    output logic                 sample_done_o,  // all T boundaries emitted
    output logic                 assert_fail_o
);
  localparam logic [W_ACC-1:0] T_ACC = W_ACC'(N_TIMESTEPS);

  logic [W_NEVENTS-1:0] n_q;
  logic [W_ACC-1:0] acc_q, acc_d, acc_sum;
  logic [  W_TSTEP-1:0] tstep_q;
  logic [W_NEVENTS-1:0] total_q;

  assign acc_sum       = acc_q + T_ACC;
  assign boundary_o    = ev_valid_i && (acc_sum >= W_ACC'(n_q));
  assign acc_d         = boundary_o ? (acc_sum - W_ACC'(n_q)) : acc_sum;
  assign tstep_o       = tstep_q;
  assign n_o           = n_q;
  assign ev_total_o    = total_q;
  assign sample_done_o = (tstep_q == W_TSTEP'(N_TIMESTEPS));

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      n_q     <= '0;
      acc_q   <= '0;
      tstep_q <= '0;
      total_q <= '0;
    end else begin
      if (cfg_n_we_i) n_q <= cfg_n_i;
      if (clr_i) begin
        acc_q   <= '0;
        tstep_q <= '0;
        total_q <= '0;
      end else if (ev_valid_i) begin
        acc_q   <= acc_d;
        total_q <= total_q + W_NEVENTS'(1);
        if (boundary_o) tstep_q <= tstep_q + W_TSTEP'(1);
      end
    end
  end

  // ------------------------------------------------------------------ assertions (simulation only; never disabled)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else begin
      if (clr_i && (n_q < W_NEVENTS'(N_TIMESTEPS))) begin
        $display("[ASSERT FAIL] %m: n >= T required at sample start (n=%0d, T=%0d)", n_q, N_TIMESTEPS);
        fail_q <= 1'b1;
      end
      if (ev_valid_i && sample_done_o) begin
        $display("[ASSERT FAIL] %m: event accepted after all T boundaries");
        fail_q <= 1'b1;
      end
      if (ev_valid_i && !(acc_sum < W_ACC'(n_q) + T_ACC)) begin
        $display("[ASSERT FAIL] %m: acc >= n + T (acc+T=%0d, n=%0d)", acc_sum, n_q);
        fail_q <= 1'b1;
      end
      if (n_q != '0 && acc_q >= W_ACC'(n_q)) begin
        $display("[ASSERT FAIL] %m: acc >= n (acc=%0d, n=%0d)", acc_q, n_q);
        fail_q <= 1'b1;
      end
      if (tstep_q > W_TSTEP'(N_TIMESTEPS)) begin
        $display("[ASSERT FAIL] %m: more than T boundaries (%0d)", tstep_q);
        fail_q <= 1'b1;
      end
      // the LAST boundary (event n) must leave acc = 0 and have counted exactly n events
      if (boundary_o && tstep_q == W_TSTEP'(N_TIMESTEPS - 1) && (acc_d != '0 || total_q + W_NEVENTS'(1) != n_q)) begin
        $display("[ASSERT FAIL] %m: at the last boundary acc must be 0 and events == n (acc=%0d events=%0d n=%0d)", acc_d, total_q + W_NEVENTS'(1), n_q);
        fail_q <= 1'b1;
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
