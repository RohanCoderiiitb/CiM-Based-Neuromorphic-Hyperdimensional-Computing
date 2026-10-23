// hdc_pkg.sv - every parameter of the Phase 2-4 RTL (HDC query, margin early exit, integration). Phase 1E's cim_neurohdc_pkg.sv is untouched.
// Source tags: [S] NeuroHDC paper, [P0] Phase 0 reference (design/reference_model/model/fixedpoint/hdc_query.py), [D] design choice made in Phase 2-4.
package hdc_pkg;

  // ------------------------------------------------------------------ algorithm / widths
  localparam int N_CLASSES_DEFAULT = 10;  // [P0] DVS-Gesture classes 0..9 (the 11th "other" class is not used); N-MNIST has 10 too
  localparam int N_CLASSES_MAX = 24;  // [D] README Phase 4: N is 10-24; every width below holds for N <= 32
  localparam int W_CLASS = 5;  // [D] class index
  localparam int W_AGREE = 5;  // [P0] XNOR-popcount of one timestep's 20 bits: 0..20
  localparam int W_SCORE = 11;  // [P0] prefix score 0..T*n = 2000
  localparam int W_THETA = 12;  // [P0] margin threshold register
  localparam int THETA_NEVER = (1 << W_THETA) - 1;  // [P0] 4095 > any margin (<= 2000): the exit can never fire
  localparam int W_BIAS = 5;  // [P0] per-class ||a_i||_1, 0..20

  // ------------------------------------------------------------------ class image port (static, like weight_load for the SNN array)
  localparam int W_CM_SEL = 2;
  localparam int CM_SEL_ARRAY = 0;  // [D] unfactorized: 100 words of N x 20 bits (class i slice of timestep t at bits [20 i +: 20]); factorized: 1 word, a_i at [20 i +: 20]
  localparam int CM_SEL_SIGN = 1;  // [D] factorized: 100 words of N bits, b_i[t] at bit i
  localparam int CM_SEL_BIAS = 2;  // [D] factorized: 1 word of N x 5 bits, ||a_i||_1 at [5 i +: 5]
  localparam int W_TADDR = 7;  // [D] timestep address 0..99

  // ------------------------------------------------------------------ top-level configuration bus (7-bit address; 0..31 are forwarded unchanged to snn_top)
  localparam int W_TOP_CFG_ADDR = 7;
  localparam int CFG_THETA = 32;  // [D] early-exit threshold (margin units: XNOR score; the software study's bipolar threshold is twice this)
  localparam int CFG_EXIT_EN = 33;  // [D] runtime enable of the early exit (reset: 1)

  // ------------------------------------------------------------------ build knobs (the four ablation builds are these two parameters)
  localparam bit FACTORIZED_DEFAULT = 1'b1;  // [D] 1: R=1 factorized class HV (20 x N + T x N); 0: unfactorized 2000 x N
  localparam bit EARLY_EXIT_EN_DEFAULT = 1'b1;  // [D] 1: margin comparator + exit FSM built; 0: not built (Phase 3)
  localparam bit CHECK_UNIPOLAR_DEFAULT = 1'b1;  // [D] simulation-only shadow of the unipolar form 2 S.C - ||C||_1; asserts argmax equality at every prefix

  // ------------------------------------------------------------------ pipeline [D]
  localparam int QUERY_STAGES = 4;  // capture, array read + agree + accumulate, top-2, decision: hold cycles = valid + QUERY_STAGES
endpackage
