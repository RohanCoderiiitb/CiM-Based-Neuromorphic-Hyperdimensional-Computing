// cim_neurohdc_pkg.sv - EVERY parameter of the Phase 1E RTL lives here (no numbers in module bodies).
// Source tags: [S] NeuroHDC paper, [P0] frozen in Phase 0 (design/reference_model/docs/bitwidth_table.md),
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
  localparam int ROWS_PER_GROUP_DEFAULT = 4;  // [1B] g = 4 (the recommended point of 1F); the RTL is bit-exact for every g that divides 512
  localparam int N_PARALLEL_COLS_DEFAULT = 40;  // [1F] 40 columns per pass, 4 passes per read: the supply-limited design point (peak 8.7 mA, 1 nF); 160: all columns at once; 20: one plane per pass
  localparam bit PLANE_SKIP_EN_DEFAULT = 1'b1;  // [1E] skip all-zero count bit-rows
  localparam bit CLOCK_GATING_DEFAULT = 1'b1;  // [D] digital-energy pass: count_mem and the class-HV sign table use explicit hierarchical clock gates (clk_gate_tree); 0: plain enabled flip-flops
  localparam bit OPERAND_ISOLATION_DEFAULT = 1'b1;  // [D] digital-energy pass: shift_accum's fold network is fed zeros except when its result is consumed
  localparam bit INSTRUMENT_EN_DEFAULT = 1'b1;  // [1E] activity / skip counters (Phase 5 handoff)
  localparam int LOCAL_QUERY_BUSY = 0;
  localparam int EXIT_CLK_FREE = 0;  // [D] 1 (the large chip): the exit controller runs on the free clock, not behind the HDC clock gate (every register has its own enable; timing of the ready outputs)  // [D] 1: the intake hold comes from a replica of the query valids beside the SNN (the large chip; timing on a large die), 0: wired from the query stage
  localparam bit GEOM_NMNIST_DEFAULT = 1'b0;  // [1E] reset value of the sensor geometry: 0 = DVS-Gesture 128x128, 1 = N-MNIST 34x34 (runtime-writable)

  // ------------------------------------------------------------------ event ingest: N_LANES lanes, banked counter memory with a short request queue per bank [D]
  localparam int N_COUNT_BANKS = 4;  // [D] the 512 counters live in N_COUNT_BANKS single-port SRAM macros selected by the low address bits
  localparam int LB_COUNT = $clog2(N_COUNT_BANKS);  // low address bits that select the bank
  localparam int W_BANK_ADDR = W_ADDR - LB_COUNT;  // address bits inside a bank
  localparam int N_BANK_WORDS = N_INPUTS / N_COUNT_BANKS;  // words per bank macro
  localparam int N_LANES = 3;  // [D] events accepted per cycle (parallel AER input: lane 0 is the ordinary valid/ready port, lanes 1.. are the extra lanes)
  localparam int N_XL = N_LANES - 1;  // extra lanes
  localparam int W_LANES = $clog2(N_LANES + 1);  // bits of a lane count 0..N_LANES
  localparam int N_DIRTY_GS = 2;  // [D] counter groups per dirty flag (the scan fetches every group of a flagged block; a fetch of a clean group costs one cycle that the crossbar reads hide)
  // packed-row crossbar reads [D]: a read drives S_ROWS arbitrary ACTIVE rows of one count bit-plane, all inside one position band (the macro's row gain varies smoothly along the bit-line, so rows of one band
  // differ by under ~2 %); the scan packs the active rows of a plane into reads instead of reading fixed groups of adjacent rows
  localparam int N_BANDS = 4;  // [D] position bands of the row array
  localparam int W_BAND = $clog2(N_BANDS);
  localparam int W_RB = $clog2(N_INPUTS / N_BANDS);  // row index inside a band
  localparam int S_ROWS = 5;  // [D] rows driven by one read (the sense chain resolves 0..S_ROWS matches); >= ROWS_PER_GROUP, and 0..S_ROWS fits the W_M-bit match count
  localparam int N_PK = 3;  // [D] count bit-planes packed side by side in one pass over the dirty groups
  localparam int N_BQ = 4;  // [D] entries of the request queue in front of every counter bank (an event merges into the last entry when it is the same counter; model: 2.80 events/cycle on DVS streams with 3 lanes)

  // ------------------------------------------------------------------ pipeline latencies [D]
  localparam int MACRO_LAT = 1;  // cim_macro registers its result
  localparam int ACC_LAT = 1;  // the neurons register V
  localparam int DRAIN_CYCLES = MACRO_LAT + ACC_LAT;  // cycles after the last read before X is final

  // ------------------------------------------------------------------ address generator [S] eq.19
  localparam int W_COORD = 7;  // [D] x, y coordinate width (DVS 0..127)
  localparam int W_COORD_MUL = 9;  // [D] reciprocal multiplier width
  localparam int COORD_SHIFT = 10;  // [D] floor(16 x / W) = (x * MUL) >> COORD_SHIFT
  localparam int COORD_MUL_DVS = 128;  // 16 * 2^10 / 128 exactly: (x*128)>>10 == x>>3  (128x128 sensor)
  localparam int COORD_MUL_NMNIST = 482;  // round(16 * 2^10 / 34); exhaustively == floor(16 x / 34) for x = 0..127 (scripts/derive_recip.py)
  localparam int W_AER = 16;  // AER event word
  localparam int AER_SHIFT_DVS = 7;  // word = p<<14 | y<<7 | x
  localparam int AER_SHIFT_NMNIST = 6;  // word = p<<12 | y<<6 | x   (the SECOND geometry's field width: 34 x 34 on this chip)
  localparam int GEO2_W = 34;  // [D] second geometry: sensor width and height (eq. 19 tables built from these)
  localparam int GEO2_H = 34;

  // ------------------------------------------------------------------ weight load [D]
  localparam int W_WL_WORD = 32;  // shift-in word = one macro's slice (4 neurons x 8 planes) of one address
  localparam int N_MACROS = N_WCOLS / W_WL_WORD;  // 5 macros of 512 x 32 (NeuroHDC organisation)
  localparam int W_MACRO_IDX = $clog2(N_MACROS);  // 3 bits for 5 macros
  localparam int N_WL_WORDS = N_MACROS * N_INPUTS;  // 2560 words, macro-major, address 0 first

  // ------------------------------------------------------------------ config register map [D]
  localparam int W_CFG_ADDR = $clog2(N_NEURONS + 4);  // thresholds + 4 registers: 5 bits for 20 neurons
  localparam int CFG_THRESH_BASE = 0;  // 0..19: threshold of neuron j
  localparam int CFG_N_EVENTS = N_NEURONS;  // events in the sample (event_ctr n); 20 for 20 neurons
  localparam int CFG_COORD_MUL = N_NEURONS + 1;  // addr_gen reciprocal multiplier
  localparam int CFG_AER_SHIFT = N_NEURONS + 2;  // AER field width
  localparam int CFG_THRESH_SHARED = N_NEURONS + 3;  // 1: every neuron uses threshold register 0 (N-MNIST per-tensor)
  localparam int W_CFG_DATA = W_NEVENTS;

  // ------------------------------------------------------------------ top-level FSM [D]
  localparam int W_TOP_STATE = 2;
  localparam logic [W_TOP_STATE-1:0] ST_IDLE = 2'd0;  // reset; configuration and start accepted
  localparam logic [W_TOP_STATE-1:0] ST_LOAD = 2'd1;  // weight image shifting in
  localparam logic [W_TOP_STATE-1:0] ST_RUN = 2'd2;  // per-timestep loop
  localparam logic [W_TOP_STATE-1:0] ST_DONE = 2'd3;  // all timesteps emitted; new sample or reload accepted

endpackage
