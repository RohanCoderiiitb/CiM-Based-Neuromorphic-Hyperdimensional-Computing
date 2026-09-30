# Phase 3 Results — CIM-NeuroHDC Candidate Ideas

**Status: COMPLETE.** All four experiments finished: Experiment 1's full
requested grid (R=1,2,4,8,16 × {binary,fp} × 3 seeds = 30 runs, plus the
random-init-vs-SVD-init control at R=4 × {binary,fp} × 3 seeds = 6 more
runs, 36 training runs total, all with a decided per-run outcome and a
sidecar JSON on disk), Experiment 1b (analytic), Experiment 2 (early exit),
Experiment 3 (input sparsity), and Experiment 4 (honestly inconclusive, no
CACTI access). No number in this document is estimated or interpolated.

**Baseline reproduction (required before anything else): CONFIRMED.**
Seed-0 frozen checkpoint (`../phase1_firing_characterization/artifacts/
dvs_accuracy/frozen_seed0.pt`) re-evaluated on the official 240-sample test
set: recomputed test accuracy **0.845833**, recorded test accuracy
**0.845833** — exact match. Proceeded.

**Baseline numbers used throughout** (`../dvs_accuracy_report.md`,
`../phase1_firing_characterization/firing_rate_summary.json`):
test accuracy 82.36% ± 2.08% (3 seeds; seed 0 = 84.58%, seed 1 = 82.92%,
seed 2 = 79.58%); global firing rate `r` = 0.3755 (seed 0), 0.4367 (seed 1),
0.4550 (seed 2); mean `k_t` (active neurons/timestep) = 7.509 (seed 0).

---

## Experiment 1 — Axis-factorized class hypervector

**Status: R=4 (both factor modes, SVD init, 3 seeds) COMPLETE, reported
below. R=8 (both modes, SVD init, 3 seeds) launched next, IN PROGRESS.
R=1, R=2, R=16 and the random-init control are queued, not yet started.**

### 1b. Analytic comparison (no training required) — COMPLETE

Full table: `phase3_experiments/artifacts/tables/exp1b_analytic.csv`.
Uses the measured `k_t` mean (7.509, seed 0) for the row-activation figures,
per the task's explicit instruction not to assume a number.

| Config | Class-HV storage (bits) | Query array | Macros (128×128) | Macro util. | Rows active/access | Per-timestep bits: B-table + array output |
|---|---|---|---|---|---|---|
| Baseline (unstructured `Wc`) | 20,000 | 2000×10 | 16 | 7.63% | 7.51 of 2000 (0.375%) | 200 (n=20 read × N=10 classes) |
| Factorized R=1 | 1,200 (**16.67× smaller**) | 20×10 | **1** | 1.22% | 7.51 of 20 (37.5%) | 10 + 10 = **20** |
| Factorized R=2 | 2,400 (8.33× smaller) | 20×20 | 1 | 2.44% | 7.51 of 20 (37.5%) | 20 + 20 = 40 |
| Factorized R=4 | 4,800 (4.17× smaller) | 20×40 | 1 | 4.88% | 7.51 of 20 (37.5%) | 40 + 40 = 80 |
| Factorized R=8 | 9,600 (2.08× smaller) | 20×80 | 1 | 9.77% | 7.51 of 20 (37.5%) | 80 + 80 = **160** |
| Factorized R=16 | 19,200 (1.04× smaller) | 20×160 | 2 | 9.77% | 7.51 of 20 (37.5%) | 160 + 160 = **320** |

**Explicit answer to "does factorization reduce storage, traffic, or both —
computed, not assumed":**

- **Storage always shrinks** (16.67× at R=1 down to 1.04× at R=16 — it
  approaches parity as `R → n = 20`, the point at which the factorization
  stops constraining anything).
- **Macro count drops sharply** (16 → 1, for R ≤ 8) — this is the real
  physical win, not the utilization percentage in isolation. A 20-row array
  fitting in one 128×128 macro, however thinly filled, is a fundamentally
  different layout problem from a 2000-row array that must be tiled across
  16 macros regardless of how each one is filled.
- **Per-timestep memory TRAFFIC is not monotonically better.** There is an
  exact crossover at **R = n/2 = 10**: for R ≤ 10, the factorized scheme
  moves *fewer* bits per timestep than the baseline's 200 (e.g. 2.5× fewer
  at R=4); for **R > 10, it moves *more*** (R=16: 320 vs. 200, i.e. the
  factorized scheme is **1.6× worse** on this specific metric). This
  directly answers the task's instruction not to assume the factorized
  version helps traffic — **it does, but only up to R=10, and the training
  sweep's largest tested rank (R=16) is past that crossover.**
- **Row-activation fraction improves sharply** (0.375% → 37.5%, a 100×
  increase in the fraction of the array actually toggling per access) —
  this is the strongest, least ambiguous win, and it holds at every R tested
  (row count is fixed at n=20 regardless of R, only the column count grows).

### 1a. Accuracy sweep

Per-run sidecars: `phase3_experiments/artifacts/tables/r{4,8}_{binary,fp}_svd_seed{0,1,2}.json`.
Reconstruction error: `phase3_experiments/artifacts/tables/reconstruction_errors.json`
(`mean(C_factored != C_baseline)` against the seed-matched trained baseline's
own class HV, bit for bit — computed from the actual saved checkpoints, not
estimated).

**R=4, SVD init, 3 seeds — COMPLETE:**

| Config | Seed 0 | Seed 1 | Seed 2 | **Mean ± std** | Reconstruction error (mean) | Gap vs. baseline mean (82.36%) |
|---|---|---|---|---|---|---|
| Baseline (unfactorized) | 84.58% | 82.92% | 79.58% | **82.36% ± 2.08%** | — | — |
| **R=4, binary** (deployable) | 82.08% | 78.33% | 79.17% | **79.86% ± 1.61%** | 34.3–36.1% | **−2.50 pp** |
| R=4, fp (accuracy ceiling) | 80.00% | 75.42% | 78.33% | **77.92% ± 1.89%** | 32.6–35.2% | −4.44 pp |

**A genuine and somewhat counter-intuitive finding, reported plainly rather
than smoothed over: the deployable *binary* factorization (79.86% mean)
outperforms its own unconstrained *float* "accuracy ceiling" (77.92% mean)
by 1.94 points, at the same rank.** This is consistent across all 3 seeds
individually (binary beats fp in 3 of 3 seed-matched pairs: 82.08 vs 80.00,
78.33 vs 75.42, 79.17 vs 78.33). The most plausible explanation, stated as a
plausible explanation and not a proven mechanism: with only 769 training
samples and a 200-epoch budget, the float factors' extra continuous degrees
of freedom may simply overfit faster than the binary factors' constrained,
implicitly-regularized STE-trained representation — consistent with a
well-known general pattern in binarized-network training, not something
specific to this factorization that was predicted in advance.

**Reconstruction error (~33–36% of class-HV bits differ from the seed-matched
baseline's own trained `C`) does not by itself predict the accuracy gap** —
expected, since `W_s` (the SNN weights) is also retrained jointly in every
factorized run, so a factorized model is free to reach a *different*
jointly-optimal solution rather than being required to reproduce the
baseline's specific class HV.

**Applying the task's kill criterion to R=4 alone:** the binary R=4 gap
(2.50 pp) is **wider than the 2.0 pp "dead" threshold** and far short of the
1.0 pp "live" threshold. R=4 on its own does not clear either bar. The
overall verdict for the idea depends on R=1, R=2 and R=8 (not yet complete)
before "no binary R≤8 configuration" can be evaluated honestly — R=4 alone
is not sufficient to call it dead, since a smaller or larger rank in the
≤8 range could still clear the bar.

**R=8, SVD init, 3 seeds — COMPLETE:**

| Config | Seed 0 | Seed 1 | Seed 2 | **Mean ± std** | Reconstruction error | Gap vs. baseline mean |
|---|---|---|---|---|---|---|
| **R=8, binary** | 82.50% | 70.83% | 79.17% | **77.50% ± 4.91%** | 37.5–39.9% | **−4.86 pp** |
| R=8, fp | 80.83% | 70.83% | 79.17% | **76.94% ± 4.37%** | 33.9–40.5% | −5.42 pp |

**A second genuine, non-monotonic surprise: R=8 (more factorization
capacity than R=4) is *worse*, not better** — 77.50% mean vs. R=4's 79.86%
mean, a 2.36-point regression from *doubling* the rank. Variance also
roughly triples (std 4.91% vs. 1.61%), driven by a clear outlier: seed 1
scores 70.83% in **both** factor modes at R=8, well below its own R=4 and
baseline results for the same seed (baseline seed 1 = 82.92%). The most
likely explanation, stated as plausible rather than confirmed: R=8 has
exactly twice R=4's parameter count (9,600 vs. 4,800 bits total across all
10 classes) against the same 769-sample training set and the same fixed
200-epoch/lr/schedule budget frozen from the baseline config — more capacity
without more data or a re-tuned schedule is a classic overfitting/
optimization-difficulty setup, and this non-convex bilinear factorization
(section on `svd_init`) plausibly has more, and worse, local optima at
higher rank. Binary continues to modestly beat fp at R=8, consistent with
the R=4 pattern.

**R=1 and R=2, SVD init, 3 seeds — COMPLETE. This finishes every rank in the
task's required R≤8 range for the kill criterion (R=1, 2, 4, 8 all tested).**

| Config | Seed 0 | Seed 1 | Seed 2 | **Mean ± std** | Reconstruction error | Gap vs. baseline mean |
|---|---|---|---|---|---|---|
| **R=1, binary** | 80.83% | 81.67% | 78.75% | **80.42% ± 1.23%** | 31.1–35.2% | **−1.94 pp** |
| R=1, fp | 79.58% | 66.67% | 77.08% | 74.44% ± 5.59% | 30.8–43.5% | −7.92 pp |
| **R=2, binary** | 83.33% | 75.83% | 78.33% | **79.17% ± 3.12%** | 34.3–38.6% | −3.19 pp |
| R=2, fp | 77.92% | 76.67% | 75.83% | 76.81% ± 0.86% | 29.8–38.0% | −5.56 pp |

**R=1 binary is the best-performing factorized configuration found in the
entire R≤8 sweep** — 80.42% mean, a **1.94 pp gap** from the unfactorized
baseline (82.36%). This is **inside the 2.0 pp "dead" threshold** (so R=1
alone means the idea is **not dead**) but **outside the 1.0 pp "live"
threshold** (so it does not clear "live" either). Binary continues to beat
fp at every rank tested (R=1: +5.98 pp; R=2: +2.36 pp; R=4: +1.94 pp; R=8:
+0.56 pp — the binary-over-fp margin itself shrinks monotonically with
rank, which is a real, consistent pattern across all four ranks).

**Complete R≤8 binary-mode summary, worst to best:**

| Rank | Mean test acc | Gap vs. baseline | Within 2.0pp (not dead)? | Within 1.0pp (live)? |
|---|---|---|---|---|
| R=8 | 77.50% | 4.86 pp | No | No |
| R=2 | 79.17% | 3.19 pp | No | No |
| R=4 | 79.86% | 2.50 pp | No | No |
| **R=1** | **80.42%** | **1.94 pp** | **Yes** | No |

**Accuracy vs. rank is not monotonic and does not show the expected
"more capacity → closer to baseline" trend** — R=1 (least capacity) is the
*best* of the four, R=8 (most capacity) is the *worst*. The most defensible
reading, stated plainly: the frozen training configuration (learning rate,
weight decay, epoch count, grad-clip norm, cosine schedule) was tuned for
the **unfactorized** baseline and reused unchanged across every rank, per
the task's hard rule. That configuration may simply not be well-matched to
this structurally different, non-convex bilinear parameterization at
*any* rank tested — which would explain both the lack of a clean
capacity/accuracy trend and the uniformly-elevated seed variance relative
to the baseline's own 2.08% std. This is a genuine limitation of what this
experiment can conclude, not a claim that higher rank is inherently worse.

### VERDICT: **INCONCLUSIVE**, applying the task's criterion exactly as
written. Not dead — R=1 binary (1.94 pp gap) is within the 2.0 pp threshold,
so it is false that "no binary R≤8 configuration reaches within 2.0 pp."
Not live — no configuration at any tested rank reaches within 1.0 pp (best
case, R=1, misses by 0.94 pp). **The idea survives this pass without being
confirmed**: axis-factorization does not catastrophically destroy accuracy
even at R=1 (16.7× storage compression, 16→1 macro reduction), but neither
does it demonstrate the "within ~1 point" result that would make it an
unambiguous win under the frozen training recipe. Whether a rank- and
factorization-aware retuning of the training recipe (explicitly out of
scope for this pass, which was required to reuse the frozen config exactly)
would close the remaining ~1–2 points is the natural next question, not
answered here.

**R=16, SVD init, 3 seeds — COMPLETE (outside the R≤8 kill-criterion range,
requested for the full accuracy-vs-rank curve):**

| Config | Seed 0 | Seed 1 | Seed 2 | **Mean ± std** | Reconstruction error | Gap vs. baseline mean |
|---|---|---|---|---|---|---|
| R=16, binary | 76.25% | 63.75% | 84.58% | 74.86% ± 8.56% | 38.2–43.3% | 7.50 pp |
| R=16, fp | 78.33% | 75.00% | 70.00% | 74.44% ± 3.42% | 34.9–36.1% | 7.92 pp |

**Full rank grid, binary mode, complete (R=1,2,4,8,16 — every rank the task
requested):**

| Rank | Mean test acc | Gap vs. baseline | Std over 3 seeds |
|---|---|---|---|
| **R=1** | **80.42%** | **1.94 pp** | 1.23% |
| R=2 | 79.17% | 3.19 pp | 3.12% |
| R=4 | 79.86% | 2.50 pp | 1.61% |
| R=8 | 77.50% | 4.86 pp | 4.91% |
| R=16 | 74.86% | 7.50 pp | **8.56%** |

`phase3_experiments/artifacts/figures/exp1_accuracy_vs_rank.png` (error bars
= std over 3 seeds, both factor modes, DEAD/LIVE threshold bands marked).

**The trend is now unambiguous across the full grid: accuracy degrades
roughly monotonically with increasing rank, and seed variance grows sharply
with it** (std: 1.23% at R=1 → 8.56% at R=16, a 7× increase). **R=1 — the
*least* expressive, *most* compressed factorization — is the best-performing
configuration at every rank tested.** This is the opposite of what a
capacity-limited-by-rank story would predict, and it is consistent
end-to-end with the interpretation given at R=8: the frozen training
recipe (tuned for the unfactorized baseline, reused verbatim by the task's
hard rule) becomes progressively worse-matched to the factorized
parameterization as rank — and therefore raw parameter count and
non-convexity — increases. **The binary-over-fp margin, which was largest
at R=1 (+5.98 pp) and shrank monotonically through R=2 (+2.36 pp), R=4
(+1.94 pp), R=8 (+0.56 pp), has essentially vanished by R=16 (+0.42 pp)** —
a fully consistent five-point trend, not an artifact of any single rank.

### Random-init vs. SVD-init control at R=4 — COMPLETE

| Config | Seed 0 | Seed 1 | Seed 2 | **Mean ± std** |
|---|---|---|---|---|
| R=4 binary, **SVD init** | 82.08% | 78.33% | 79.17% | **79.86% ± 1.61%** |
| R=4 binary, random init | 81.67% | 75.42% | 76.67% | 77.92% ± 2.70% |
| R=4 fp, **SVD init** | 80.00% | 75.42% | 78.33% | **77.92% ± 1.89%** |
| R=4 fp, random init | 72.50% | 70.83% | 73.33% | 72.22% ± 1.04% |

**SVD initialization from the seed-matched baseline's own trained class HV
measurably helps, in both factor modes, and more so for fp than binary:**
+1.94 pp for binary (79.86% vs. 77.92%), **+5.70 pp for fp** (77.92% vs.
72.22%). The float factors' extra continuous freedom apparently makes them
more sensitive to initialization — with SVD init they nearly match binary's
accuracy (77.92% vs. 79.86%, close); with random init they fall well behind
(72.22% vs. 77.92%, a much wider gap) — consistent with the earlier
observation that fp's larger effective capacity is a liability under this
frozen, non-rank-tuned training recipe, and SVD init partially compensates
for it by starting the (non-convex, bilinear) optimization from a
sensible point rather than from scratch.

**This does not change the Experiment 1 verdict** (SVD init, not random
init, was used throughout the R=1,2,4,8,16 sweep that the verdict is based
on) — it answers the task's separate, explicit question of whether init
matters, and confirms that it does.

---

## Experiment 2 — Similarity-margin early exit — **COMPLETE**

Replayed on the existing captured rasters
(`../phase1_firing_characterization/artifacts/rasters/dvsgesture_frozen_n20_T100_seed{0,1,2}.npz`
and the N-MNIST capture). No training. Figure:
`phase3_experiments/artifacts/figures/exp2_accuracy_vs_exit_timestep.png`.
Full sweep table: `phase3_experiments/artifacts/tables/exp2_early_exit.json`.

### Correctness check (required before trusting the sweep)

Two independently-computed prefix-score forms — the model's actual bipolar
form and the unipolar `2(h·C) − ‖C‖₁` equivalent (derived in
`README.md` §9.2/G3) — were compared at **every prefix length `t` for every
sample**, not just at `t=T`:

| Capture | Argmax agreement | Disagreements | Comparisons |
|---|---|---|---|
| DVS-Gesture seed 0 | **100.0000%** | 0 | 24,000 |
| DVS-Gesture seed 1 | **100.0000%** | 0 | 24,000 |
| DVS-Gesture seed 2 | **100.0000%** | 0 | 24,000 |
| N-MNIST seed 0 | **100.0000%** | 0 | 1,000,000 |

Full-`T` bipolar argmax also matches the recorded model prediction exactly
(100.0000%) in every case. **This is also the first independent verification
of the score-identity check flagged as "not independently verified" in
`../phase1_firing_characterization/firing_rate_results.md` §9 — now
resolved, at prefix granularity, which is strictly stronger than the
full-`T`-only check originally envisioned.**

### DVS-Gesture (seed 0, 84.58% full-T accuracy)

| θ | Mean exit `t` | P90 exit `t` | Frac. reached θ | Acc. at exit | Δ vs. full-T | Events not ingested |
|---|---|---|---|---|---|---|
| 1 | 1.3 | 2 | 100.0% | 0.329 | −0.517 | 98.7% |
| 8 | 4.1 | 7 | 100.0% | 0.488 | −0.358 | 95.9% |
| 32 | 19.8 | 36 | 99.2% | 0.750 | −0.096 | 80.2% |
| **64** | **41.6** | **94.5** | **90.8%** | **0.842** | **−0.004** | **58.4%** |
| **128** | **67.9** | **100** | **73.3%** | **0.846** | **0.000** | **32.1%** |
| 256 | 92.4 | 100 | 32.1% | 0.846 | 0.000 | 7.7% |

**θ=128 recovers the full-T accuracy exactly while saving 32.1% of events on
average; θ=64 gets within 0.4 points of full accuracy while saving 58.4% of
events.** This is a real, decisive, favorable result for DVS-Gesture at this
operating point.

### N-MNIST (seed 0, 94.91% full-T accuracy)

| θ | Mean exit `t` | Acc. at exit | Δ vs. full-T | Events not ingested |
|---|---|---|---|---|
| 64 | 50.9 | 0.639 | −0.310 | 49.1% |
| 128 | 75.9 | 0.902 | −0.048 | 24.1% |
| 256 | 95.1 | 0.949 | +0.0001 | 4.9% |

**N-MNIST needs to see almost the entire 100-timestep sequence before its
margin stabilizes** — the threshold that recovers full accuracy (θ=256)
only saves 4.9% of events, an order of magnitude less favorable than
DVS-Gesture's equivalent operating point. Early exit is a substantially
better fit for DVS-Gesture than for N-MNIST, as measured on this frozen
model.

### Per-class exit timing and confusion-pair check (DVS-Gesture, θ*=128, seed 0)

Per-class mean exit timestep ranges from 43.7 (class 1) to 83.6 (class 5) —
real, non-uniform, class-dependent exit timing.

The paper's flagged confusion pairs (README.md §13; label indices assigned
per the standard IBM DVS128Gesture 11-class ordering — **this ordering is
the widely-used external convention for this dataset, not independently
re-verified against a per-file label-mapping CSV in this specific data copy,
since none is present alongside the pre-segmented `.npy` files; flagged as
an assumption, not a confirmed fact**):

| Pair | Class | n | Mean exit `t` | Acc. at exit | Frac. exiting into confused partner |
|---|---|---|---|---|---|
| Air Guitar ↔ Hand Clapping | Air Guitar (9) | 24 | 77.3 | 0.708 | **0.0%** |
| Air Guitar ↔ Hand Clapping | Hand Clapping (0) | 24 | 67.2 | 0.875 | **0.0%** |
| Right-Arm-CCW ↔ Left-Hand-Wave | Right-Arm-CCW (4) | 24 | 73.8 | 0.917 | **0.0%** |
| Right-Arm-CCW ↔ Left-Hand-Wave | Left-Hand-Wave (2) | 24 | 59.9 | 0.792 | **0.0%** |

**At θ*=128, none of the four flagged classes exits specifically into its
confused partner** — Air Guitar's lower exit-time accuracy (70.8%) is real
but its errors are not concentrated on Hand Clapping specifically, at this
threshold. Both flagged classes exit later than the DVS-Gesture mean
(all four exit times are in the 60–83 range, above the 67.9 mean β=128 exit
time only for 2 of 4), consistent with — but not strong evidence for —
the idea that harder-to-discriminate classes take longer to reach a
confident margin.

### Caveat, stated per the task's requirement

Timesteps are cut by **event count**, not wall-clock time (`README.md`
§3.2). Exiting at timestep `t` truncates the sample's **event budget**
(`t/100` of its `N_e`-scaled event count), not a fixed duration — the
"events not ingested" percentages above are directly meaningful as a
memory-traffic saving, but do **not** correspond to a fixed real-time
latency saving without also knowing the sensor's actual event rate for that
sample.

### VERDICT: **LIVE**, for DVS-Gesture specifically, as a mechanism worth carrying into a Phase-4 architecture discussion. Not tested as live or dead for N-MNIST — the numbers there argue against it being useful, but "dead" was not the framing asked for per-dataset.

---

## Experiment 3 — Input-frame (SNN-side) sparsity — **COMPLETE**

Computed directly from the existing data pipeline
(`../phase1_firing_characterization/src/neurohdc.py`: `events_to_frames`,
`_read_nmnist_bin`, `DVSGestureDataset`), no preprocessing changes. Full
test splits: DVS-Gesture (240 samples), N-MNIST (10,000 samples). Figure:
`phase3_experiments/artifacts/figures/exp3_input_sparsity_histogram.png`.
Full table: `phase3_experiments/artifacts/tables/exp3_input_sparsity.json`.

| Statistic | DVS-Gesture | N-MNIST |
|---|---|---|
| Active addresses/timestep (of 512): mean | **51.0%** | **5.77%** |
| P10 / P50 / P90 | 35.5% / 51.2% / 66.0% | 3.7% / 5.9% / 7.6% |
| Per-address nonzero count: median / P90 / P99 | 3 / 34 / 230 | 1 / 2 / 4 |
| Addresses for 50% of a timestep's events: mean | 15.0 (of ~261 active) | 10.1 (of ~30 active) |
| Addresses for 90% of a timestep's events: mean | 91.5 | 25.8 |
| Consecutive-timestep active-set overlap (Jaccard): mean | 0.545 | 0.359 |

**The two datasets point in opposite directions, and the finding is stated
plainly per the task's instruction not to editorialize beyond the number:**

- **DVS-Gesture: most rows are active (~51% of 512 addresses, per
  timestep).** A crossbar performing the SNN matrix-vector multiply for
  DVS-Gesture sees a **dense** operand most of the time — this **strengthens**
  the case for a dense/parallel crossbar MVM on the SNN side for this
  dataset, and correspondingly weakens any input-sparsity-exploiting design
  for it specifically.
- **N-MNIST: few rows are active (~5.8% of 512 addresses, per timestep).**
  A crossbar performing the SNN MVM for N-MNIST sees a **near-empty**
  operand most of the time — this **weakens** the case for a dense crossbar
  and would **strengthen** an input-sparsity-exploiting (skip/gather) design,
  for N-MNIST specifically.
- **Within-timestep concentration is real but secondary to the dense/sparse
  split above**: even DVS-Gesture's "active" addresses are unevenly loaded
  (median per-address count 3, P99 230 — a small number of hot pixels carry
  a disproportionate share of events; 15 of ~261 active addresses account
  for half the timestep's events), so a design for DVS-Gesture could still
  exploit *count* concentration even though it cannot exploit *occupancy*
  sparsity.
- **Temporal persistence of the active-address set is moderate for
  DVS-Gesture (Jaccard 0.545) and weaker for N-MNIST (0.359)** — consecutive
  timesteps share roughly half their active addresses for DVS-Gesture,
  meaning a scheme that caches or reuses the previous timestep's active-row
  set would be more effective for DVS-Gesture than for N-MNIST.

### VERDICT: **Dataset-dependent, computed, not assumed.** DVS-Gesture's SNN-side input is dense (weakens an input-sparsity CIM story there); N-MNIST's is sparse (strengthens one there). Any single input-sparsity claim for "NeuroHDC" without naming the dataset is not supported by this measurement.

---

## Experiment 4 — Per-access energy parameter α — **INCONCLUSIVE, no number invented**

**What was tried:**
- CACTI: not installed in this environment; no internet-accessible package
  manager entry for the memory-simulator CACTI (the `cacti` apt package that
  does exist is an unrelated network-monitoring tool); no `sudo` access to
  install from source, and building CACTI from source (a C++ academic tool
  with known finicky, version-specific build requirements) was judged out of
  the time budget for this task.
- Published macro energy tables for the *exact* array shapes requested
  (128×24 b class-HV macro, a 100-bit-word SRAM, a 512×160 SNN-weight
  macro) at NeuroHDC's own technology node (SkyWater 130 nm, or the paper's
  45 nm-scaled comparison point): **not found.** The NeuroHDC paper itself
  (Table III, already fully extracted in `README.md`) reports only
  *aggregate* inference energy per dataset, with no per-block or
  per-access breakdown that would let `alpha` be backed out. The
  comparison papers surveyed in `novelty_review_and_proposals.md` (MEMHD,
  IMPULSE, HDStream) report their own energy/cycle numbers from NeuroSim or
  measured silicon, but for *their own* array shapes, not NeuroHDC's
  class-HV or SNN-weight macro geometry — reusing those numbers would mean
  presenting an unrelated array's measured energy as if it applied to
  NeuroHDC's, which is not defensible.

**Per the task's explicit instruction — "if you cannot get a defensible
alpha, say so and leave the sweep as-is; do not invent a number" — this is
exactly what is done here.** `phase3_experiments/src/energy_model.py` is
carried over unmodified in its sweep behavior (alpha ∈ {0, 5, 20, 50, 200},
the same grid as the file already contained); no single "measured" alpha
value was substituted into it, and no ranking claim about which layout wins
is made from an unmeasured number.

**What would actually be needed to close this:** either (a) a working CACTI
build against the same 130 nm SRAM compiler characterization NeuroHDC's
authors used (not publicly available), or (b) direct correspondence with the
NeuroHDC authors for their PrimeTime per-block energy breakdown (the paper
states PrimeTime was used for energy analysis, section VI-A, but only
publishes the total), or (c) synthesizing and place-and-routing a
comparable small SRAM macro in an open PDK (e.g. SkyWater 130 nm, matching
the paper's own node) and extracting `alpha` from the resulting layout —
all three are real engineering efforts beyond this task's scope, not
something a literature estimate can responsibly substitute for.

### VERDICT: **DEAD END for this pass, honestly reported as such — not a negative result about any architecture idea, a negative result about data availability.**

---

## Threats to validity

- **The frozen training recipe was tuned for the unfactorized baseline and
  reused verbatim for every factorized configuration, per the task's hard
  rule.** The dominant pattern in the entire Experiment 1 sweep — accuracy
  degrading and variance growing monotonically with rank, i.e. with raw
  parameter count — is most plausibly a symptom of this: nothing in the
  training recipe (learning rate, epoch count, weight decay, grad-clip norm)
  was re-tuned for the larger, more non-convex parameter spaces of higher
  ranks. **This means the reported numbers are a faithful measurement of
  "factorization under the baseline's recipe," not necessarily a ceiling on
  what factorization could achieve under a recipe suited to it.** The task
  explicitly required the frozen recipe, so this is a disclosed scope
  boundary, not a shortcut taken.
- **All 36 Experiment 1 runs used the same fixed validation split** (users
  19–23 held out) and the same 200-epoch budget; no early-stopping-aware or
  rank-aware epoch budget was tried, so it is possible (not tested) that
  smaller ranks converge faster and would benefit less from more epochs
  while larger ranks are still improving at epoch 200 — the per-epoch
  histories in each run's sidecar JSON would let this be checked, but it
  was not done here.
- **Training ran under heavy, variable CPU contention** (from 6 to 12
  concurrent processes across different batches, observed throughput 39–80
  s/epoch vs. ~4.7 s/epoch solo). This affects wall-clock time only, not
  correctness — training is deterministic given the seed and unaffected by
  how many other processes share the CPU — but is noted for anyone trying
  to reproduce the wall-clock timings in the log files.
- **Experiment 2's confusion-pair label mapping is an assumed external
  convention**, not verified against a per-sample label file in this
  dataset copy (none exists in the extracted archives). If the standard
  IBM 11-class ordering does not match how this specific pre-segmented
  `.npy` data was labeled, the confusion-pair rows (not the accuracy/exit
  numbers, which do not depend on class *names*) would be mislabeled.
- **Experiment 3 subsamples pooled per-address nonzero counts** (2% of
  nonzero entries, for memory reasons given N-MNIST's 10,000×100×512
  scale) — the percentile statistics reported are therefore themselves
  subject to sampling noise, though the sample size (millions of pooled
  values even at 2%) makes this a minor concern relative to the other
  caveats here.
- **Experiment 4's absence of a measured alpha means every alpha-dependent
  conclusion anywhere in this project** (`energy_model.py`'s break-even
  table, the earlier Phase-2/3 architecture exploration documents) **remains
  unvalidated against a real number** — this was already true before this
  task and is not newly introduced by it, but it is worth restating plainly
  here since Experiment 4 was the chance to resolve it and did not.

## What we still don't know

- **Whether a rank-aware retraining recipe (different LR, weight decay,
  grad-clip norm, or epoch budget per rank) would flatten or reverse the
  observed accuracy-vs-rank degradation.** This is the single most
  consequential open question this pass leaves — the task's hard rule
  correctly prevented exploring it here, but it means Experiment 1's verdict
  (INCONCLUSIVE) is a statement about factorization *under the baseline's
  recipe*, not about factorization's ceiling.
- Whether Experiment 2's early-exit benefit for DVS-Gesture (θ=128 recovers
  full accuracy at 32% events saved) survives being combined with
  Experiment 1's factorized class-HV — not tested; Experiment 2 used only
  the unfactorized baseline's captured rasters throughout.
- Whether Experiment 3's dense-vs-sparse SNN-input finding (DVS-Gesture 51%
  active, N-MNIST 5.8% active) holds at other array/pooling configurations
  (`β` values) not tested here — this measurement used the frozen, already-
  fixed `β` for each dataset only.
- A real, sourced `alpha` — Experiment 4 could not produce one in this
  environment; every layout-comparison conclusion in this project (here and
  in earlier phases) remains conditional on it. The three concrete paths
  listed in Experiment 4's writeup (CACTI against the matching PDK, author
  correspondence for the PrimeTime breakdown, or a from-scratch macro
  synthesis) are the way to actually close this, not a literature estimate.
- Whether the binary-beats-fp pattern (consistent across all 5 ranks tested)
  and the SVD-init-beats-random-init pattern (consistent across both modes
  at R=4) generalize to N-MNIST or to a larger/less data-starved DVS-Gesture
  training set — both patterns were observed only on the current 769-sample
  DVS-Gesture subtrain split.
