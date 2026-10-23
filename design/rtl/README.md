# design/rtl - the digital RTL of CIM-NeuroHDC: Phase 1E (SNN) and Phases 2-4 (HDC query, integration, margin early exit)

Everything digital except the crossbar: event front end, count memory, plane sequencer, shift-accumulate, IF neuron array, controller. The crossbar is a
**behavioural** model (`cim_macro.sv`); no analog, no PDK. The RTL is bit-exact against the Phase 0 integer model
(`01_integer_reference_model/model/fixedpoint/int_model.py`, imported by the testbenches, never reimplemented).

Full results and every measured number: [`reports/phase1e_report.md`](../../reports/phase1e_report.md).

## Run it

```
python3 -m venv venv && venv/bin/pip install -r 03_rtl/requirements.txt   # once, from the repository root
03_rtl/scripts/run_everything.sh                                           # everything below, then regenerates the report
03_rtl/scripts/run_everything.sh --skip-icarus-regression                  # ~25 min instead of hours; criterion 6 not re-established
```

Tools: Verilator 5.052, Icarus Verilog 13, Yosys 0.69, Verible v0.0-4296 (on `PATH` or under `03_rtl/tools/verible-*/`, which is gitignored), cocotb 2.1.
The stages (each also runnable alone, all log to `results/logs/`):

| script | what |
|---|---|
| `scripts/lint.sh` | Verible lint + format check, `verilator --lint-only -Wall` on the design and on every block |
| `scripts/level1_guard.py` | Phase 0 pytest + `int_model` reproduces the stored golden traces + AER stream -> address -> count check |
| `tb/cocotb/run_unit_tests.py` | per-block and MVM-unit cocotb tests on Verilator and Icarus, including the g-sweep (X identical for every g) |
| `scripts/run_all_regressions.sh` | Verilator regression: DVS-Gesture 240 samples x 3 seeds, g = 4..64, 20-column mode, no-skip, real/shuffled/sorted streams with random gaps, N-MNIST 1,000 samples |
| `scripts/run_icarus_regressions.sh` | the same configurations on Icarus, then `scripts/compare_sims.py` compares every timestep (spikes, X, V, all counters) with Verilator |
| `scripts/synth_check.sh` | generic Yosys (no liberty): `check -assert`, zero `$dlatch`, gate/flop/depth smell test |
| `scripts/make_report.py` | regenerates the report from the logged artefacts |

One regression run: `venv/bin/python 03_rtl/scripts/run_regression.py --dataset dvsgesture --seed 0 --rows all --g 8 [--cols 20] [--no-skip] [--gap 1] [--sim icarus --chunks 10]`.

## Blocks (`rtl/phase1_snn/`)

| file | block |
|---|---|
| `addr_gen.sv` | A: AER (x, y, p) -> 9-bit address, combinational; eq. 19 with a reciprocal multiply (no divider; 34x34 N-MNIST via 482/1024) |
| `count_mem.sv` | B: 512 x 11-bit flip-flop counters, 2-stage read-modify-write with forwarding, one-cycle bulk wipe, bit-row read-out |
| `event_ctr.sv` | C: timestep boundary counter `acc += T; if acc >= n {acc -= n; boundary}` (floor(k*T/n) rule) |
| `plane_seq.sv` | D: walks the 11 count bit-rows, skips all-zero rows, issues 512/g group reads per row, instruments reads / skips; emits `group_idx_o` per read |
| `cim_macro.sv` | E: behavioural crossbar - per-column match counts of one group (blackbox in synthesis) |
| `weight_load.sv` | F: shifts the 5 x 512 x 32-bit weight image into the macros |
| `shift_accum.sv` | G: combines match counts into X = sum +-2^(b+k) m (plane 7 negative); computes the `a` term; width-checked |
| `if_neuron_array.sv` | H: 20 integrate-and-fire neurons, V = V + X, spike = V >= thr, hard reset, 26-bit V |
| `spike_reg.sv` | I: holds the 20-bit spike vector S(t) with a one-cycle valid strobe, the timestep index and `done` after the last timestep |
| `snn_ctrl.sv` | I: FSM IDLE -> LOAD -> RUN -> DONE; run sub-states ingest, drain, MVM, update, emit, wipe; `ingest_en` gate (stall, never buffer) |
| `snn_top.sv` | top: config registers, AER unpack, glue |
| `popcount.sv` | recursive popcount tree used by shift_accum / top |

## Parameters

Every parameter lives in `rtl/pkg/cim_neurohdc_pkg.sv` (no numbers in module bodies), tagged with its source ([S] paper, [P0] Phase 0, [1B], [D] design choice):
widths (`W_COUNT` 11, `W_X` 21, `W_V` 26, `W_THRESH` 15, `F_FRAC` 0, `W_NEVENTS` 21, `W_ACC` 22), algorithm constants (20 neurons, T = 100, 512 inputs, 8 weight planes),
pipeline latencies, address-generator constants, weight-load organisation, config register map and top-level states. The experiment knobs are module parameters of `snn_top`:
`ROWS_PER_GROUP` (g, default 8; exact for every g), `N_PARALLEL_COLS` (160 or 20), `PLANE_SKIP_EN`, `INSTRUMENT_EN`; defaults are `*_DEFAULT` in the package.
Sensor geometry (DVS 128x128 vs N-MNIST 34x34) and the shared N-MNIST threshold are runtime configuration registers.

## Handoffs to Phase 5 (all measured, report section 5-8)

- cycles per inference at every g (4, 8, 16, 32, 64) and with 20 columns per read; stall cycles (the design is input-bound: **g sets energy, not latency**)
- crossbar group reads per inference under both column-sensing assumptions (160 vs 20 columns per read), with and without plane skipping (23.9% saved at g = 8)
- mean active addresses 51.0%, weight-bit reads per sample ~26.1 k (15.6x below event-serial), rows skipped per timestep
- flip-flop / gate counts (generic, with and without instrumentation) and the 67-gate longest path (likely to need pipelining; best guess: the fold adder in `shift_accum`)
- `group_idx_o` per read, for the per-group analog ladder; `ingest_en` for Phase 4 early exit

## Golden vectors

`01_integer_reference_model/tb/vectors/` (75 MB) is committed as ordinary files; no Git LFS. Each regression JSON records the SHA-256 of every vector file it used, and `scripts/level1_guard.py` fails if Phase 0's `int_model.py` stops reproducing them.

---

# Phases 2-4: the HDC query, the integration and the margin early exit

Everything above is Phase 1E and is **unchanged**. Phases 2-4 add three directories next to `rtl/phase1_snn/`; the golden model they are checked against is the Phase 0 reference extended in `design/reference_model/model/fixedpoint/hdc_query.py` (written and tested BEFORE the RTL: `design/reference_model/tests/test_hdc_query.py`). Full results: [`reports/phase234_report.md`](../../reports/phase234_report.md); synthesis, power and the ablation table: [`reports/phase5_ppa.md`](../../reports/phase5_ppa.md).

| file | block |
|---|---|
| `rtl/pkg/hdc_pkg.sv` | every parameter of Phases 2-4 (widths, class-image port, config addresses, the two build knobs) |
| `rtl/phase2_hdc/hdc_class_array.sv` | **behavioural model of the class-HV CIM array**, both mappings (stationary 20 x N array -> AND-popcount per class; or the 2000 x N memory -> a class slice); black box in synthesis (like `cim_macro`) |
| `rtl/phase2_hdc/hdc_score.sv` | the two scoring datapaths: (a) XNOR-popcount of the slice, (b) AND-popcount + bias + sign flip |
| `rtl/phase2_hdc/top2_tree.sv` | leader (lowest index on ties) and second-largest score by a binary tournament - no sort |
| `rtl/phase2_hdc/hdc_query.sv` | the query stage: spike capture, array read, N score accumulators, top-2; the sign table and the bias registers of the factorized mapping; simulation-only checks (the unipolar identity `2 S.C - ||C||_1` at every prefix, agree in range, no spike while scoring) |
| `rtl/phase4_exit/exit_ctrl.sv` | margin comparator against the threshold register, exit FSM, prediction register |
| `rtl/phase3_top/cim_neurohdc_top.sv` | the integration: `snn_top` (instantiated unchanged) -> 20-bit spike waist -> `hdc_query` -> `exit_ctrl`; the event-intake handshake; shared configuration |

Build knobs (parameters of `cim_neurohdc_top`, not edits): `FACTORIZED` (1: R=1 mapping, 0: unfactorized) and `EARLY_EXIT_EN` (1: comparator + exit FSM built, 0: not built = Phase 3). The four ablation builds are `(1,1)` full, `(1,0)` early exit off, `(0,1)` factorization off, `(0,0)` both off.

```
design/rtl/scripts/run_hdc_everything.sh                 # reference tests, lint, elaboration, unit tests, the whole regression matrix on both simulators, synthesis, power, reports
venv/bin/python design/rtl/scripts/run_hdc_regression.py --model r1 --seed 0 --factorized 1 --early-exit 1 --theta 50 --rows all --sim verilator --tag demo
venv/bin/python design/rtl/scripts/run_hdc_matrix.py --sim verilator --set main      # the matrix (resumable);  --set extra | twin;  --sim icarus for the subset profile
venv/bin/python design/rtl/scripts/hdc_compare_all.py     # factorized vs unfactorized, early-exit-disabled vs Phase 3, Icarus vs Verilator: line-by-line per timestep
design/rtl/scripts/lint_hdc.sh   &&   design/rtl/scripts/synth_check_hdc.sh
venv/bin/python design/rtl/scripts/synth_ppa.py && venv/bin/python design/rtl/scripts/synth_power.py && venv/bin/python design/rtl/scripts/phase5_ppa.py
```

`tb/sv/hdc_regress_tb.sv` is the Phase 2-4 counterpart of `snn_regress_tb.sv` (same stimulus format, plus the class image and a per-sample threshold); `tb/common/hdc_golden.py` prepares the jobs from the golden vectors (`design/reference_model/tb/vectors/dvsgesture/r1_seed<k>.npz` for the R=1 model). The regression compares, for every timestep that ran, the spikes, X, V, the N prefix scores, the leader, the second-largest score, the exit decision, and per sample the prediction, the exit timestep and the events actually ingested.

**Tools.** OpenSTA (for timing and power) is not in Homebrew; it was built from source (cmake, Tcl 8.6, CUDD) and its binary placed at `design/rtl/tools/sta` (git-ignored). The standard-cell library is the FFT project's Cadence 45 nm `fast_vdd1v0_basicCells.lib`, read from the sibling project directory (`--lib-dir`); no PDK file is copied into this repository. Verible is not installed on this machine; the Phase 2-4 files are linted with `verilator --lint-only -Wall` only (`scripts/lint_hdc.sh` runs Verible too wherever it is installed).
