// plane_seq.sv - block D. Sequencer of the crossbar reads of one timestep.
//   for each count bit-row b = 0 .. W_COUNT-1:
//        if the bit-row is all zeros -> SKIP it (one check cycle, no group reads)       [PLANE_SKIP_EN]
//        else for each of the ceil(512/g) groups: issue one read (b, group)
// A skipped bit-row avoids N_GROUPS reads (64 at g = 8, x8 planes when planes are sensed one at a time).
//
// N_PARALLEL_COLS selects the column-sensing assumption that 1C has not settled:
//   160 : all 160 columns (20 neurons x 8 weight bit-planes) sensed by one read      -> 11 x 512/g reads / timestep
//   20  : one weight bit-plane (20 columns) per read, 8 passes per (bit-row, group)   -> 88 x 512/g reads / timestep
// Both counts are instrumented in either mode (reads_allcols_o, reads_plane_o); reads_issued_o is the mode's actual cycles.
// `group_idx_o` accompanies every read so the analog side can select its per-group comparator ladder (1B interface addition).
module plane_seq
  import cim_neurohdc_pkg::*;
#(
    parameter int ROWS_PER_GROUP = ROWS_PER_GROUP_DEFAULT,
    parameter int N_PARALLEL_COLS = N_PARALLEL_COLS_DEFAULT,
    parameter bit PLANE_SKIP_EN = PLANE_SKIP_EN_DEFAULT
) (
    input  logic                 clk_i,
    input  logic                 rst_n_i,
    input  logic                 start_i,          // begin the reads of one timestep (sequencer idle)
    input  logic                 row_nz_i,         // the count bit-row currently selected is non-zero
    output logic [W_BIT_IDX-1:0] row_sel_o,        // count bit-row index b (also drives count_mem)
    output logic                 rd_valid_o,       // a crossbar read is issued this cycle
    output logic [W_GRP-1:0]     group_idx_o,      // group of ROWS_PER_GROUP consecutive rows
    output logic [W_WEIGHT-1:0]  plane_mask_o,     // weight bit-planes sensed by this read
    output logic                 rd_last_o,        // last read of this bit-row (shift_accum folds the row)
    output logic                 done_o,           // one-cycle pulse: all bit-rows walked
    output logic                 busy_o,
    output logic [W_STAT-1:0]    rows_skipped_o,   // this timestep
    output logic [W_STAT-1:0]    rows_read_o,
    output logic [W_STAT-1:0]    reads_allcols_o,  // (bit-row, group) activations: 11 x 512/g form
    output logic [W_STAT-1:0]    reads_plane_o,    // x W_WEIGHT: 88 x 512/g form
    output logic [W_STAT-1:0]    reads_issued_o,   // reads actually issued in this configuration
    output logic                 assert_fail_o
);
  localparam int N_GROUPS = (N_INPUTS + ROWS_PER_GROUP - 1) / ROWS_PER_GROUP;
  localparam int N_PASSES = N_WCOLS / N_PARALLEL_COLS;
  localparam logic [W_BIT_IDX-1:0] LAST_ROW = W_BIT_IDX'(W_COUNT - 1);
  localparam logic [W_GRP-1:0] LAST_GRP = W_GRP'(N_GROUPS - 1);
  localparam logic [W_BIT_IDX-1:0] LAST_PASS = W_BIT_IDX'(N_PASSES - 1);
  localparam logic [W_WEIGHT-1:0] ALL_PLANES = '1;
  localparam logic [W_STAT-1:0] STAT_ONE = W_STAT'(1);

  typedef enum logic [1:0] {
    S_IDLE,
    S_CHECK,
    S_READ
  } state_e;

  state_e                 state_q;
  logic   [W_BIT_IDX-1:0] b_q;
  logic   [    W_GRP-1:0] grp_q;
  logic   [W_BIT_IDX-1:0] pass_q;
  logic                   done_q;
  logic   [   W_STAT-1:0] skipped_q;
  logic   [   W_STAT-1:0] rows_read_q;
  logic   [   W_STAT-1:0] allcols_q;
  logic   [   W_STAT-1:0] plane_q;
  logic   [   W_STAT-1:0] issued_q;

  logic                   last_grp;
  logic                   last_pass;
  logic                   last_row;
  logic                   skip_row;

  assign last_grp       = (grp_q == LAST_GRP);
  assign last_pass      = (pass_q == LAST_PASS);
  assign last_row       = (b_q == LAST_ROW);
  assign skip_row       = PLANE_SKIP_EN && !row_nz_i;

  assign row_sel_o      = b_q;
  assign rd_valid_o     = (state_q == S_READ);
  assign group_idx_o    = grp_q;
  assign plane_mask_o   = (N_PASSES == 1) ? ALL_PLANES : (W_WEIGHT'(1) << pass_q);
  assign rd_last_o      = rd_valid_o && last_grp && last_pass;
  assign done_o         = done_q;
  assign busy_o         = (state_q != S_IDLE);
  assign rows_skipped_o = skipped_q;
  assign rows_read_o    = rows_read_q;
  assign reads_allcols_o = allcols_q;
  assign reads_plane_o  = plane_q;
  assign reads_issued_o = issued_q;

  always_ff @(posedge clk_i) begin
    if (!rst_n_i) begin
      state_q     <= S_IDLE;
      b_q         <= '0;
      grp_q       <= '0;
      pass_q      <= '0;
      done_q      <= 1'b0;
      skipped_q   <= '0;
      rows_read_q <= '0;
      allcols_q   <= '0;
      plane_q     <= '0;
      issued_q    <= '0;
    end else begin
      done_q <= 1'b0;
      unique case (state_q)
        S_IDLE: begin
          if (start_i) begin
            state_q     <= S_CHECK;
            b_q         <= '0;
            grp_q       <= '0;
            pass_q      <= '0;
            skipped_q   <= '0;
            rows_read_q <= '0;
            allcols_q   <= '0;
            plane_q     <= '0;
            issued_q    <= '0;
          end
        end
        S_CHECK: begin
          if (skip_row) begin
            skipped_q <= skipped_q + STAT_ONE;
            if (last_row) begin
              state_q <= S_IDLE;
              done_q  <= 1'b1;
            end else b_q <= b_q + W_BIT_IDX'(1);
          end else begin
            state_q     <= S_READ;
            grp_q       <= '0;
            pass_q      <= '0;
            rows_read_q <= rows_read_q + STAT_ONE;
          end
        end
        S_READ: begin
          issued_q <= issued_q + STAT_ONE;
          if (pass_q == '0) begin
            allcols_q <= allcols_q + STAT_ONE;
            plane_q   <= plane_q + W_STAT'(W_WEIGHT);
          end
          if (!last_grp) grp_q <= grp_q + W_GRP'(1);
          else begin
            grp_q <= '0;
            if (!last_pass) pass_q <= pass_q + W_BIT_IDX'(1);
            else begin
              pass_q  <= '0;
              state_q <= S_CHECK;
              if (last_row) begin
                state_q <= S_IDLE;
                done_q  <= 1'b1;
              end else b_q <= b_q + W_BIT_IDX'(1);
            end
          end
        end
        default: state_q <= S_IDLE;
      endcase
    end
  end

  // ------------------------------------------------------------------ assertions (simulation only)
  logic fail_q;
  assign assert_fail_o = fail_q;
`ifndef SYNTHESIS
  always_ff @(posedge clk_i) begin
    if (!rst_n_i) fail_q <= 1'b0;
    else begin
      if (start_i && state_q != S_IDLE) begin
        $display("[ASSERT FAIL] %m: start while the sequencer is busy");
        fail_q <= 1'b1;
      end
      if (rd_valid_o && !(grp_q < W_GRP'(N_GROUPS))) begin
        $display("[ASSERT FAIL] %m: group index %0d out of range", grp_q);
        fail_q <= 1'b1;
      end
      if (state_q == S_READ && PLANE_SKIP_EN && !row_nz_i) begin
        $display("[ASSERT FAIL] %m: reading an all-zero bit-row %0d", b_q);
        fail_q <= 1'b1;
      end
    end
  end
`else
  assign fail_q = 1'b0;
`endif
endmodule
