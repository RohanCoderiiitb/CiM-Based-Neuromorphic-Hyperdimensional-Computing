// cim_neurohdc_pkg.sv - EVERY parameter of the Phase 1E RTL lives here (no numbers in module bodies).
// Source tags: [S] NeuroHDC paper, [P0] frozen in Phase 0 (01_integer_reference_model/docs/bitwidth_table.md),
//              [1B] 1B handoff, [D] design choice made in 1E.
package cim_neurohdc_pkg;

  // ------------------------------------------------------------------ algorithm constants [S]
  localparam int N_NEURONS = 20;  // [S] SIV-B1 spiking neurons
  localparam int N_TIMESTEPS = 100;  // [S] SIV-A timesteps T
  localparam int N_INPUTS = 512;  // [S] eq.19: 2 polarities x 16 x 16
  localparam int GRID_DIM = 16;  // [S] eq.19 spatial grid after sum-pooling
  localparam int W_GRID = 4;  // [D] bits of one grid coordinate (0..15)

  // ------------------------------------------------------------------ frozen widths [P0]
  localparam int W_ADDR = 9;  // [P0] 512 addresses
  localparam int W_WEIGHT = 8;  // [S] int8 weights, 8 bit-planes per weight
  localparam int W_COUNT = 11;  // [P0] counter width (measured max 1208 < 2047)
  localparam int W_X = 21;  // [P0] MVM output, signed
  localparam int W_V = 26;  // [P0] membrane potential, signed (negative drift sets the width)
  localparam int W_THRESH = 15;  // [P0] threshold, signed
  localparam int F_FRAC = 0;  // [P0] no fractional bits anywhere
  localparam int W_NEVENTS = 21;  // [P0] n_events register
  localparam int W_ACC = 22;  // [P0] timestep accumulator (n + T fits)
  localparam int W_TSTEP = 7;  // [D] timestep index, 0..127 covers T = 100

  // ------------------------------------------------------------------ derived structure [D]
  localparam int N_WCOLS = N_NEURONS * W_WEIGHT;  // 160 crossbar columns (neuron x weight bit-plane)
  localparam int W_BIT_IDX = 4;  // count bit-row index 0..10
  localparam int W_GRP = 9;  // group index; up to 512 groups (g = 1)
  localparam int W_MATCH = 10;  // match count 0..512
  localparam int W_M_FLAT = N_WCOLS * W_MATCH;  // flat bus of all 160 match counts (column j*8+k at bit (j*8+k)*W_MATCH); flat, not packed-2D, so Icarus can index it
  localparam int W_PCOUNT = 10;  // popcount of a 512-bit row (0..512)
  localparam int W_FOLD = 29;  // signed width of one folded bit-row contribution (+ guard bit)
  localparam int SIGN_PLANE = W_WEIGHT - 1;  // weight bit-plane 7 is the int8 sign bit => NEGATIVE weight
  localparam int W_STAT = 32;  // instrumentation counters

  // ------------------------------------------------------------------ design-point defaults
  localparam int ROWS_PER_GROUP_DEFAULT = 8;  // [1B] g = 8; the RTL is bit-exact for every g
  localparam int N_PARALLEL_COLS_DEFAULT = N_WCOLS;  // [1B] 160: all columns per read (11 x 512/g reads); 20: one plane at a time (88 x 512/g)
  localparam bit PLANE_SKIP_EN_DEFAULT = 1'b1;  // [1E] skip all-zero count bit-rows
  localparam bit INSTRUMENT_EN_DEFAULT = 1'b1;  // [1E] activity / skip counters (Phase 5 handoff)
  localparam bit GEOM_NMNIST_DEFAULT = 1'b0;  // [1E] reset value of the sensor geometry: 0 = DVS-Gesture 128x128, 1 = N-MNIST 34x34 (runtime-writable)

  // ------------------------------------------------------------------ pipeline latencies [D]
  localparam int MACRO_LAT = 1;  // cim_macro registers its result
  localparam int ACC_LAT = 1;  // shift_accum registers its accumulators
  localparam int DRAIN_CYCLES = MACRO_LAT + ACC_LAT;  // cycles after the last read before X is final

  // ------------------------------------------------------------------ address generator [S] eq.19
  localparam int W_COORD = 7;  // [D] x, y coordinate width (DVS 0..127)
  localparam int W_COORD_MUL = 9;  // [D] reciprocal multiplier width
  localparam int COORD_SHIFT = 10;  // [D] floor(16 x / W) = (x * MUL) >> COORD_SHIFT
  localparam int COORD_MUL_DVS = 128;  // 16 * 2^10 / 128 exactly: (x*128)>>10 == x>>3  (128x128 sensor)
  localparam int COORD_MUL_NMNIST = 482;  // round(16 * 2^10 / 34); exhaustively == floor(16 x / 34) for x = 0..127 (scripts/derive_recip.py)
  localparam int W_AER = 16;  // AER event word
  localparam int AER_SHIFT_DVS = 7;  // word = p<<14 | y<<7 | x
  localparam int AER_SHIFT_NMNIST = 6;  // word = p<<12 | y<<6 | x

  // ------------------------------------------------------------------ weight load [D]
  localparam int W_WL_WORD = 32;  // shift-in word = one macro's slice (4 neurons x 8 planes) of one address
  localparam int N_MACROS = N_WCOLS / W_WL_WORD;  // 5 macros of 512 x 32 (NeuroHDC organisation)
  localparam int W_MACRO_IDX = 3;
  localparam int N_WL_WORDS = N_MACROS * N_INPUTS;  // 2560 words, macro-major, address 0 first

  // ------------------------------------------------------------------ config register map [D]
  localparam int W_CFG_ADDR = 5;
  localparam int CFG_THRESH_BASE = 0;  // 0..19: threshold of neuron j
  localparam int CFG_N_EVENTS = 20;  // events in the sample (event_ctr n)
  localparam int CFG_COORD_MUL = 21;  // addr_gen reciprocal multiplier
  localparam int CFG_AER_SHIFT = 22;  // AER field width
  localparam int CFG_THRESH_SHARED = 23;  // 1: every neuron uses threshold register 0 (N-MNIST per-tensor)
  localparam int W_CFG_DATA = W_NEVENTS;

  // ------------------------------------------------------------------ top-level FSM [D]
  localparam int W_TOP_STATE = 2;
  localparam logic [W_TOP_STATE-1:0] ST_IDLE = 2'd0;  // reset; configuration and start accepted
  localparam logic [W_TOP_STATE-1:0] ST_LOAD = 2'd1;  // weight image shifting in
  localparam logic [W_TOP_STATE-1:0] ST_RUN = 2'd2;  // per-timestep loop
  localparam logic [W_TOP_STATE-1:0] ST_DONE = 2'd3;  // all timesteps emitted; new sample or reload accepted

endpackage
