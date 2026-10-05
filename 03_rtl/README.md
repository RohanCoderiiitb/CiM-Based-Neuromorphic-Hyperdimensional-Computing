# 03_rtl - Phase 1E: digital RTL for CIM-NeuroHDC

Everything digital except the crossbar: event front end, count memory, plane sequencer, shift-accumulate, IF neuron array, controller. The crossbar is a
**behavioural** model (`cim_macro.sv`); no analog, no PDK. The RTL is bit-exact against the Phase 0 integer model
(`01_integer_reference_model/model/fixedpoint/int_model.py`, imported by the testbenches, never reimplemented).

Full results and every measured number: [`results/reports/phase1e_report.md`](results/reports/phase1e_report.md).

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
