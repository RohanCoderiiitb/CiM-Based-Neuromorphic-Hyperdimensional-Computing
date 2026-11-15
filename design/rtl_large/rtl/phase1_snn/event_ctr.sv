// event_ctr.sv - block C. Decides when a timestep ends: event j (1-based) belongs to timestep t when ceil(t n/T) < j <= ceil((t+1) n/T), so a timestep holds N_e or N_e+1 events - never a fixed count.
//
// n = N_e T + r (0 <= r < T). The size of timestep t is  N_e + [ceil((t+1) r/T) - ceil(t r/T)]  =  N_e + (r > e_t)  with the 7-bit state  e_t = T ceil(t r/T) - t r  (e_0 = 0,
// e_{t+1} = e_t - r + T if r > e_t else e_t - r). That is the same rule as the earlier `acc += T; if (acc >= n) acc -= n` accumulator (snn_ctrl asserts the floor/ceil bin sizes at every hand-over),
// but the per-event hardware is a DOWN-COUNTER of the events left in the timestep (`left_q`): lane k ends the timestep iff left <= k+1, a compare of a register against a constant. N_LANES
// events can be accepted in one cycle (a PREFIX of the lanes); the controller accepts no lane behind the first one that ends the timestep.
// N_e and r come from a restoring divider (n / T, one bit per cycle, W_NEVENTS cycles) that runs when the host writes n: `ready_o` is low meanwhile (and until the sample-start load has happened), so
// the first event of a sample waits at most W_NEVENTS + 1 cycles. n >= T is required (a timestep would otherwise hold no event): rejected loudly (assertion).
import cim_neurohdc_pkg::N_LANES;
import cim_neurohdc_pkg::N_TIMESTEPS;
import cim_neurohdc_pkg::W_LANES;
import cim_neurohdc_pkg::W_NEVENTS;
import cim_neurohdc_pkg::W_TSTEP;

module event_ctr (
    input  logic                 clk_i,
    input  logic                 rst_n_i,
    input  logic                 clr_i,          // sample start: first timestep, counters cleared
    input  logic                 cfg_n_we_i,     // write the sample's event count n
    input  logic [W_NEVENTS-1:0] cfg_n_i,
    input  logic [W_LANES-1:0]   n_acc_i,        // lanes accepted this cycle (a prefix; 0 = none)
    output logic [N_LANES-1:0]   bnd_pre_o,      // lane k, if accepted, ends its timestep (valid for the first such lane)
    output logic                 bnd_acc_o,      // the last accepted lane ends its timestep (combinational)
    output logic                 ready_o,        // the divider is idle and the sample-start load is done
    output logic [  W_TSTEP-1:0] tstep_o,        // timestep this event belongs to
    output logic [W_NEVENTS-1:0] n_o,
    output logic [W_NEVENTS-1:0] ev_total_o,     // events accepted so far in this sample
    output logic                 sample_done_o,  // all T boundaries emitted
    output logic                 assert_fail_o
);
  localparam int T = N_TIMESTEPS;
  localparam int W_R = $clog2(T) + 1;  // remainder register width (rem < T, and the working value 2 rem + 1 < 2 T)
  localparam int W_DC = $clog2(W_NEVENTS + 1);

  logic [W_NEVENTS-1:0] n_q;
  // ---------------------------------------------------------------- divider n / T
  logic [W_NEVENTS-1:0] dv_q;  // dividend, shifted out MSB first
  logic [W_NEVENTS-1:0] quo_q;
  logic [      W_R-1:0] rem_q;
  logic [      W_DC-1:0] dv_cnt_q;
  logic                 dv_busy_q;
  logic [W_NEVENTS-1:0] ne_q;  // N_e
  logic [      W_R-1:0] rm_q;  // r
  logic [      W_R-1:0] rem_n;
  logic                 sub;
  assign rem_n = {rem_q[W_R-2:0], dv_q[W_NEVENTS-1]};
  assign sub   = (rem_n >= W_R'(T));

  // ---------------------------------------------------------------- per-timestep state
  logic [W_NEVENTS-1:0] left_q;  // events still to come in the current timestep
  logic [      W_R-1:0] e_q;  // e_t of the NEXT boundary computation
  logic                 ld_pend_q;  // a sample start waits for the divider
  logic [  W_TSTEP-1:0] tstep_q;
  logic [W_NEVENTS-1:0] total_q;

  logic                 c_next;
  logic [      W_R-1:0] e_next;
  logic [W_NEVENTS-1:0] left_next;
  assign c_next    = (rm_q > e_q);
  assign e_next    = c_next ? (e_q - rm_q + W_R'(T)) : (e_q - rm_q);
  assign left_next = ne_q + W_NEVENTS'(c_next);

  always_comb begin
    for (int k = 0; k < N_LANES; k++) bnd_pre_o[k] = (left_q <= W_NEVENTS'(k + 1));
  end
  assign bnd_acc_o     = (n_acc_i != '0) && bnd_pre_o[n_acc_i-W_LANES'(1)];
  assign tstep_o       = tstep_q;
  assign n_o           = n_q;
  assign ev_total_o    = total_q;
  assign sample_done_o = (tstep_q == W_TSTEP'(N_TIMESTEPS));
  assign ready_o       = !dv_busy_q && !ld_pend_q;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      n_q       <= '0;
      dv_q      <= '0;
      quo_q     <= '0;
      rem_q     <= '0;
      dv_cnt_q  <= '0;
      dv_busy_q <= 1'b0;
      ne_q      <= '0;
      rm_q      <= '0;
      left_q    <= '0;
      e_q       <= '0;
      ld_pend_q <= 1'b0;
      tstep_q   <= '0;
      total_q   <= '0;
    end else begin
      // divider
      if (cfg_n_we_i) begin
        n_q       <= cfg_n_i;
        dv_q      <= cfg_n_i;
        quo_q     <= '0;
        rem_q     <= '0;
        dv_cnt_q  <= W_DC'(W_NEVENTS);
        dv_busy_q <= 1'b1;
      end else if (dv_busy_q) begin
        dv_q     <= dv_q << 1;
        quo_q    <= {quo_q[W_NEVENTS-2:0], sub};
        rem_q    <= sub ? (rem_n - W_R'(T)) : rem_n;
        dv_cnt_q <= dv_cnt_q - W_DC'(1);
        if (dv_cnt_q == W_DC'(1)) begin
          dv_busy_q <= 1'b0;
          ne_q      <= {quo_q[W_NEVENTS-2:0], sub};
          rm_q      <= sub ? (rem_n - W_R'(T)) : rem_n;
        end
      end
      // sample start: load the first timestep once N_e and r are known
      if (clr_i) begin
        ld_pend_q <= 1'b1;
        tstep_q   <= '0;
        total_q   <= '0;
      end else if (ld_pend_q && !dv_busy_q && !cfg_n_we_i) begin
        ld_pend_q <= 1'b0;
        left_q    <= left_next;  // e_q = 0 at this point (cleared below)
        e_q       <= e_next;
      end else if (n_acc_i != '0) begin
        total_q <= total_q + W_NEVENTS'(n_acc_i);
        if (bnd_acc_o) begin
          tstep_q <= tstep_q + W_TSTEP'(1);
          left_q  <= left_next;
          e_q     <= e_next;
        end else left_q <= left_q - W_NEVENTS'(n_acc_i);
      end
      if (clr_i) e_q <= '0;
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
      if ((n_acc_i != '0) && !ready_o) begin
        $display("[ASSERT FAIL] %m: event accepted before the event counter is ready");
        fail_q <= 1'b1;
      end
      if ((n_acc_i != '0) && sample_done_o) begin
        $display("[ASSERT FAIL] %m: event accepted after all T boundaries");
        fail_q <= 1'b1;
      end
      // a boundary may only be the LAST accepted lane
      for (int k = 0; k + 1 < N_LANES; k++) begin
        if (W_LANES'(k + 1) < n_acc_i && bnd_pre_o[k]) begin
          $display("[ASSERT FAIL] %m: lane %0d accepted behind a timestep boundary", k + 2);
          fail_q <= 1'b1;
        end
      end
      if ((n_acc_i != '0) && (left_q < W_NEVENTS'(n_acc_i))) begin
        $display("[ASSERT FAIL] %m: %0d lanes accepted but only %0d events are left in the timestep", n_acc_i, left_q);
        fail_q <= 1'b1;
      end
      if (tstep_q > W_TSTEP'(N_TIMESTEPS)) begin
        $display("[ASSERT FAIL] %m: more than T boundaries (%0d)", tstep_q);
        fail_q <= 1'b1;
      end
      // the LAST boundary (event n) must have counted exactly n events
      if (bnd_acc_o && tstep_q == W_TSTEP'(N_TIMESTEPS - 1) && (total_q + W_NEVENTS'(n_acc_i) != n_q)) begin
        $display("[ASSERT FAIL] %m: at the last boundary events must equal n (events=%0d n=%0d)", total_q + W_NEVENTS'(n_acc_i), n_q);
        fail_q <= 1'b1;
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
