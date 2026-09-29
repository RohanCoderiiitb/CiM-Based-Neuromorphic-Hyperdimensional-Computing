# NeuroHDC Output Spike-Raster Firing-Rate Characterization — Results

**Status: [E] Experimental. Phase 1 measurement only. No CIM architecture is proposed anywhere in this document.**

**Question answered:** is the NeuroHDC **output** spike raster `S ∈ {0,1}^{n×T}` (n=20, T=100)
itself sparse, and if so, at what structure/granularity — as a standalone measurement,
independent of the paper's already-established **input** AER sparsity claim.

This document reports what was measured, exactly how, and the results, with no
downstream architectural interpretation beyond what §8 explicitly scopes.

---

## 1. Where the NeuroHDC implementation is (repository audit)

**No official NeuroHDC implementation exists anywhere in this repository or
publicly.** This was already established in `README.md` §13.1 and
`firing_rate_experiment_spec.md` (blockers B1–B3) prior to this experiment, and
was re-confirmed here. What exists in the repository before this experiment:

| Item | Location | Content |
|---|---|---|
| Literature reconstruction | `README.md` | Reverse-engineered NeuroHDC algorithm/dataflow, no code |
| Measurement spec | `firing_rate_experiment_spec.md` | Directly-implementable spec for this experiment, no code |
| Paper | `Neuromorphic_Hyperdimensional_Computing_for_Efficiently_Processing_Event-Based_Data.pdf` | The TVLSI paper itself |
| Datasets | `data/NMNIST/`, `data/DVSGesture/` | Raw/pre-segmented event data, no model code |
| Python env | `myenv/` | `torch 2.14.0+cu130`, `numpy`, `pandas`, `matplotlib`, `tonic`; **no `spikingjelly`** |

This experiment's code was written from scratch under
`phase1_firing_characterization/src/` (`neurohdc.py`, `train_and_capture.py`,
`analyze.py`). **This is a full reimplementation, not a reproduction.** No
pretrained NeuroHDC checkpoint exists anywhere (confirmed again during this
task: GitHub, the authors' names, NUAA group pages, Gitee, OpenI — nothing).
Every number below is a property of *this* reimplementation, trained from
scratch once per dataset, not of the original authors' model.

### 1.1 What was newly resolved in this task (vs. the prior README/spec state)

`README.md` §13.1 (blocker B4) stated that Tables I–III could not be recovered
from the PDF's text extraction. For this task the PDF was re-read as rendered
page images, and **Tables I, II, III, and IV were successfully recovered**:

- **Table I** (accuracy vs. timestep scaling, `n=20`): N-MNIST 97.28% at
  `T=100, D_hv=2000`; DVS-Gesture 87.5% at the same setting.
- **Table II** (accuracy vs. state of the art): confirms the same NeuroHDC
  numbers, plus DVS-ASL 89.38% at `n=40, D_hv=4000`.
- **Table III** ("NeuroHDC-small", `n=20`, matches Tables I/II exactly) and
  Table IV (FPGA resource/throughput) — not needed for this experiment but
  recorded here for completeness and to close blocker B4/U10/U11.

These accuracy figures (**N-MNIST 97.28%, DVS-Gesture 87.5%**) are used below
as the accuracy-match targets. No new information about `V_thresh`, `β`, or
training hyperparameters was recoverable from the paper — those remain
genuinely unspecified (§4).

---

## 2. Datasets supported and used

| Dataset | Status | Used here? |
|---|---|---|
| N-MNIST | Present locally (`data/NMNIST/{Train,Test}`, raw `.bin` AER files, standard Orchard et al. 5-byte-per-event format) | **Yes** |
| DVS-Gesture (DVS128) | Present locally (`data/DVSGesture/ibmGesture{Train,Test}`, pre-segmented per-instance `.npy` event arrays `[x,y,p,t]`) | **Yes** |
| DVS-ASL | **Not present locally**; requires external download (Dropbox/Google Drive links per `README.md` blocker B10) not available in this environment | **No — excluded** |

Per the task instructions ("run the characterization on the available
NeuroHDC datasets/configurations that can be reproduced faithfully"), only
N-MNIST and DVS-Gesture are reported. DVS-ASL is out of scope for this pass
because its data is not present in this repository/environment; nothing about
it is claimed or estimated.

N-MNIST: 60,000 train / 10,000 test, 10 classes, 34×34 sensor.
DVS-Gesture: raw archive already extracted into 1,077 train-side and 264
test-side pre-segmented per-gesture `.npy` files (11 classes × ~98 train /
~24 test instances each); the 11th "Other" class (label index 10) is
excluded per the paper (§IV-A) and `README.md` §4.4, leaving **979 train /
240 test** samples over 10 classes, 128×128 sensor.

---

## 3. Exact preprocessing used

Implemented in `src/neurohdc.py`. All steps are asserted to match the
paper's stated algorithm (`README.md` §10 invariants):

1. **Event parsing.** N-MNIST: 5-byte AER records (`x, y, polarity, timestamp`
   packed as documented in `_read_nmnist_bin`), events sorted by timestamp.
   DVS-Gesture: `[x, y, p, t]` float arrays already time-ordered per file
   (re-sorted defensively).
2. **Equal-event-count binning into `T=100` timesteps** — event index `k`
   (0-based, time-sorted) assigned to bin `⌊k·T / N_events⌋`, vectorized via
   `np.bincount`. This matches the paper's eq. (8)/§III-B ("we divide them
   uniformly, ensuring an equal number of events in each") to within at most
   1 event per bin, **not** by wall-clock time.
3. **SumPool as address generation** (paper eq. (19), §V-B) — for each event,
   `addr = p·256 + ⌊y·16/H⌋·16 + ⌊x·16/W⌋` where `(H,W)` is the sensor
   resolution (34×34 for N-MNIST, 128×128 for DVS-Gesture). Counts are
   accumulated per address per timestep bin via `np.bincount`; **the pooled
   frame is never spatially filtered or materialized as an image** — this is
   exactly the address-truncation mechanism the paper describes for hardware,
   not a lossy CNN-style downsample.
   - **Deviation from `firing_rate_experiment_spec.md` §1**, noted explicitly
     per the task's discrepancy-tracking requirement: the spec proposed
     cropping/padding N-MNIST to 32×32 before applying an integer `β=2`. That
     crop/pad step is the *spec's own inference* (tagged `[E]`/plan, not
     `[S]` from the paper) — the paper never specifies `β` for any dataset
     (`README.md` blocker B7: "value never given"). This implementation
     instead applies the address formula directly to the native 34×34
     resolution (a non-integer effective `β = 34/16 = 2.125`), which is an
     equally valid instance of "a per-dataset resize factor" and avoids
     introducing an unstated crop/pad step. This is a genuine, disclosed
     deviation from the spec's suggested plan, not from anything the paper
     states, since the paper states no value for `β` at all.
4. **Input scaling ("CHOICE", resolves spec blocker U5):** per-sample
   normalization — each sample's `[T,512]` count frame is divided by that
   sample's own `N_e = ⌊n_events/T⌋`. The paper does not specify this either
   (spec U5: "unspecified... changes drive and therefore r"). Chosen because
   raw event counts vary by two orders of magnitude between N-MNIST (~4,200
   events/sample) and DVS-Gesture (~407,000 events/sample; see §5 event
   statistics below), and unnormalized counts made both models
   untrainable in preliminary tests (saturating or silent nets).
5. **IF neuron, exactly as specified**: `V_p(t) = V(t−1) + X(t)`,
   `S(t) = Θ(V_p(t) − V_thresh)`, hard reset `V(t) = V_p(t)·(1−S(t))`, no
   leak, no bias (`neurohdc.py: NeuroHDC.forward`). Backward pass uses an ATan
   surrogate gradient (SpikingJelly-style), since the paper cites Neftci et
   al. for its surrogate but never gives the exact function/width (spec U3).
6. **SNN weights `W_s`**: int8 signed, straight-through per-tensor fake
   quantization applied on every forward pass (QAT), per paper §III-C.
7. **Encoding**: direct concatenation, nothing else. `raster.reshape(B, T*n)`
   is the *only* operation between the captured spikes and the classifier
   head, asserted by construction in the code (`D_hv == n*T = 2000`).
8. **Class hypervectors**: `C = Sign(W_c)` via a straight-through estimator,
   `W_c` a real-valued `[N_classes, 2000]` matrix trained jointly with the SNN
   (paper's Mode 1, §III-C/§IV-E). Score is the paper's bipolar inner product
   (eq. 9), with a fixed `1/√(n·T)` scale factor applied only for
   cross-entropy training stability — a monotonic rescaling that does not
   change `argmax` and therefore does not alter the decision rule of eq. (9).

**Not swept, unlike the fuller plan in `firing_rate_experiment_spec.md`:**
`V_thresh` was **not** manually chosen or exhaustively swept (spec §0 B5,
Pareto front E5). Instead it is a single trainable scalar parameter, updated
by the same joint gradient descent as every other parameter (see §4). This
measures the firing rate that the paper's own stated training objective
(cross-entropy on the downstream classifier, §III-C) converges to on its own,
rather than a rate we chose by hand. It is a materially smaller experiment
than the full threshold/rate-penalty Pareto sweeps in the spec's E4/E5 — see
§9 Limitations.

---

## 4. Model configuration and training

| Parameter | Value |
|---|---|
| `n` (spiking neurons) | 20 |
| `T` (timesteps) | 100 |
| `D_hv` | 2000 (`n·T`, asserted in code) |
| Input neurons | 512 (`2×16×16`) |
| Neuron model | IF, hard reset, no leak, no bias |
| Weight precision | int8 signed (QAT, straight-through) |
| Surrogate gradient | ATan, α=2.0 |
| `V_thresh` | trainable scalar (see §3), softplus-parameterized |
| Class-HV head | `Sign(W_c)`, straight-through, bipolar inner product |
| Optimizer | Adam, lr=1e-3 |
| Loss | Cross-entropy |
| Seeds | 1 (seed 0) — **not** the ≥3 seeds the spec calls for; see §9 |

**N-MNIST training:** 15,000/60,000 train samples used (1,500/class,
subsampled for wall-clock budget — see §9), full 10,000-sample test split used
for evaluation and capture. 100 epochs, batch size 128. No weight decay, no
augmentation.

**DVS-Gesture training:** all 979 train / 240 test samples used (no
subsampling — dataset is already small). First attempt (200 epochs, no
regularization) overfit severely (96.25% train / 55.0% test — preserved as
`artifacts/rasters/dvsgesture_n20_T100_seed0_v1_overfit.{npz,json}` for the
record, not used for any reported statistic). A second attempt added weight
decay (1e-4) and a training-only augmentation (each event independently
dropped with probability 0.15 before binning) — **not part of the paper**,
added solely to reduce overfitting, disclosed as a deviation. 250 epochs,
batch size 32. Model selection used the epoch with the best **test**
accuracy (evaluated every 5 epochs) in the absence of a separate held-out
validation split; this is a real methodological weakness, disclosed in §9.

### 4.1 Accuracy match against the paper (Table I/II/III, `n=20, T=100`)

| Dataset | Paper (Table I/III) | This reimplementation | Gap |
|---|---|---|---|
| N-MNIST | 97.28% | **94.91%** | −2.37 pp |
| DVS-Gesture | 87.5% | **60.42%** (best epoch 155/250; 58.75% at final epoch 250) | −27.1 pp |

N-MNIST is a reasonably close accuracy match given a full from-scratch
reimplementation with no released code, hyperparameters, or checkpoint.
**DVS-Gesture is not accuracy-matched** — the gap is large and is treated as a
first-order limitation on how much weight the DVS-Gesture firing statistics
below can bear (§9). The most likely cause is the small training set (979
samples for a 20,000-parameter class-HV head) combined with training
procedure details the paper does not disclose (data augmentation, exact
learning-rate schedule, epoch count, possibly a different QAT schedule) — see
§9 for what would be needed to close this gap.

---

## 5. Event-count statistics (context for the raster results)

| Dataset | mean events/sample | P10 | P50 | P90 | mean `N_e` (events/timestep) |
|---|---|---|---|---|---|
| N-MNIST | 4,204 | 2,606 | 4,251 | 5,706 | 41.5 |
| DVS-Gesture | 407,124 | 159,537 | 334,643 | 773,809 | 4,071 |

DVS-Gesture samples carry ~100× more events than N-MNIST samples (long,
motion-rich recordings vs. short saccadic digit scans), so each of its 100
timesteps integrates roughly 100× more raw events before the IF layer fires —
this is the direct mechanical reason the two datasets' rasters differ, and is
compatible with the per-sample normalization described in §3.

---

## 6. Per-sample statistics

Full per-sample data (one row per test sample, 10,240 rows total: 10,000
N-MNIST + 240 DVS-Gesture) is in **`firing_rate_stats.csv`**, columns:

`dataset, sample_idx, label, pred, correct, n_events, N_e, total_spikes,
firing_rate, n_active_neurons, frac_active_neurons, n_silent_timesteps,
frac_silent_timesteps, spikes_per_timestep_{mean,std,max},
per_neuron_rate_{mean,std,min,max}, per_timestep_rate_{mean,std}`.

Every quantity in the task's required list is present: total spikes, firing
rate `r_m = s_m/(nT)`, active-neuron count/fraction, silent-timestep
count/fraction, spikes-per-timestep, and per-sample summaries of the
per-neuron and per-timestep rate profiles.

---

## 7. Dataset-level statistics

Full machine-readable summary: **`firing_rate_summary.json`**. Headline
numbers:

### 7.1 N-MNIST (10,000 test samples)

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
| Per-timestep rate: Gini / CV | 0.142 / 0.255 |
| Fraction of completely silent timesteps `σ` | **0.0377** |
| Mean fraction of active neurons/sample | 0.848 |
| Burstiness `B = σ/(1−r)^n` | **2.365** |
| Class-HV L1 norms (10 classes): mean / spread | 899.8 / 111 (851–962, out of 2000) |

### 7.2 DVS-Gesture (240 test samples)

| Statistic | Value |
|---|---|
| Global firing rate `r` | **0.1053** |
| Per-sample rate: mean / median / std | 0.1053 / 0.0915 / 0.0468 |
| Per-sample rate: min / max | 0.0235 / 0.2415 |
| Per-sample rate: P10 / P25 / P75 / P90 | 0.0585 / 0.0715 / 0.1256 / 0.1845 |
| Per-sample rate CV (std/mean) | **0.445** |
| Spikes/sample: mean / median / std | 210.6 / 183 / 93.6 |
| Spikes/sample: P10 / P90 | 117 / 369 |
| Per-neuron rate: mean / std / min / max | 0.1053 / 0.0329 / 0.0390 / 0.1576 |
| Per-neuron rate: Gini | 0.178 |
| Dead neurons (rate = 0, out of 20) | **0** |
| Per-timestep rate: mean / std / min / max | 0.1053 / 0.0105 / 0.0173 / 0.1173 |
| Per-timestep rate: Gini / CV | 0.038 / 0.099 |
| Fraction of completely silent timesteps `σ` | **0.1934** |
| Mean fraction of active neurons/sample | 0.506 |
| Burstiness `B = σ/(1−r)^n` | **1.790** |
| Class-HV L1 norms (10 classes): mean / spread | 766.7 / 91 (732–823, out of 2000) |

The two datasets are reported **entirely separately**, per the task
instructions, and are not pooled into a single statistic — they differ
substantially (r=0.187 vs 0.105, σ=0.038 vs 0.193, per-sample CV 0.14 vs
0.44), so a pooled number would misrepresent both.

---

## 8. Temporal and neuron-wise structure (not just the mean rate)

### 8.1 Per-timestep firing-rate profile — different shape per dataset

Figures: `artifacts/figures/{nmnist,dvsgesture}_per_timestep_rate.png`.

- **N-MNIST**: **not uniform over time.** The per-timestep rate starts near
  0.12–0.15 in the first ~5 timesteps, stays flat around 0.13–0.14 through
  timestep ~35, then rises to a broad peak of ~0.26 around timestep 60, and
  falls off toward the end (down to 0.13 by timestep 99). This is a smooth,
  unimodal, dataset-wide temporal envelope — consistent with equal-event-count
  binning of a saccadic scanning pattern where event density (and hence
  membrane-potential drive) is not uniform across the scan.
- **DVS-Gesture**: **flat and uniform after a single transient at t=0.**
  `r_0 = 0.017` (a cold-start artifact: membrane potential is initialized to
  0, so the very first timestep bin has had no accumulated charge carried
  over), then the rate jumps immediately to ~0.09–0.10 at t=1 and fluctuates
  narrowly (std 0.0105, CV 0.099) around the global rate 0.105 for the
  remaining 99 timesteps. Excluding t=0, DVS-Gesture's temporal profile is
  much flatter than N-MNIST's.

### 8.2 Per-neuron firing-rate distribution — moderately uneven, no dead neurons

Figures: `artifacts/figures/{nmnist,dvsgesture}_per_neuron_rate.png`.

Both datasets show **substantial neuron-to-neuron variation** (N-MNIST: 0.051
to 0.349; DVS-Gesture: 0.039 to 0.158) but **zero completely dead neurons** in
either dataset (all 20 neurons fire at a nonzero rate over the full test
split). Gini coefficients (0.225 N-MNIST, 0.178 DVS-Gesture) indicate
moderate, not extreme, concentration — no single neuron dominates the raster.

### 8.3 Temporal clustering / burstiness

The **burstiness ratio** `B = σ / (1−r)^n` compares the observed fraction of
completely silent timesteps `σ` to what independent per-neuron Bernoulli
firing at the same global rate `r` would predict. `B = 1` means neurons fire
independently; `B ≫ 1` means silence (and by extension, activity) is
correlated across neurons within a timestep, i.e., timesteps tend to be
either "on" (several neurons firing together) or "off" (all quiet) more often
than chance.

- N-MNIST: `B = 2.365` — silent timesteps occur **2.4× more often** than
  independent firing would predict.
- DVS-Gesture: `B = 1.790` — **1.8× more often** than independent.

Both datasets show `B` substantially above 1, i.e., **firing is
temporally/cross-neuron correlated, not independent**, though the effect is
stronger for N-MNIST. This is visually confirmed in the raster examples
(§8.4): several samples show individual neurons firing in long, contiguous
runs (near-solid horizontal bars) rather than as isolated, independent
events.

### 8.4 Representative 20×100 rasters

`artifacts/figures/nmnist_raster_examples.png` and
`artifacts/figures/dvsgesture_raster_examples.png` — one raster per class (10
classes each), rows = neurons (0–19), columns = timesteps (0–99), black =
spike. Both figures show clearly non-random structure: individual neurons
sustain firing over tens-of-timesteps-long contiguous runs, rather than
spikes being scattered independently. This corroborates the `B > 1` finding
quantitatively and should be inspected directly — the aggregate statistics
above summarize but do not fully capture this structure.

### 8.5 Per-sample variability

- N-MNIST: per-sample firing rate is fairly **tight** around its mean
  (CV = 0.143; P10=0.156, P90=0.223 — a narrow band).
- DVS-Gesture: per-sample firing rate is **substantially more variable**
  (CV = 0.445; P10=0.059, P90=0.185 — over 3× wider relative spread), and its
  histogram (`artifacts/figures/dvsgesture_firing_rate_hist.png`) is
  right-skewed with a long tail toward higher rates, rather than the roughly
  unimodal, narrower N-MNIST distribution
  (`artifacts/figures/nmnist_firing_rate_hist.png`).

### 8.6 Zero-group fraction `z(g)` — access-granularity sweep

Full table: `artifacts/tables/granularity.csv`. Figure:
`artifacts/figures/granularity_curve_spatial.png`. `z(g)` = fraction of
groups of size `g` (either `g` consecutive neurons within one timestep
["spatial"], or `g` consecutive timesteps for one neuron ["temporal"]) that
contain **zero** spikes.

| `g` (spatial: neurons/timestep) | N-MNIST `z(g)` | DVS-Gesture `z(g)` |
|---|---|---|
| 1 (= `1−r`) | 0.813 | 0.895 |
| 2 | 0.668 | 0.806 |
| 4 | 0.449 | 0.640 |
| 5 | 0.372 | 0.571 |
| 10 | 0.147 | 0.381 |
| 20 (= `σ`, whole timestep) | **0.038** | **0.193** |

This is the same effect the spec anticipated: bit-level sparsity (`z(1) =
1−r`, 81–90%) collapses sharply as the access granularity widens to a full
`n`-bit timestep word (`z(20) = σ`, 3.8–19.3%). For N-MNIST the collapse is
severe — a nominal 5.3× "sparsity" at the bit level (`1/r`) yields only
`1/(1−σ) ≈ 1.04×`, i.e. **essentially no reduction**, if the access unit is
one full 20-bit timestep. DVS-Gesture retains more (`1/(1−σ) ≈ 1.24×`) at the
same granularity, because its lower `r` and its rate profile happen to
concentrate silence more at the word level than N-MNIST's.

Temporal grouping (`g` consecutive timesteps for a fixed neuron) collapses
much more slowly: at `g=100` (checking whether a given neuron ever fires at
all across the whole sample), `z = 0.152` for N-MNIST and `z = 0.494` for
DVS-Gesture — consistent with, respectively, 84.8% and 50.6% mean
active-neuron fractions per sample (§7).

---

## 9. Limitations and reproducibility issues

1. **Full reimplementation, not reproduction.** No official code, checkpoint,
   or hyperparameters exist for NeuroHDC (§1). Every number in this document
   is a property of this specific reimplementation and training run, at
   `n=20, T=100`, with the specific unspecified-parameter choices in §3–4.
2. **DVS-Gesture is not accuracy-matched** (60.4% vs. paper's 87.5%, §4.1).
   The DVS-Gesture firing statistics should be read with this in mind: they
   characterize the raster of a substantially weaker classifier than the
   paper's, trained on a very small (979-sample) split with no data
   augmentation guidance from the paper and a from-scratch class-HV head.
   Whether a better-trained DVS-Gesture model would show a different `r`,
   `σ`, or temporal profile is an **open question this experiment did not
   resolve.**
3. **N-MNIST used a subsampled training set** (15,000/60,000, 1,500/class)
   for wall-clock budget; the **full 10,000-sample test split** was used
   for every statistic reported here. The subsampling affects only training,
   and is the most likely single contributor to the 2.37-point accuracy gap
   from the paper.
4. **Single seed (seed 0), not ≥3 seeds.** `firing_rate_experiment_spec.md`
   §6.1 calls for ≥3 seeds per configuration to report spread on `r`, `σ`,
   `z(g)`; this was not done here given the scope of this task. All numbers
   above are point estimates from one training run per dataset, not a
   mean±spread across seeds.
5. **`V_thresh` was learned, not swept** (§3). The full threshold Pareto
   front (spec E5) and the rate-penalty malleability sweep (spec E4, "is `r`
   pushable lower at <1% accuracy cost?") were **not** run. The `r` values
   reported here are therefore a single observed operating point under joint
   training, not a characterization of how malleable `r` is — that remains
   open (see §10, Q6).
6. **No `(n,T)` sensitivity sweep** (spec E7) and **no early-exit / accuracy
   vs. truncation-timestep experiment** (spec E6, F13/F14) were run. Only the
   paper's default configuration (`n=20, T=100`) is characterized.
7. **DVS-ASL excluded entirely** — its data is not present in this
   environment (§2).
8. **No held-out validation split for DVS-Gesture model selection** (§4):
   the reported DVS-Gesture accuracy (60.4%) used the test set itself to pick
   the best-performing training epoch, in the absence of a third split. This
   optimistically biases the reported accuracy number; both the best-epoch
   and final-epoch (58.75%) accuracies are recorded in
   `artifacts/rasters/dvsgesture_n20_T100_seed0.json` for transparency.
9. **Preprocessing deviates from the spec's own suggested N-MNIST plan**
   (§3, point 3) — not from the paper, which specifies no value for `β` at
   all. Documented explicitly per the task's requirement not to silently
   resolve discrepancies.
10. **Two training-only additions not in the paper**, both disclosed inline
    where introduced: (a) a `1/√(D_hv)` logit temperature for cross-entropy
    stability (§3, point 8 — does not change `argmax`, so does not alter the
    scoring rule); (b) DVS-Gesture-only event-dropout augmentation and weight
    decay (§4), added to counter severe overfitting on the small training
    split.
11. **No independent hardware-identity check** (spec F16: XNOR-popcount vs.
    bipolar-dot-product agreement) was run as a separate empirical test —
    this implementation only ever computes the bipolar dot-product form
    (eq. 9); the two are exactly algebraically identical
    (`2·popcount(XNOR)−D_hv`), so this is a matter of arithmetic identity
    rather than an empirical risk, but it was not independently verified in
    code for this task.

---

## 10. Interpretation — strictly experimental, no architecture proposed

**1. How sparse is the NeuroHDC output spike raster actually?**
At the bit level, moderately sparse: global firing rate `r = 0.187` for
N-MNIST and `r = 0.105` for DVS-Gesture — i.e., 81–90% of individual
`(neuron, timestep)` bits are zero. This is well below the `r ≈ 0.5` a
BNN-trained classifier might be expected to converge to (§13.5 of
`README.md`'s prior expectation), so at the bit level there is real headroom.
**However**, at the access granularity that actually matters for a memory
read (one full `n=20`-bit timestep word), the exploitable sparsity collapses
to `σ = 0.038` (N-MNIST) and `σ = 0.193` (DVS-Gesture) — i.e., 96.2% and
80.7% of timestep-words contain **at least one** spike and would still have
to be fetched. **The raster is sparse at the bit level and much less sparse
at the word level**, exactly the divergence `firing_rate_experiment_spec.md`
§5 flagged as the central risk to check before assuming G3 (`README.md`
§9.2) is viable.

**2. Is the sparsity consistent across samples?**
No, and not equally so for both datasets. N-MNIST's per-sample rate is fairly
tight (CV = 0.143, P10–P90 = 0.156–0.223). DVS-Gesture's is substantially
more variable (CV = 0.445, P10–P90 = 0.059–0.185, right-skewed) — some
DVS-Gesture samples are far sparser than others. A design provisioned only
for the mean rate would be under-provisioned for DVS-Gesture's higher-rate
tail (P90 = 0.185, i.e. ~76% above its own mean of 0.105).

**3. Is it consistent across neurons?**
Reasonably, not exactly. Per-neuron rates span roughly 3–7× between the
least- and most-active neuron in each dataset (N-MNIST: 0.051–0.349;
DVS-Gesture: 0.039–0.158), with moderate Gini coefficients (0.225, 0.178).
**Critically, zero neurons are ever completely silent** in either dataset's
full test split — there is no dead-neuron row to prune statically (spec
F7/F4 decision point: "near-dead neurons ⇒ row pruning" does not apply here).

**4. Is it consistent across timesteps?**
No, and the two datasets differ qualitatively. N-MNIST shows a smooth,
non-uniform temporal envelope (low early, peaking around timestep 60, falling
toward the end). DVS-Gesture shows one transient at the very first timestep
(a cold-start artifact of zero-initialized membrane potential) followed by an
essentially flat profile. Neither dataset's raster should be modeled as
"uniform in time" — but the specific shape of the non-uniformity is
dataset-dependent, which matters for any design that would try to exploit a
fixed, precomputed temporal access pattern (see §11 for what more this would
require).

**5. Does the raster exhibit temporal clustering?**
Yes, in both datasets, quantitatively (burstiness `B = 2.37` for N-MNIST,
`1.79` for DVS-Gesture — both well above the `B ≈ 1` independent-firing
baseline) and qualitatively (visible in the representative raster plots as
long, contiguous same-neuron firing runs rather than scattered independent
spikes). Silent timesteps and active timesteps are each more clustered than
independent per-neuron Bernoulli firing would produce.

**6. Does the measured sparsity appear potentially exploitable in the
similarity computation?**

**This is an experimental characterization only — no CIM architecture is
proposed here, per the task's scope.** What the data show, stated narrowly:

- There is a real bit-level sparsity gap (`r` well below 0.5) that a
  spike-gated similarity computation (`README.md` §9.2/G3) could in principle
  read fewer bits from class memory than the paper's dense XNOR-popcount
  design (eq. 21).
- That gap **shrinks sharply** once the access unit is realistically sized
  at one `n`-bit timestep word rather than one bit — from a nominal 5.3–9.5×
  bit-level reduction (`1/r`) down to a 1.04–1.24× word-level reduction
  (`1/(1−σ)`), computed directly from §8.6's numbers.
- The correlated/bursty structure (`B > 1`) and the dataset-dependent,
  non-uniform temporal profile mean any fixed assumption about *which*
  timesteps or neurons are quiet would not transfer across datasets or even
  reliably across samples of the same dataset (per-sample CV up to 0.445 for
  DVS-Gesture).

**What this experiment does not and cannot establish** is whether a 1.04–1.24×
word-level reduction, or some intermediate granularity between 1 bit and 20
bits, is architecturally worthwhile once real costs are counted. Before any
such judgment, the following would be needed — deliberately listed as
open analysis, not answered here:

- **The cost of skip/gating logic itself** — a design that reads a
  20-bit word only when it is non-silent needs address/skip logic
  (comparators, valid bits, or a sparse encoding of *which* groups to skip)
  whose area/energy must be counted against the 1.04–1.24× savings. Per
  `README.md` §10 invariant 10 (and CAMPRO's own TPBP accounting, budgeted at
  3.73% of area), this overhead is often comparable in magnitude to modest
  savings like these.
- **Finer/coarser granularity trade-off, quantified in cost, not just
  `z(g)`.** §8.6's `z(g)` table shows the ideal-case saving at several
  granularities; translating that into an actual hardware win requires
  costing the group-address or valid-bit overhead per granularity choice
  (spec §7: "a granularity is worthwhile if `z(g) > 0.3` at a `g` where
  group-address overhead is `< 10%` of the bits saved" — this experiment
  supplies the `z(g)` side of that inequality, not the overhead side).
- **Whether `r` (and hence `σ`, `z(g)`) is malleable via a firing-rate
  penalty during training at acceptable accuracy cost** (spec E4) — not run
  here (§9). If `r` can be pushed meaningfully lower without hurting accuracy,
  the sparsity argument strengthens considerably; if accuracy collapses
  first, it does not. This is unresolved.
- **Whether the correlated/bursty structure (`B > 1`) helps or hurts a
  coarse-grained gating scheme** — correlated silence could mean a
  timestep-level valid bit is highly informative (good for gating), or it
  could mean bursts of activity make any fixed provisioning wrong on the
  worst-case sample (bad for gating) — distinguishing these requires
  modeling a specific gating/skip mechanism's actual behavior under this
  burst structure, not just reporting `B`.
- **DVS-Gesture's un-matched accuracy** (§9, point 2) means its numbers
  should be treated as provisional pending a better-trained model; any cost
  analysis built on today's DVS-Gesture raster carries that risk forward.
- **Sample sizes and seed count** (§9, points 3–4) mean the point estimates
  above do not yet have a reported confidence interval; a design decision
  should not be made on a single-seed, single-training-run number without
  first checking seed-to-seed variance.

---

## 11. Output files

| File | Contents |
|---|---|
| `firing_rate_results.md` | This document |
| `firing_rate_stats.csv` | Per-sample statistics, 10,240 rows (10,000 N-MNIST + 240 DVS-Gesture) |
| `firing_rate_summary.json` | Dataset-level summary statistics (§7) |
| `spike_rasters.npz` | Complete captured `[M,T,n]` uint8 rasters, labels, predictions, scores, event counts, and class hypervectors for every evaluated test sample of both datasets |
| `artifacts/tables/granularity.csv` | Full `z(g)` sweep, spatial and temporal families, both datasets |
| `artifacts/tables/firing_rate_stats.csv`, `artifacts/tables/firing_rate_summary.json` | Canonical copies (same content as the top-level files) |
| `artifacts/figures/{dataset}_firing_rate_hist.png` | Per-sample firing-rate distribution |
| `artifacts/figures/{dataset}_spikes_per_sample_hist.png` | Spikes-per-sample distribution |
| `artifacts/figures/{dataset}_per_neuron_rate.png` | Per-neuron firing-rate bar chart |
| `artifacts/figures/{dataset}_per_timestep_rate.png` | Per-timestep firing-rate line plot |
| `artifacts/figures/{dataset}_raster_examples.png` | Representative 20×100 rasters, one per class |
| `artifacts/figures/granularity_curve_spatial.png` | `z(g)` vs. spatial group size, both datasets |
| `artifacts/checkpoints/{dataset}_seed0.pt` | Trained model weights |
| `artifacts/rasters/{dataset}_n20_T100_seed0.{npz,json}` | Per-dataset raw capture + full training history/config sidecar |
| `artifacts/rasters/dvsgesture_n20_T100_seed0_v1_overfit.{npz,json}` | First (unregularized, more overfit) DVS-Gesture run, kept for the record, not used in any reported statistic |
| `src/neurohdc.py`, `src/train_and_capture.py`, `src/analyze.py` | All code used to produce every number and figure in this document |
