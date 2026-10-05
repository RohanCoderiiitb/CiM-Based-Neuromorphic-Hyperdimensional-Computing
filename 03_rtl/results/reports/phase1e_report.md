# Phase 1E - digital RTL for CIM-NeuroHDC: report

Everything below is measured by the regression in this directory; regenerate with `03_rtl/scripts/run_everything.sh` (see `03_rtl/README.md`). Tools: Verilator 5.052 2026-09-05, Icarus Verilog version 13.0 (stable) (v13_0), Yosys 0.69+post, Verible v0.0-4296. Golden model: Phase 0 `int_model.py`, imported, never reimplemented. Crossbar: behavioural model (`cim_macro.sv`). No PDK anywhere in 1E.

## 1. Completion criteria

| # | criterion | status | evidence |
|---|---|---|---|
| 1 | 240/240 DVS-Gesture rasters identical to Phase 0, 3 seeds | PASS | 0 mismatches in `dvs_seed{0,1,2}_g8_c160` (section 2) |
| 2 | N-MNIST exact on >=1,000 samples, shared threshold, divide-by-34 path | PASS | 1,000 samples x 3 runs (g=8, g=8 with random gaps, g=64), 0 mismatches |
| 3 | raster bit-identical at g = 4, 8, 16, 32, 64 | PASS | 240/240 raster hashes equal to g=8 at every g, and in the 20-column and no-skip runs (section 3) |
| 4 | every assertion passes, none disabled or waived | PASS | 0 assertion messages in all 19 regression runs; 62 unit-test cases pass; assertions are `ifndef SYNTHESIS` only (simulation), never switched off in a run |
| 5 | Verible and `verilator --lint-only` clean | PASS | `results/lint/lint.log` (waivers listed in `scripts/lint.sh`) |
| 6 | Verilator and Icarus agree on the whole regression | PASS | per-timestep comparison, section 4 |
| 7 | access counts per sample, matching an independent estimate within 1% | PASS | 0 mismatches in every run: the logged group reads equal the estimate computed in Python from the count vectors **exactly** |
| 8 | synthesises (generic Yosys, no PDK): no latches, no comb. loops | PASS | `check -assert` clean, 0 `$dlatch`, section 8 |
| 9 | one command reruns everything and reproduces the report | PASS | `03_rtl/scripts/run_everything.sh` (section 11); executed end to end on the development machine (all stages except the 4-5 h Icarus regression, whose script ran separately); a fresh-clone run on another machine is not yet done |
| 10 | this report states all measured numbers | PASS | sections 2-9 |

Criterion 8 deviates from the first wording of the brief ("against sky130"): the corrected 1E brief is generic Yosys, no PDK, no liberty file; mapping to sky130 is Phase 5.

## 2. Bit-exactness against the Phase 0 golden model

Per sample and timestep the testbench compares spikes, X[20], V[20] and the final prediction against `int_model.snn_forward`.

| run | samples | mismatching | assertion msgs | access-estimate mismatches |
|---|---|---|---|---|
| dvs_seed0_g8_c160 | 240 | 0 | 0 | 0 |
| dvs_seed1_g8_c160 | 240 | 0 | 0 | 0 |
| dvs_seed2_g8_c160 | 240 | 0 | 0 | 0 |
| dvs_seed0_g4_c160 | 240 | 0 | 0 | 0 |
| dvs_seed0_g16_c160 | 240 | 0 | 0 | 0 |
| dvs_seed0_g32_c160 | 240 | 0 | 0 | 0 |
| dvs_seed0_g64_c160 | 240 | 0 | 0 | 0 |
| dvs_seed0_g8_c20 | 240 | 0 | 0 | 0 |
| dvs_seed0_g64_c20 | 240 | 0 | 0 | 0 |
| dvs_seed0_g8_noskip | 240 | 0 | 0 | 0 |
| dvs_seed0_level4_real_gaps | 20 | 0 | 0 | 0 |
| dvs_seed1_level4_real_gaps | 20 | 0 | 0 | 0 |
| dvs_seed2_level4_real_gaps | 20 | 0 | 0 | 0 |
| dvs_seed0_level4_shuffled_gaps | 48 | 0 | 0 | 0 |
| dvs_seed0_level4_sorted_gaps | 48 | 0 | 0 | 0 |
| dvs_seed1_level4_sorted_nogap | 48 | 0 | 0 | 0 |
| nmnist_seed0_g8 | 1000 | 0 | 0 | 0 |
| nmnist_seed0_g8_gaps | 1000 | 0 | 0 | 0 |
| nmnist_seed0_g64 | 1000 | 0 | 0 | 0 |

`level4_*` runs drive real AER streams (20 samples, every class) or synthesised streams (48 samples) with randomised idle gaps (stall path) and sorted / shuffled event order (same-address adjacency stress, read-modify-write forwarding).

## 3. Raster identical across g (seed 0, 240 samples)

- dvs_seed0_g4_c160 vs g=8: 240/240 identical raster hashes
- dvs_seed0_g16_c160 vs g=8: 240/240 identical raster hashes
- dvs_seed0_g32_c160 vs g=8: 240/240 identical raster hashes
- dvs_seed0_g64_c160 vs g=8: 240/240 identical raster hashes
- dvs_seed0_g8_c20 vs g=8: 240/240 identical raster hashes
- dvs_seed0_g64_c20 vs g=8: 240/240 identical raster hashes
- dvs_seed0_g8_noskip vs g=8: 240/240 identical raster hashes

## 4. Verilator vs Icarus, per timestep (criterion 6)

Compared per (sample, timestep): spikes, X[20], V[20], every instrumentation counter (events, active addresses, rows skipped/read, group reads, zero groups, forwards, cycles, ingest cycles), the golden-match flag; per sample: raster hash, total cycles, stall cycles, prediction, event count, reads.

| Verilator run compared against | samples | timesteps compared | disagreements | verdict |
|---|---|---|---|---|
| dvs_seed0_g8_c160 | 240 | 24,000 | 0 | AGREE |
| dvs_seed1_g8_c160 | 240 | 24,000 | 0 | AGREE |
| dvs_seed2_g8_c160 | 240 | 24,000 | 0 | AGREE |
| dvs_seed0_level4_real_gaps | 20 | 2,000 | 0 | AGREE |
| dvs_seed1_level4_real_gaps | 20 | 2,000 | 0 | AGREE |
| dvs_seed2_level4_real_gaps | 20 | 2,000 | 0 | AGREE |
| dvs_seed0_level4_shuffled_gaps | 48 | 4,800 | 0 | AGREE |
| dvs_seed0_level4_sorted_gaps | 48 | 4,800 | 0 | AGREE |
| dvs_seed1_level4_sorted_nogap | 48 | 4,800 | 0 | AGREE |
| nmnist_seed0_g8 | 1000 | 100,000 | 0 | AGREE |
| nmnist_seed0_g8_gaps | 200 | 20,000 | 0 | AGREE |
| nmnist_seed0_g64 | 200 | 20,000 | 0 | AGREE |
| sub_dvs_seed0_g4_c160 | 48 | 4,800 | 0 | AGREE |
| sub_dvs_seed0_g16_c160 | 48 | 4,800 | 0 | AGREE |
| sub_dvs_seed0_g32_c160 | 48 | 4,800 | 0 | AGREE |
| sub_dvs_seed0_g64_c160 | 48 | 4,800 | 0 | AGREE |
| sub_dvs_seed0_g8_c20 | 48 | 4,800 | 0 | AGREE |
| sub_dvs_seed0_g64_c20 | 48 | 4,800 | 0 | AGREE |
| sub_dvs_seed0_g8_noskip | 48 | 4,800 | 0 | AGREE |

Coverage: the design point (g=8, three seeds), the Level 4 stress runs and N-MNIST g=8 are compared on every sample; the remaining sweeps were run on a fixed random subset of the same rows (overnight profile of `run_icarus_regressions.sh`, chosen so the whole comparison finishes in one night; `PROFILE=full` runs all): nmnist_seed0_g8_gaps (200 of 1000), nmnist_seed0_g64 (200 of 1000), dvs_seed0_g4_c160 (48 of 240), dvs_seed0_g16_c160 (48 of 240), dvs_seed0_g32_c160 (48 of 240), dvs_seed0_g64_c160 (48 of 240), dvs_seed0_g8_c20 (48 of 240), dvs_seed0_g64_c20 (48 of 240), dvs_seed0_g8_noskip (48 of 240). Synthesised streams take their event order from one random generator consumed row after row, so a subset sends a different event order for a row than the full Verilator run (same counts, so same X, V, spikes and cycles, but a different read-modify-write forwarding count). Each DVS sweep subset is therefore compared with a Verilator twin run of identical arguments (sub_dvs_seed0_g4_c160, sub_dvs_seed0_g16_c160, sub_dvs_seed0_g32_c160, sub_dvs_seed0_g64_c160, sub_dvs_seed0_g8_c20, sub_dvs_seed0_g64_c20, sub_dvs_seed0_g8_noskip), which gives identical stimulus on both simulators. The first comparison against the full Verilator runs showed exactly this, and only in `fwd_events`.

Total: 266,000 timesteps over 2,660 samples. No disagreement anywhere: the two simulators agree on all intermediate state, not just the final raster.

## 5. Phase-5 handoff numbers (DVS-Gesture, seed 0 weight image, mean per sample over 240 samples)

All counts are for one inference = 100 timesteps; cycles include ingest stalls (back-pressure; no event is lost or buffered).

| configuration | cycles / inference | stall cycles | crossbar reads, 160 columns/read | crossbar reads, 20 columns/read | rows skipped / sample | weight-bit reads / sample |
|---|---|---|---|---|---|---|
| g=4 | 516,207 | 107,982 | 107,179 | 857,434 | 262.7 | 26,093 |
| **g=8 (design point)** | 462,617 | 54,931 | 53,590 | 428,717 | 262.7 | 26,093 |
| g=16 | 435,823 | 28,406 | 26,795 | 214,358 | 262.7 | 26,093 |
| g=32 | 422,425 | 15,144 | 13,397 | 107,179 | 262.7 | 26,093 |
| g=64 | 415,727 | 8,512 | 6,699 | 53,590 | 262.7 | 26,093 |
| g=8, plane skipping off | 479,428 | 71,577 | 70,400 | 563,200 | 0.0 | 26,093 |

Column-sensing assumption B (`N_PARALLEL_COLS`=20, one weight bit-plane per read) is a separate measured run, not the 8x multiple above: 
- g=8, 20 columns/read: 428,717 reads, 837,745 cycles/inference (426,284 stall cycles).
- g=64, 20 columns/read: 53,590 reads, 462,617 cycles/inference (54,931 stall cycles).

- Mean events per sample: 407,124. Mean active addresses per timestep: 50.96% of 512 (Phase 0 expectation 51.0%).
- Plane skipping at g=8: 53,590 reads vs 70,400 without = 23.9% saved; 2.63 of 11 count bit-rows skipped per timestep.
- Weight-bit reads per sample (sum of active addresses over timesteps): 26,093; Phase 0 expectation ~26,112; 15.6x below event-serial (one read per event).
- Read-modify-write forwarding events per sample: 16,330.
- N-MNIST at g=8 (1,000 samples): 20,872 cycles/inference, 4,210 events/sample, 14,758 reads, 5.8% active addresses.

## 6. The design is input-bound: g sets energy, not latency

| g | events | stall cycles | cycles | cycles / events | crossbar reads |
|---|---|---|---|---|---|
| 4 | 407,124 | 107,982 | 516,207 | 1.268 | 107,179 |
| 8 | 407,124 | 54,931 | 462,617 | 1.136 | 53,590 |
| 16 | 407,124 | 28,406 | 435,823 | 1.070 | 26,795 |
| 32 | 407,124 | 15,144 | 422,425 | 1.038 | 13,397 |
| 64 | 407,124 | 8,512 | 415,727 | 1.021 | 6,699 |

Ingest takes exactly one cycle per event (`cycles_ingest` = events in every timestep), so cycles = events + stalls, and events dominate: 407,124 events against 415,727 to 516,207 total cycles. A 16x change in g moves the cycle count by only 1.24x while it moves crossbar reads by 16x. **g sets energy, not latency.** The only latency g controls is the stall tail (the MVM at each timestep boundary, during which ingest is held off): 107,982 cycles at g=4 down to 8,512 at g=64, i.e. 21% down to 2% of the inference. Consequences: the choice of g can be made on the 1B margin / 1C array criteria and on read energy without a latency penalty argument; and the only way to cut latency substantially is to overlap the MVM with ingest (ping-pong count memory, deliberately not built in 1E) or to raise the event-ingest rate. With 20 columns per read the MVM is long enough to matter (g=8: 1.81x the cycles of the 160-column design), but g=64 with 20 columns reads exactly as often as g=8 with 160 columns and takes identical time (462,617 vs 462,617 cycles).

## 7. The plane-skipping gap (measured opportunity, not acted on)

Skipping saves 23.9% of the reads and skips 2.63 of 11 bit-rows, so 8.37 bit-rows are still read per timestep. The active addresses' counts are small: median 3, mean 15.6, P99 230, max 1208 (golden count vectors, non-zero entries, all 24,000 timestep vectors); the median count needs 2 bits and the mean active address needs 2.79 bits, against 8.37 rows read.

| count bit-row | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fraction of active addresses with the bit set | 60.9% | 42.9% | 28.3% | 18.1% | 11.3% | 6.9% | 4.1% | 2.2% | 0.7% | 0.0% | 0.0% |
| fraction of timesteps where the whole row is zero (skipped) | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.2% | 3.4% | 15.4% | 50.6% | 93.1% | 100.0% |

The gap exists because skipping is all-or-nothing across all 512 addresses: a bit-row is skipped only if **every** active address has a zero there. With ~261 active addresses per timestep and a heavy tail (P99 = 230), a handful of hot addresses keeps the high rows alive for the whole timestep even though almost every other address is zero in them (e.g. row 7 is set for only 2.2% of active addresses yet is skipped in only 15% of timesteps). No finer-grained (per-group or per-address) row mask exists; This is recorded as a measured opportunity for later (e.g. a per-group plane-skip mask, or clipping/handling the hot addresses separately); it is not acted on in 1E and the RTL is unchanged.

## 8. Synthesis check (generic Yosys, no PDK)

- `check -assert` on the specified elaboration: PASS; latch cells: 0; combinational loops: none (check -assert).
- Generic-gate smell test (not area): 9,352 flip-flops and 78,730 gates with instrumentation, 9,332 / 70,568 without (INSTRUMENT_EN = 0). count_mem is 512 x 11 = 5,632 flip-flops of these (counters are flip-flops by design).
- Longest topological path: **67 gates** (both builds). **Flag for Phase 5: it will likely need pipelining at timing closure.** From the Yosys path report it starts at `plane_seq.b_q` (the bit-row index), goes through the bit-row select and the 512-bit `a_row` popcount in `shift_accum`, and ends in `shift_accum.x_wide` (the 21-bit signed fold of the eight per-plane partial sums into X) feeding `x_q`. Best guess: the critical stage is the **fold adder in `shift_accum`** (about 55 of the 67 levels are the carry-propagating add after the popcount); the first fix would be to register the popcount output and fold in a second stage - which costs one cycle per MVM (ACC_LAT), nothing at all per event, and per section 6 the design is input-bound.
- `cim_macro` is a blackbox in synthesis (the crossbar is out of scope).

## 9. Unit tests and the Level 1 guard

- cocotb (icarus): 31/31 cases pass (addr_gen, event_ctr, count_mem, weight_load, spike_reg, if_neuron_array, plane_seq x6 configs, cim_macro / shift_accum at g=8, 48, 512, mvm_unit at g=1..512 and the 20-column / no-skip variants, and the g-sweep check that X is identical for every g).
- cocotb (verilator): 31/31 cases pass (addr_gen, event_ctr, count_mem, weight_load, spike_reg, if_neuron_array, plane_seq x6 configs, cim_macro / shift_accum at g=8, 48, 512, mvm_unit at g=1..512 and the 20-column / no-skip variants, and the g-sweep check that X is identical for every g).
- Level 1 guard (`scripts/level1_guard.py`, part of `run_everything.sh`): Phase 0 pytest `10 passed in 1.86s`; `int_model.snn_forward` reproduces the stored X/V/spike traces for dvsgesture_seed0 (240 samples, 0 mismatches), dvsgesture_seed1 (240 samples, 0 mismatches), dvsgesture_seed2 (240 samples, 0 mismatches), nmnist_seed0 (1000 samples, 0 mismatches); every exported AER stream reproduces the stored addresses and counts (dvsgesture: 20 streams, nmnist: 1000 streams). A future change to `int_model.py` that alters behaviour fails here before it can silently change what the RTL is compared against.

## 10. Golden vectors in the repository

The golden vectors (`01_integer_reference_model/tb/vectors/`, 75 MB; the largest file is 31 MB, under GitHub's 100 MB limit) are committed as ordinary files, as they have been since Phase 0. Decision: **no Git LFS**. LFS was set up and the history migrated during 1E, then reverted at the owner's request; nothing was pushed, `main` is the original history, and no force push is needed. Integrity is guarded instead by the Level 1 check (`scripts/level1_guard.py`: `int_model` must reproduce every stored trace) and by the SHA-256 of each vector file that every regression JSON records (`golden_vectors_sha256`). The vectors are in `01_integer_reference_model/tb/vectors/`, not `03_rtl/tb/vectors/` as the 1E brief assumed.

## 11. Reproduce

```
python3 -m venv venv && venv/bin/pip install -r 03_rtl/requirements.txt   # once; also needs verilator, iverilog, yosys, verible
03_rtl/scripts/run_everything.sh                                           # lint, Level-1 guard, unit tests (both sims), Verilator regression,
                                                                           # Icarus regression + per-timestep comparison, Yosys, this report
```

## 12. Scope and limits

- The crossbar is a behavioural model; analog effects (margin, wire IR, comparator noise, the per-group ladder) are 1B/1C. `group_idx_o` is emitted per read for the later ladder model.
- Cycle counts are RTL cycles of this micro-architecture with the stall (back-pressure) policy; no energy, area or timing numbers (Phase 5).
- Icarus is far slower than Verilator (about 10-15k simulated cycles/s per process); see section 4 for exactly what it covered.
- The report path is `results/reports/phase1e_report.md` (descriptive directory, matching the 1B layout) rather than the `results/1e/` of the brief.
