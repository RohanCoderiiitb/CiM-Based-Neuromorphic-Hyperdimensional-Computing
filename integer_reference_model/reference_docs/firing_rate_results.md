# NeuroHDC Output Spike-Raster Firing-Rate Characterization — Results

**Status: [E] Experimental. Phase 1 measurement only. No CIM architecture is proposed anywhere in this document.**

> ## ⚠️ DVS-Gesture results in this document are CURRENT (v2), superseding a PROVISIONAL (v1) run
>
> An earlier capture of DVS-Gesture (test accuracy 58.75–60.42%, obtained
> from a methodologically-flawed, test-set-selected training run — see
> `dvs_accuracy_report.md` and `neurohdc_implementation_audit.md`) is
> **superseded** by the results below, which come from a properly
> validation-selected, accuracy-improved frozen configuration (mean test
> accuracy **82.36% ± 2.08%** across 3 seeds, best seed **84.58%**, vs. the
> paper's 87.5%). **The v1 artifacts are preserved, not deleted**, under
> `archive_dvsgesture_v1_provisional/` for the historical record. Do not cite
> the v1 numbers (`r=0.105`, `σ=0.193`) as representative of NeuroHDC on
> DVS-Gesture — they were measured on a model far from the paper's reported
> accuracy. **N-MNIST results are unaffected and unchanged** by this update.

**Question answered:** is the NeuroHDC **output** spike raster `S ∈ {0,1}^{n×T}` (n=20, T=100)
itself sparse, and if so, at what structure/granularity — as a standalone measurement,
independent of the paper's already-established **input** AER sparsity claim.

This document reports what was measured, exactly how, and the results, with no
downstream architectural interpretation beyond what §8 explicitly scopes.

---

## 1. Where the NeuroHDC implementation is (repository audit)

**No official NeuroHDC implementation exists anywhere in this repository or
publicly.** This was established in `README.md` §13.1 and re-confirmed
during the accuracy-improvement work (`neurohdc_implementation_audit.md`).
Code used for this experiment lives entirely under
`phase1_firing_characterization/src/`:

| File | Role |
|---|---|
| `neurohdc.py` | Core algorithm: data parsing, address-generation SumPool, IF neuron, QAT, model |
| `train_dvs.py` | DVS-Gesture training with validation-based model selection (Phase 2/3) |
| `capture_dvs_frozen.py` | Raster capture from the frozen, accuracy-improved DVS-Gesture model (Phase 4, this document) |
| `train_and_capture.py` | N-MNIST training + capture (unchanged from the original run) |
| `analyze.py` | Statistics (F1–F12, F15-equivalent) and figures for both datasets |

**Part A of `neurohdc_implementation_audit.md` verified, item by item, that
the core NeuroHDC algorithm/dataflow (encoding, SNN, query) is faithful to
the paper** — no architectural discrepancy was found or is claimed anywhere
in this document. Every DVS-Gesture accuracy issue traced to
training-procedure choices (Part B of that audit), not the algorithm.

Tables I–IV of the paper (accuracy targets, hardware configs) were recovered
from the PDF's rendered page images in an earlier pass, resolving the
original blocker B4. `N-MNIST 97.28%` and `DVS-Gesture 87.5%` (both
`n=20, T=100`) are used throughout as the accuracy-match targets.

---

## 2. Datasets supported and used

| Dataset | Status | Used here? |
|---|---|---|
| N-MNIST | Present locally, full 60,000 train / 10,000 test | **Yes — unchanged from the original run** |
| DVS-Gesture (DVS128) | Present locally, official split (users 1–23 train / 24–29 test), 11th "Other" class excluded | **Yes — re-run under the frozen, accuracy-improved configuration** |
| DVS-ASL | Not present locally (external download required) | **No — out of scope, unchanged** |

DVS-Gesture: 979 official training samples (98/class over 10 classes),
further split into 769 subtrain / 210 validation (5 of the 23 training
users held out — `user19`–`user23`) for model selection; 240 official test
samples (24/class), touched exactly once per seed for the final evaluation.

---

## 3. Exact preprocessing used

Unchanged from the original run for the parts common to both datasets
(equal-event-count binning, SumPool as address generation per eq. 19, IF
neuron with `V_reset=0`, no leak, no bias, 8-bit QAT, direct spike
concatenation) — see `neurohdc_implementation_audit.md` Part A for the
complete, re-verified checklist. **What changed for DVS-Gesture** (full
detail and rationale in `dvs_accuracy_report.md`):

1. **Input scaling: `raw`, not `per_sample_norm`.** The v1 capture divided
   every timestep's frame by that sample's own mean events/timestep — an
   operation **not supported by eq. (16)**, which defines
   `X(t) = W_s·D_flat(t)ᵀ` directly on the raw (unnormalized) SumPooled
   count tensor. This is now fixed for DVS-Gesture: `D_flat(t)` is used raw,
   exactly as eq. (16) specifies. (N-MNIST is unaffected — its original run
   already used `per_sample_norm` and is not revisited here, out of scope
   for this task.)
2. **Threshold calibration at init** (label-free): `v_thresh`'s initial
   value is set from the median `|X(t)|` on one calibration batch under the
   freshly-initialized weights, then trained normally like every other
   parameter. **[O]**, not paper-specified.
3. **Per-channel (per-neuron) 8-bit weight quantization**, rather than one
   scale shared by all 20 neurons — arguably more consistent with the
   paper's own hardware description (§V-A: each neuron's weights stored
   independently in its own SRAM macro). **[O]**.
4. **Gradient clipping** (`clip_grad_norm_`, max norm 0.5) — absent from
   every prior run. This architecture is a 100-step unrolled recurrence
   (BPTT through a hard-reset nonlinearity each step, paper eq. 12–16); the
   absence of gradient clipping in any earlier run turned out to be the
   single largest contributor to the DVS-Gesture accuracy gap (see
   `dvs_accuracy_report.md` §3). **[O]**, standard technique, not
   paper-specific.
5. **Weight decay (`1e-4`) and event-dropout augmentation (`p=0.1`)** during
   training only — both **[O]**, explicitly not paper-supported, disclosed.
6. **Model selection now uses a validation split**, never the test set
   (v1's flaw). Five of the 23 official training users (`user19`–`user23`)
   are held out for validation; the official test users (`user24`–`29`) are
   touched exactly once per seed, after the configuration is frozen.

---

## 4. Model configuration and training

| Parameter | N-MNIST (unchanged) | DVS-Gesture (frozen, this document) |
|---|---|---|
| `n`, `T`, `D_hv` | 20, 100, 2000 | 20, 100, 2000 |
| Input scaling | `per_sample_norm` **[O]** | `raw` **[S]-restoring** (eq. 16) |
| Threshold | trainable scalar, fixed init | trainable scalar, **calibrated** init **[O]** |
| QAT granularity | per-tensor | **per-channel** **[O]** |
| Optimizer | Adam, lr=1e-3 | Adam, lr=1e-3, **cosine schedule** |
| Weight decay / event dropout | 0 / 0 | **1e-4 / 0.1** **[O]** |
| Gradient clipping | none | **norm 0.5** **[O]** |
| Epochs | 100 | 200 |
| Model selection | best test-set epoch *(v1 methodological flaw, not revisited for N-MNIST in this task)* | **best validation-set epoch** (test set untouched until the final run) |
| Seeds | 1 (seed 0) | **3 (seeds 0, 1, 2)** |

### 4.1 Accuracy match against the paper (`n=20, T=100`)

| Dataset | Paper | This reimplementation | Gap |
|---|---|---|---|
| N-MNIST | 97.28% | 94.91% (unchanged) | −2.37 pp |
| DVS-Gesture | 87.5% | **82.36% ± 2.08%** (mean, 3 seeds) / **84.58%** (best seed) | −5.14 pp (mean) / −2.92 pp (best seed) |

DVS-Gesture's accuracy match **improved by ~22–24 points** (from
58.75–60.42% to 82.36–84.58%) as a direct result of the fixes in §3. Full
experiment log (10 controlled runs) and discussion of the residual gap in
`dvs_accuracy_report.md`.

---

## 5. Event-count statistics (context for the raster results — unchanged)

| Dataset | mean events/sample | P10 | P50 | P90 | mean `N_e` (events/timestep) |
|---|---|---|---|---|---|
| N-MNIST | 4,204 | 2,606 | 4,251 | 5,706 | 41.5 |
| DVS-Gesture | 407,124 | 159,537 | 334,643 | 773,809 | 4,071 |

Unchanged from the original run — event counts are a property of the raw
data and preprocessing (§3 of the earlier analysis), not of training. The
change in §3–4 only affects how these counts are used as input to the SNN
(raw vs. normalized), not the counts themselves.

---

## 6. Per-sample statistics

Full per-sample data, one row per test sample (10,240 rows: 10,000 N-MNIST +
240 DVS-Gesture, **from the frozen, seed-0 DVS-Gesture model** — the
highest-accuracy of the 3 seeds and the one used for all figures below):
**`firing_rate_stats.csv`**. Columns as before: `dataset, sample_idx, label,
pred, correct, n_events, N_e, total_spikes, firing_rate, n_active_neurons,
frac_active_neurons, n_silent_timesteps, frac_silent_timesteps,
spikes_per_timestep_{mean,std,max}, per_neuron_rate_{mean,std,min,max},
per_timestep_rate_{mean,std}`. Cross-seed consistency for DVS-Gesture
(all 3 frozen seeds) is reported separately in §7.3.

---

## 7. Dataset-level statistics

Full machine-readable summary: **`firing_rate_summary.json`** (dataset keys
`nmnist`, `dvsgesture_frozen`).

### 7.1 N-MNIST (10,000 test samples) — unchanged from the original run

| Statistic | Value |
|---|---|
| Global firing rate `r` | **0.1869** |
| Per-sample rate: mean / median / std | 0.1869 / 0.1840 / 0.0267 |
| Per-sample rate: min / max | 0.0925 / 0.3085 |
| Per-sample rate: P10 / P25 / P75 / P90 | 0.1555 / 0.1685 / 0.2026 / 0.2235 |
| Per-sample rate CV (std/mean) | 0.143 |
| Spikes/sample: mean / median / std | 373.9 / 368 / 53.5 |
| Spikes/sample: P10 / P90 | 311 / 447 |
| Per-neuron rate: mean / std / min / max | 0.1869 / 0.0749 / 0.0508 / 0.3495 |
| Per-neuron rate: Gini | 0.225 |
| Dead neurons (rate = 0, out of 20) | **0** |
| Per-timestep rate: mean / std / min / max | 0.1869 / 0.0477 / 0.1189 / 0.2571 |
| Fraction of completely silent timesteps `σ` | **0.0377** |
| Mean fraction of active neurons/sample | 0.848 |
| Burstiness `B = σ/(1−r)^n` | **2.365** |

### 7.2 DVS-Gesture — **NEW (frozen, seed 0, 84.58% test accuracy), 240 test samples**

| Statistic | v1 (superseded, 60.4% acc) | **v2 (current, 84.6% acc)** |
|---|---|---|
| Global firing rate `r` | 0.1053 | **0.3755** |
| Per-sample rate: mean / median / std | 0.1053 / 0.0915 / 0.0468 | **0.3755 / 0.3675 / 0.0778** |
| Per-sample rate: min / max | 0.0235 / 0.2415 | **0.1760 / 0.5530** |
| Per-sample rate: P10 / P25 / P75 / P90 | 0.0585 / 0.0715 / 0.1256 / 0.1845 | **0.2815 / 0.3169 / 0.4239 / 0.4875** |
| Per-sample rate CV | 0.445 | **0.207** |
| Spikes/sample: mean / median / std | 210.6 / 183 / 93.6 | **750.9 / 735 / 155.7** |
| Spikes/sample: P10 / P90 | 117 / 369 | **563 / 975** |
| Per-neuron rate: mean / std / min / max | 0.1053 / 0.0329 / 0.0390 / 0.1576 | **0.3755 / 0.1516 / 0.0635 / 0.7255** |
| Per-neuron rate: Gini | 0.178 | **0.218** |
| Dead neurons (out of 20) | 0 | **0** |
| Per-timestep rate: mean / std / min / max | 0.1053 / 0.0105 / 0.0173 / 0.1173 | **0.3755 / 0.0205 / 0.3558 / 0.4758** |
| **Fraction of completely silent timesteps `σ`** | 0.1934 | **0.00021** (5 of 24,000 timestep-observations) |
| Mean fraction of active neurons/sample | 0.506 | **0.772** |
| Burstiness `B = σ/(1−r)^n` | 1.790 | **2.555** (see §8.3 for a caveat on this statistic at near-zero `σ`) |
| Class-HV L1 norms (10 classes): mean / spread | 766.7 / 91 | **905.1 / 528** |

**The properly-trained, accuracy-matched model produces a raster more than
3.5× denser (`r`: 0.105 → 0.376) and with silent timesteps roughly 900×
rarer (`σ`: 0.193 → 0.0002) than the earlier, undertrained model.** This is
the headline finding of this update — see §10.

### 7.3 Cross-seed consistency, DVS-Gesture (all 3 frozen seeds)

| Seed | Test acc | `r` | `σ` | exact silent-timestep count (of 24,000) | `B` | Dead neurons |
|---|---|---|---|---|---|---|
| 0 | 84.58% | 0.3755 | 0.00021 | 5 | 2.555 | 0 |
| 1 | 82.92% | 0.4367 | 0.00017 | 4 | 16.097 | 0 |
| 2 | 79.58% | 0.4550 | 0.00029 | 7 | 54.525 | 0 |

**The qualitative finding — dense firing (`r` in 0.38–0.46) with
near-zero, single-digit-event silent-timestep counts — is consistent across
all 3 independently-trained seeds**, not an artifact of one run. The exact
value of `r` and the burstiness ratio `B` both vary noticeably by seed (see
§8.3 for why `B` in particular should be read cautiously at this `σ`
regime); the *structural* conclusion (dense, essentially never silent at
word granularity) does not.

---

## 8. Temporal and neuron-wise structure

### 8.1 Per-timestep firing-rate profile

Figure: `artifacts/figures/dvsgesture_frozen_per_timestep_rate.png`.

- **N-MNIST** (unchanged): non-uniform, smooth unimodal envelope — low
  (~0.13) through timestep ~35, peaking ~0.26 around timestep 60, falling to
  ~0.13 by timestep 99.
- **DVS-Gesture v2 (new)**: a **decaying transient**, the opposite shape
  from v1. Rate starts high (~0.476 at `t=0`) and decays smoothly to a
  stable plateau of ~0.36–0.37 by `t≈15–20`, then stays flat for the
  remaining ~80 timesteps (std over that plateau region ≈ 0.005). This is
  consistent with the membrane potential starting at `V(0)=0`: with raw,
  large-magnitude inputs and the calibrated threshold, the first bin's
  accumulated charge reliably crosses threshold for a wide swath of
  neurons, and the population settles into steady-state dynamics over the
  next ~15–20 timesteps.

### 8.2 Per-neuron firing-rate distribution

Figure: `artifacts/figures/dvsgesture_frozen_per_neuron_rate.png`.

DVS-Gesture v2 shows a **wide** per-neuron rate spread (0.063 to 0.725, vs.
v1's 0.039–0.158) — some neurons fire on nearly three-quarters of all
`(sample, timestep)` pairs. **Zero dead neurons**, same as v1 and as
N-MNIST. Gini coefficient (0.218) is close to N-MNIST's (0.225) and v1's
(0.178) despite the much higher overall rate — concentration *relative to
the mean* is similar even though the absolute rate is far higher.

### 8.3 Temporal clustering / burstiness — a measurement caveat

`B = σ/(1−r)^n` compares observed silent-timestep frequency to the
independent-per-neuron-Bernoulli prediction. For DVS-Gesture v2, `σ` itself
is extremely small (4–7 exact occurrences out of 24,000 timestep-samples
per seed, §7.3), and the independent-Bernoulli-predicted baseline
`(1−r)^n` shrinks **exponentially** as `r` grows — e.g. for seed 0,
`(1−0.3755)^20 ≈ 8.1×10⁻⁵`, so `B` is the ratio of two very small numbers,
one of which (the numerator) is estimated from a single-digit event count.
**This makes `B`'s exact value highly sensitive to a handful of samples**
(seed-to-seed range: 2.56–54.5, §7.3) and it should be read as "silence is
dramatically more common than pure independence would predict, especially
as `r` grows" (qualitatively robust across all 3 seeds) rather than as a
precise number (quantitatively noisy). N-MNIST's `B=2.365` does not have
this issue (`σ=0.038`, a much better-sampled quantity: ~756 of 20,000
timestep-observations).

### 8.4 Representative 20×100 rasters

`artifacts/figures/dvsgesture_frozen_raster_examples.png` (one per class,
seed 0) — visibly denser than the v1 figure it supersedes
(`archive_dvsgesture_v1_provisional/` retains the old figure references via
the old CSV/JSON, though the PNG itself was regenerated in place; the v1
`.npz` raster arrays remain available in `artifacts/rasters/dvsgesture_n20_
T100_seed0.npz` for anyone who wants to re-plot them). Several neurons show
long, near-continuous firing runs across most of the 100 timesteps — visibly
consistent with the near-zero silent-timestep fraction.

### 8.5 Per-sample variability

DVS-Gesture v2's per-sample rate is **more tightly clustered relative to its
own mean** than v1 was (CV: 0.207 vs. 0.445) — the higher-accuracy model
produces a more numerically consistent (if much denser) raster
sample-to-sample, even though the raw event-count variability across samples
(§5) is unchanged. N-MNIST (CV 0.143) is still the tightest of the three.

### 8.6 Zero-group fraction `z(g)` — access-granularity sweep

Full table: `artifacts/tables/granularity.csv`. `z(g)` = fraction of groups
of size `g` (spatial: `g` consecutive neurons within one timestep; temporal:
`g` consecutive timesteps for one neuron) containing zero spikes.

| `g` (spatial) | N-MNIST `z(g)` | DVS-Gesture v1 (superseded) | **DVS-Gesture v2 (current)** |
|---|---|---|---|
| 1 (= `1−r`) | 0.813 | 0.895 | **0.625** |
| 2 | 0.668 | 0.806 | **0.389** |
| 4 | 0.449 | 0.640 | **0.142** |
| 5 | 0.372 | 0.571 | **0.101** |
| 10 | 0.147 | 0.381 | **0.0070** |
| 20 (= `σ`, whole timestep) | **0.038** | 0.193 | **0.0002** |

Temporal grouping at `g=100` (does a given neuron ever fire across the whole
sample): N-MNIST 0.152, DVS-Gesture v1 0.494, **DVS-Gesture v2 0.2275** —
consistent with the respective active-neuron fractions (84.8%, 50.6%,
**77.2%**, §7).

**The word-level collapse is now far more severe for DVS-Gesture than for
N-MNIST — the opposite ranking from v1.** In v1, DVS-Gesture retained
*more* word-level sparsity than N-MNIST (`σ=0.193` vs. `0.038`); in v2, the
properly-trained model's DVS-Gesture raster is **essentially never** silent
at the word level (`σ=0.0002`, 16× smaller than N-MNIST's `0.038`). This
reversal is itself a central, directly-measured finding — see §10.

### 8.7 Timestep-vector-granularity deep dive (DVS-Gesture v2, seed 0) — three distinct sparsity views, not to be conflated

This section exists to answer one specific question precisely: **not** "how
sparse is the raster overall" (§7, a single pooled bit-level number), but
**"how is that sparsity distributed across the 100 individual 20-bit
timestep vectors that a CIM query would actually touch one at a time?"**
Three quantities below look superficially similar and must be kept distinct:

- **Global bit-level sparsity**: `1 − r = 0.6245` (§7.2) — pools every one
  of the 240×100×20 = 480,000 individual bits into one fraction.
- **Timestep/vector-level sparsity**: the distribution of `k_t` (active
  neurons in one 20-bit timestep vector) and of `σ_m` (fraction of a given
  *sample's* 100 timesteps that are completely silent) — this section.
- **Finer/coarser group sparsity**: `z(g)` for `g ≠ 20` (§8.6) — an
  intermediate view at group sizes other than exactly one timestep.

#### 8.7.1 Per-timestep spike count `k_t` (pooled over all 240×100 = 24,000 timesteps)

| Statistic | Value |
|---|---|
| Mean | **7.51** (of 20) |
| Median | 7 |
| Std | 2.28 |
| Min / Max | **0** / **15** (never 16–20: no timestep vector is ever more than 75% active) |
| P10 / P25 / P75 / P90 | 5 / 6 / 9 / 11 |
| Mode | 7 |

Full integer histogram (`k_t = 0…20`), pooled over all 24,000
sample×timestep pairs:

```
k_t:    0    1    2    3    4     5     6     7     8     9    10    11   12   13  14  15  16-20
count:  5   22  203  467 1289  2577  3823  4199  3674  2877  2283  1504  739  257  66  15    0
```

`artifacts/figures/dvsgesture_frozen_kt_histogram.png`. The distribution is
unimodal and fairly narrow (P10–P90 spans only 5–11 of 20 neurons) — **a
typical timestep vector is neither empty nor dense; it sits in a
moderate middle band**, and essentially never approaches either extreme.

#### 8.7.2 "20 − k_t" — zeros within one timestep vector (NOT the global bit-zero fraction)

| Statistic | Value |
|---|---|
| Mean | 12.49 (of 20) |
| Median | 13 |
| Std | 2.28 |
| Min / Max | 5 / 20 |
| P10 / P25 / P75 / P90 | 9 / 11 / 14 / 15 |

**Explicit distinction the task asked for:** the *mean* of this
per-timestep-vector quantity, divided by `n=20`, is mathematically identical
to the global bit-zero fraction (`12.49/20 = 0.6245 = 1−r`) — that
equivalence is expected and is a consistency check, not a new number. **What
is new here is the *shape* of the distribution**, which the single global
fraction cannot show: every observed timestep vector has **at least 5**
zeros (never more than 15 of 20 neurons fire together) and **at most 20**
(fully silent, occurring only 5 times out of 24,000). The middle 80% of
timesteps (P10–P90) have 9–15 zeros — i.e. 5–11 active neurons — matching
§8.7.1 by construction (`zeros = 20 − k_t`).

#### 8.7.3 Per-sample silent-timestep fraction `σ_m` — distribution across the 240 samples

| Statistic | Value |
|---|---|
| Mean | 0.000208 |
| Median | **0** |
| Std | 0.00143 |
| Min / Max | 0 / **0.01** (i.e. at most 1 silent timestep out of 100, in any sample) |
| P10 / P25 / P75 / P90 | 0 / 0 / 0 / **0** |

`artifacts/figures/dvsgesture_frozen_sigma_per_sample_hist.png`. **235 of
240 test samples (97.9%) have σ_m = 0 exactly** — not one silent timestep
anywhere in the entire 100-timestep sequence. The remaining 5 samples each
have exactly 1 silent timestep (σ_m = 0.01). Even the 90th percentile sample
has zero silent timesteps. This is a much stronger and more specific
statement than the pooled global `σ = 0.0002` (§7.2) alone would suggest:
it is not that silence is thinly spread across many samples — it is
**absent from the overwhelming majority of samples entirely**, and confined
to a handful of isolated occurrences in a small minority.

#### 8.7.4 Consecutive-run-length structure (F10, `firing_rate_experiment_spec.md`, extended symmetrically to active runs)

| | Silent runs | Active runs |
|---|---|---|
| Count (total, pooled) | **5** | 243 |
| Mean length | 1.0 | 98.74 |
| Median length | 1 | **100** |
| Min / Max length | 1 / 1 | 33 / 100 |
| P10–P90 | 1 / 1 | 100 / 100 |

**All 5 silent-timestep occurrences are isolated singletons** — every
observed silent run has length exactly 1; there is not one instance of two
or more consecutive silent timesteps anywhere in the 240-sample test set.
Correspondingly, 235 of 240 samples consist of one single unbroken active
run of length 100 (the full sample); the 5 samples with one silent timestep
are each split into two active runs by that single interruption (accounting
for the 243 total active-run count and the min=33 outlier — one sample's
silent timestep falls early enough to leave a shorter first segment). **At
the timestep-vector granularity, "silence" in this model is not bursty at
all — it is a vanishingly rare, single-timestep event, never a run.**

**Reading `B=2.555` (§7.2) alongside this:** the burstiness ratio compares
the observed *frequency* of silence to an independence-adjusted baseline,
and remains informative about how much rarer independent firing would
predict silence to be; the run-length data here adds the complementary fact
that whatever silence does occur is never temporally clustered into
multi-timestep bursts — the two statistics answer different questions and
neither substitutes for the other.

---

## 9. Limitations and reproducibility issues

1. **Full reimplementation, not reproduction** (unchanged caveat) — no
   official code, checkpoint, or hyperparameters exist for NeuroHDC.
2. **DVS-Gesture is close to, but does not fully match, the paper's
   accuracy** (84.58% best seed / 82.36% mean vs. 87.5%, a 3–5 point gap).
   See `dvs_accuracy_report.md` §7 for the full discussion of why this
   residual gap is judged likely attributable to genuinely undisclosed
   paper details rather than a further reachable fix. The firing-rate
   statistics in this document are measured on models close to but not
   exactly at the paper's reported operating point.
3. **N-MNIST was not revisited in this task** (out of scope, per the task's
   explicit DVS-Gesture-only framing) — its `per_sample_norm` input scaling
   remains an undisclosed-but-unaddressed deviation from eq. (16), parallel
   to DVS-Gesture's now-fixed one. This is flagged, not silently carried
   forward as though resolved.
4. **3 seeds for DVS-Gesture** (up from 1) — better than before, still short
   of the kind of seed count that would give a tight confidence interval on
   `r`, `σ`, or `B` individually (§8.3 notes `B`'s particular sensitivity).
5. **No `(n,T)` sensitivity sweep, no early-exit experiment, no rate-penalty
   malleability sweep** were run for DVS-Gesture in this pass either — same
   scope limitation as the original document.
6. **DVS-ASL excluded entirely** — data not available in this environment.
7. **No independent hardware-identity check** (XNOR-popcount vs.
   bipolar-dot-product) was run as a separate empirical test — algebraically
   exact by construction, not independently re-verified in code.
8. **The v1→v2 comparison in this document is itself evidence that firing-
   rate statistics are sensitive to training quality**, which is a
   methodological point worth carrying forward explicitly: any future
   firing-rate measurement on a NeuroHDC reimplementation should be
   accompanied by its accuracy-match quality, not reported in isolation.

---

## 10. Interpretation — strictly experimental, no architecture proposed

**1. How sparse is the NeuroHDC output spike raster actually?**
This now has a **dataset- and training-quality-dependent** answer, more
sharply than before. N-MNIST: `r=0.187` (moderately sparse, unchanged).
DVS-Gesture, properly trained: `r=0.376` (denser than N-MNIST, denser than
the `r≈0.5` "BNN default" the original document flagged as a prior risk —
though still below it). At the **word level** (one 20-bit timestep), the
picture is starker: N-MNIST retains some exploitable sparsity (`σ=0.038`,
96.2% of words touched), while **properly-trained DVS-Gesture retains
essentially none** (`σ=0.0002`, 99.98% of words touched, consistent across
all 3 seeds). **Sparsity is not a fixed property of "the NeuroHDC output
raster" in the abstract — it depends materially on which dataset and,
within a dataset, on how close the trained model is to the paper's reported
accuracy.**

**2. Is the sparsity consistent across samples?**
DVS-Gesture v2's per-sample rate is *more* consistent (CV 0.207) than v1's
was (CV 0.445), even though the underlying raw event-count variability (§5)
is identical — the higher-accuracy model produces a numerically steadier,
if much denser, raster. N-MNIST remains the most consistent of the three
(CV 0.143).

**3. Is it consistent across neurons?**
In both v1 and v2, DVS-Gesture has zero dead neurons and a moderate Gini
coefficient (0.178 → 0.218, both similar in magnitude to N-MNIST's 0.225)
despite the large change in absolute rate — relative concentration across
neurons is fairly stable even as the overall density shifted substantially.

**4. Is it consistent across timesteps?**
No — and the *shape* of the non-uniformity changed direction between v1 and
v2. v1 showed a rising-then-flat profile (low at `t=0`, climbing to a
plateau). v2 shows a **falling** transient (high at `t=0`, decaying to a
lower, stable plateau by `t≈20`). Both are non-uniform; which end is high
and which is low flipped along with the accuracy fix, which is itself an
informative result about how sensitive the temporal profile is to training
quality, not just to the dataset.

**5. Does the raster exhibit temporal clustering?**
Yes in both v1 and v2, by the burstiness measure (`B > 1` throughout,
§7.3), though `B`'s precise value for DVS-Gesture v2 should be read with the
§8.3 caveat about its sensitivity at near-zero `σ`. Qualitatively, the
representative raster plots (§8.4) show sustained, non-independent
same-neuron firing runs in both versions.

**6. Does the measured sparsity appear potentially exploitable in the
similarity computation?**

**Still strictly a measurement question — no CIM architecture is proposed
here.** What changed from the original document's answer:

- The original document's headline number (a "1.04–1.24× word-level
  reduction" for both datasets) was **partly an artifact of measuring an
  undertrained DVS-Gesture model.** With the accuracy gap substantially
  closed, DVS-Gesture's word-level reduction is now `1/(1−σ) ≈ 1.0002×` —
  i.e., **essentially none** — while N-MNIST's (`1/(1−0.038) ≈ 1.04×`,
  unchanged, since N-MNIST was not retrained in this task) remains as
  originally measured.
- **This is now the more decisive, better-supported version of the finding
  the original document could only partially support**: at realistic
  access granularity (one timestep word), word-level sparsity is minimal to
  nonexistent for both datasets once the model is close to the paper's
  reported accuracy, and the earlier appearance of more usable DVS-Gesture
  sparsity was specifically a symptom of that model not yet matching the
  paper.
- **What this experiment still does not and cannot establish**, unchanged
  from the original document: the cost of skip/gating logic, whether a
  rate-penalty during training could push `r` down at acceptable accuracy
  cost (not tested for either dataset, and now a materially more important
  open question given how dense the properly-trained DVS-Gesture raster
  turned out to be), and any comparison against a specific hardware cost
  model. These remain open, and are explicitly out of scope for this
  document per the task's research constraint.

**7. At what spatial access granularity does the current DVS-Gesture
representation exhibit meaningful sparsity?** (§8.7, `z(g)` from §8.6)

Answering strictly from the measured `z(g)` curve, with **no claim that a
zero fraction equals an energy or latency saving** — this is a
representation characterization only:

| Granularity `g` | `z(g)` | Reading |
|---|---|---|
| 1 bit | 0.625 | Majority-zero at the single-bit level |
| 2 | 0.389 | Roughly a third of pairs are all-zero |
| 4 | 0.142 | Sparsity mostly gone |
| 5 | 0.101 | Sparsity mostly gone |
| 10 | 0.0070 | Essentially no all-zero half-timestep groups |
| **20 (one full timestep vector)** | **0.0002** | **No meaningful sparsity — a timestep vector is almost never all-zero** |

**The transition from "some exploitable zero-group structure" to "none" happens
somewhere between `g=1` and `g=10`, and is essentially complete by `g=10`**
(`z(10)=0.007`, under 1%). By `g=20` — the actual granularity of one
NeuroHDC timestep vector, i.e. the unit this task asked about — there is
**no meaningful sparsity left to characterize**: 99.98% of timestep vectors
contain at least one active neuron (§8.7.3: 97.9% of samples contain *zero*
silent timesteps at all, not just "few"). The finer per-timestep-vector view
in §8.7 (the `k_t` distribution, run-length analysis) confirms this isn't a
borderline or noisy result — `k_t` never once reaches 0 except in 5 of
24,000 observations, each an isolated single-timestep occurrence with no
multi-timestep bursts of silence anywhere in the test set. **At the
20-bit/one-timestep granularity relevant to a per-timestep memory access,
the current accuracy-matched DVS-Gesture representation is, as measured,
effectively dense.**

---

## 11. Output files

| File | Contents |
|---|---|
| `firing_rate_results.md` | This document (v2, DVS-Gesture superseding v1) |
| `firing_rate_stats.csv` | Per-sample statistics, 10,240 rows (10,000 N-MNIST + 240 DVS-Gesture v2, seed 0) |
| `firing_rate_summary.json` | Dataset-level summary statistics, keys `nmnist`, `dvsgesture_frozen` |
| `spike_rasters.npz` | Complete `[M,T,n]` uint8 rasters for N-MNIST (unchanged) and **all 3 frozen DVS-Gesture seeds** (`dvsgesture_frozen_seed{0,1,2}_*`) |
| `dvs_accuracy_report.md` | Full accuracy-improvement experiment log, frozen configuration, and gap discussion |
| `neurohdc_implementation_audit.md` | Paper-vs-implementation parameter audit (Parts A and B) |
| `artifacts/tables/granularity.csv` | Full `z(g)` sweep, spatial and temporal, both datasets, current numbers |
| `artifacts/figures/dvsgesture_frozen_*.png` | Current DVS-Gesture figures: firing-rate histogram, spikes/sample, per-neuron rate, per-timestep rate, raster examples, **`kt_histogram` (§8.7.1, k_t=0..20 pooled histogram)**, **`sigma_per_sample_hist` (§8.7.3, per-sample silent-fraction distribution)** |
| `artifacts/figures/nmnist_*.png` | N-MNIST figures, unchanged |
| `artifacts/figures/granularity_curve_spatial.png` | `z(g)` vs. spatial group size, current numbers for both datasets |
| `artifacts/dvs_accuracy/*.json`, `*.pt` | Every Phase 2/3 experiment's config, history, and checkpoint |
| `artifacts/rasters/dvsgesture_frozen_n20_T100_seed{0,1,2}.{npz,json}` | Current DVS-Gesture raw captures, all 3 seeds |
| `artifacts/rasters/dvsgesture_n20_T100_seed0.{npz,json}` | **Superseded** v1 DVS-Gesture capture, preserved for the record |
| `archive_dvsgesture_v1_provisional/` | Full v1 top-level deliverables (results doc, CSV, JSON, npz, granularity table), preserved unmodified |
| `src/neurohdc.py`, `src/train_dvs.py`, `src/capture_dvs_frozen.py`, `src/analyze.py` | All code used to produce every number and figure in this document |
