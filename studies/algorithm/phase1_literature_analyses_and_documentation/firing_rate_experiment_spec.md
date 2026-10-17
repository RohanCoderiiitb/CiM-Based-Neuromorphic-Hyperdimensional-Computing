# Firing-Rate Experiment Specification

**Target:** measure the output spike raster `S ∈ {0,1}^{n×T}` = `{0,1}^{20×100}` of NeuroHDC.

**Question being answered:** is the raster sparse enough, at an exploitable access granularity, to justify an event-driven / sparsity-exploiting CIM query path?

**Scope:** measurement only. **Do not design or propose a CIM architecture in this phase.**

**Status of every number in this document: `[E]` — not yet measured.**

---

## 0. Blockers — obtain before writing code

| # | Blocker | Status | Action |
|---|---|---|---|
| **B1** | Official NeuroHDC code | **Does not exist.** Searched GitHub (title, all six author names, NUAA group), Gitee, OpenI, Weiqiang Liu's NUAA faculty pages, and the TVLSI paper itself. No repo link, no data-availability statement, no footnote. | Full reimplementation. Budget ~2 weeks. |
| **B2** | Pretrained checkpoints | **Do not exist.** | Train from scratch (E1). |
| **B3** | Predecessor code (Spiking-HDC ISCAS'24, HyperSpikeASIC TCAD'23) | **Not released.** | Not usable as scaffolding. |
| **B4** | NeuroHDC **Tables I, II, III** | **Missing from our text extraction.** Table II holds the per-dataset accuracy targets; Table III holds the "small"/"large" hardware configs; Table I holds the timestep-scaling data. | **Re-extract from the PDF before E1.** Without Table II there is no accuracy-match target and the whole experiment is uncalibrated. |
| **B5** | `V_thresh` | **Never stated in the paper.** Exposed only as a config register (§V-A). Directly controls firing rate. | Sweep (E5). Report `r` at the accuracy-matched threshold. |
| **B6** | Input scaling of the SumPooled count image | **Never stated.** A count image is unbounded; raw vs normalised vs clipped changes the drive and hence `r`. | Sweep `{raw, per_sample_norm, clip}`; pick what reproduces accuracy. |
| **B7** | `β` resize factor per dataset | Stated to exist, value never given ("determined by the specific dataset", §V-B). | Derive from sensor resolution → `2×16×16`. Document. |
| **B8** | LR, batch size, epochs, weight decay, surrogate function/width | Not stated. | Standard defaults; document; validate by accuracy match. |
| **B9** | DVS-Gesture raw archive | IBM download requires manual acceptance. | Download before E1. |
| **B10** | ASL-DVS | `tonic.datasets.ASLDVS`, or Dropbox/Drive links in github.com/PIX2NVS/NVS2Graph. ~100,800 samples. | Download; plan disk (~50 GB raw). |

**Do not start E1 until B4 is resolved.**

---

## 1. Datasets and configurations

### Datasets (all three; `r` is expected to differ per dataset)

| Dataset | Source | Classes | Sensor res. | `β` (B7) |
|---|---|---|---|---|
| N-MNIST | `spikingjelly.datasets.n_mnist.NMNIST` / `tonic.datasets.NMNIST` | 10 | 34×34 | crop/pad to 32×32, `β = 2` |
| DVS-Gesture | `spikingjelly.datasets.dvs128_gesture.DVS128Gesture` | **10** (exclude class 11 "Other", per §IV-A) | 128×128 | `β = 8` |
| ASL-DVS | `tonic.datasets.ASLDVS` | 24 | 240×180 | centre-crop to 128×128, then `β = 8`; document the crop |

### Configurations

| Sweep | Grid | Purpose |
|---|---|---|
| **Primary** | `n=20, T=100` | The paper's default. **All headline numbers come from here.** |
| `(n,T)` sensitivity | `(10,200), (20,100), (25,80), (40,50), (50,40)` at fixed `D_hv=2000`; plus `T ∈ {100,150,200}` at `n=20` | Reproduces NeuroHDC Fig. 3 / Table I **and** reports `r` at each point. Validates our model behaves like theirs. |
| `V_thresh` | ≥5 values spanning roughly 0.25×–4× a calibrated reference | B5. Pareto of accuracy vs `r`. |
| Rate penalty `λ` | `{0, 1e-4, 1e-3, 1e-2, 1e-1}` | Is `r` malleable? (§6.2) |
| Seeds | ≥3 per configuration | Prevents single-seed conclusions. |

---

## 2. Model configuration (faithful reproduction)

```yaml
# configs/base.yaml
snn:
  topology: single_layer_fc      # §III-B
  n_input: 512                   # 2 × 16 × 16, §IV-A
  n_neurons: 20                  # §IV-B1
  neuron: IF                     # §II-A — IF, NOT LIF
  v_reset: 0.0                   # §II-A eq.(1)
  reset_mode: hard               # V(t) = Vp(t)(1-S) + Vreset·S
  leak: none
  bias: false                    # eq.(16): X(t) = Ws · D_flat(t)^T
  v_thresh: TBD                  # B5 — sweep
  w_bits: 8                      # signed int8 via QAT, §III-C
  surrogate: atan                # B8; ref [35] Neftci
  surrogate_alpha: 2.0

encoding:
  method: concat                 # eq.(7) — flatten only, nothing else
  T: 100                         # §IV-A
  D_hv: 2000                     # assert == n * T
  polarity: unipolar             # hardware form, §III-A

head:
  type: binary_fc                # eq.(10): Score = Sign(Wc) · h^T
  sign_backward: ste

data:
  binning: equal_event_count     # §III-B — NOT equal time
  pool: sum                      # §III-B SumPool; avg_pool2d(x,β)*β²
  beta: TBD                      # B7
  input_scaling: TBD             # B6 — {raw, per_sample_norm, clip}
  short_sample_policy: pad_empty # B8; log how many samples affected

train:
  optimizer: adam                # §IV-A
  loss: cross_entropy            # §III-C
  quantization: qat_int8         # §III-C, ref [36]
  lambda_rate: 0.0               # rate penalty, default off
```

### Hard invariants — assert in code, fail loudly

1. `D_hv == n * T`.
2. **Nothing sits between the raster and the classifier head except a flatten.** No pooling, no rate accumulation, no normalisation, no permutation, no binding. If anything else appears, we are no longer measuring NeuroHDC.
3. Binning is by event count, not wall-clock time.
4. SumPool is a **sum** — assert total event count is conserved.
5. Neuron is IF with hard reset; no leak; no bias.

---

## 3. Where to capture the raster

**Exactly one capture point:** the output of the IF layer, before flattening.

```python
# src/neurohdc/model.py
class NeuroHDC(nn.Module):
    def forward(self, frames):                 # frames: [B, T, 512] int32/float
        raster = self.if_layer(frames)         # [B, T, n] {0,1}   <-- CAPTURE HERE
        assert raster.dtype in (torch.bool, torch.uint8) or set(raster.unique().tolist()) <= {0.0, 1.0}
        h = raster.flatten(1).float()          # [B, n*T]  — flatten ONLY
        assert h.shape[1] == self.n * self.T
        scores = h @ torch.sign(self.Wc).t()   # [B, N]
        return scores, raster
```

Inside `IFLayer.forward`, the raster is the sequence of `Θ(V_p(t) − V_thresh)` outputs, collected over `t = 0 … T−1`, **after** the threshold and **before** the reset is applied to `V`.

Capture during **inference on the test split only**, with the model in `eval()` and `torch.no_grad()`.

Also capture, in the same pass: `class_hv = sign(Wc) > 0` reshaped to `[N, T, n]`, and `class_l1 = class_hv.sum((1,2))`.

### Artifact format

`artifacts/rasters/{dataset}_{config_hash}_seed{s}.npz`:

| Key | dtype | shape |
|---|---|---|
| `raster` | uint8 | `[M, T, n]` |
| `labels` | int16 | `[M]` |
| `pred` | int16 | `[M]` |
| `scores` | float32 | `[M, N]` |
| `n_events` | int32 | `[M]` |
| `N_e` | int32 | `[M]` |
| `class_hv` | uint8 | `[N, T, n]` |
| `class_l1` | int32 | `[N]` |

Sidecar `.json`: dataset, split, `n`, `T`, `β`, `v_thresh`, `input_scaling`, `lambda_rate`, seed, git SHA, config hash, test accuracy, package versions, subsample size if the test split was subsampled.

---

## 4. Statistics

Let `S ∈ {0,1}^{M×T×n}`, `k_{m,t} = Σ_j S[m,t,j]`.

| ID | Statistic | Definition |
|---|---|---|
| F1 | Global firing rate | `r = (1/(M·T·n)) Σ S` |
| F2 | Spikes per sample | `s_m = Σ_{t,j} S[m,t,j]` → mean, std, **P10, P50, P90**, P99, min, max |
| F3 | Firing rate per sample | `r_m = s_m/(n·T)` → mean, median, **P10, P50, P90**, P99 + histogram |
| F4 | Per-neuron firing rate | `r_j = (1/(M·T)) Σ_{m,t} S[m,t,j]`, for `j = 1…20` |
| F5 | Per-timestep firing rate | `r_t = (1/(M·n)) Σ_{m,j} S[m,t,j]`, for `t = 1…100` |
| F6 | **Silent-timestep fraction** | `σ = (1/(M·T)) Σ_{m,t} 1[k_{m,t} = 0]` |
| F7 | Active-neuron fraction | per sample `a_m = (1/n) Σ_j 1[Σ_t S[m,t,j] > 0]`; plus globally-dead neuron count |
| F8 | `k_t` distribution | histogram of `k_{m,t}` over all `(m,t)`; mean, mode, max |
| F9 | **Burstiness ratio** | `B = σ / (1−r)^n` — observed silence vs. independent-Bernoulli prediction |
| F10 | Silent-run lengths | distribution of maximal runs of consecutive silent timesteps |
| F11 | **Zero-group fraction `z(g)`** | fraction of groups with no spike — see §5 |
| F12 | Class-HV norms | `‖C_i‖₁` per class; mean, spread, `max − min` |
| F13 | Event statistics | `n_events` and derived `N_e` per sample: mean, P10/P50/P90 |
| F14 | **Identity check** | argmax agreement between `Σ_m XNOR(h,C_i)` and `2(h·C_i) − ‖C_i‖₁`. **Must be 100%.** |

Report every statistic **separately per dataset, per configuration, per seed** (§6.1).

---

## 5. The zero-group sweep — F11, the headline measurement

**Why this and not `r`:** memory is not bit-addressable for free. If the class-hypervector memory is read at word granularity (`g = n = 20` bits per timestep), a timestep containing even one spike must still be fetched — so the achievable saving is `σ` (F6), not `1 − r` (F1). These diverge violently:

> At `r = 0.2` with independent neurons, `σ = 0.8²⁰ ≈ 1.2%`. A nominal 5× reduction in the bits that matter yields essentially **zero** saving at word granularity.

**Definition.** Partition the `T × n` raster into groups of size `g`. `z(g)` = fraction of groups containing no spike. Ideal access reduction at that granularity = `z(g)`.

**Three grouping families:**

| Family | Grouping | `g` grid |
|---|---|---|
| Spatial | `g` consecutive neurons within one timestep | `1, 2, 4, 5, 10, 20` |
| Temporal | `g` consecutive timesteps for one neuron | `1, 2, 4, 5, 10, 20, 25, 50, 100` |
| 2D tile | `g_j × g_t` | `g_j ∈ {1,2,4,5,10,20}` × `g_t ∈ {1,2,5,10,25}` |

Note `z(1) = 1 − r` and `z(g=n, spatial) = σ`, so F1 and F6 are the two endpoints of the spatial curve. **Output `granularity.csv` and `granularity_curve.pdf`. This is the table the architecture decision rests on.**

---

## 6. Measurement protocol

### 6.1 Per-dataset and per-configuration — yes, always

`r` is **not** a property of NeuroHDC; it is a property of `(dataset, n, T, V_thresh, β, input_scaling, λ, seed)`. Measuring it once and generalising would be the central methodological error of this phase.

- **Per dataset:** mandatory. Event density, class count, and temporal structure all differ. DVS-Gesture is long and motion-rich; ASL-DVS is ~100 ms static handshapes; N-MNIST is saccadic. Expect materially different rasters.
- **Per `(n,T)`:** mandatory. `n` and `T` change both the raster shape and the drive per timestep (since `N_e` changes with `T`).
- **Per `V_thresh`, `input_scaling`, `λ`:** mandatory — these are the knobs that *set* `r`.
- **Per seed:** ≥3. Report mean ± spread on `r`, `σ`, `z(g)`.

**Reporting rule:** quote `r` only at an **accuracy-matched** operating point (within ~1% of NeuroHDC Table II). A low `r` at degraded accuracy is not a result.

### 6.2 Malleability — the experiment that probably decides this

**Prior expectation, to be tested rather than assumed:** NeuroHDC's raster feeds a binary FC classifier trained with STE, and BNN training generally favours balanced activations. There is a real chance training settles near `r ≈ 0.5`. **Plan for that outcome.**

So also measure whether `r` can be *pushed down*: train with `L = L_CE + λ·r̄` (mean firing rate) across the `λ` grid, and produce the accuracy-vs-`r` Pareto front.

If `r` is malleable to a useful level at <1% accuracy cost, the sparsity direction survives even if the natural `r` is high. **Note explicitly in any write-up that spike-rate regularisation is standard SNN practice and is an enabler, not a contribution.**

---

## 7. Decision criteria

| Question | Statistic | Threshold |
|---|---|---|
| Is the identity valid at all? | **F14** | Must be **exactly** 100% argmax agreement. Any disagreement invalidates the premise outright — stop and re-derive. |
| Is there any exploitable sparsity? | **F1** `r` | `r < 0.35` → ≥1.5× ideal bit-level reduction. `r ∈ [0.35, 0.45]` → marginal. `r ≳ 0.45` → naive sparsity is **dead**; go to §6.2. |
| Does coarse gating work? | **F6** `σ`, **F9** `B` | `B ≫ 1` **and** `σ > 0.2` → word-level gating viable. `B ≈ 1` → neurons fire independently; only fine granularity helps. |
| **What granularity pays?** | **F11** `z(g)` | Report `z(g)` against the address/control overhead per fetched group. A granularity is worthwhile if `z(g) > 0.3` at a `g` where the group-address overhead is `< 10%` of the bits saved. **This is the decisive table.** |
| Can dense samples break the budget? | **F3** P90/P99 | If P90 `r_m` is ≫ mean, the design cannot be provisioned on the mean; report worst-case separately. |
| Static compression instead? | **F4**, **F7** | Near-dead neurons → row pruning. Cheaper, but a weaker and more incremental contribution — note it, don't celebrate it. |
| Does the bias term cost anything? | **F12** | Narrow `‖C_i‖₁` spread → the constant nearly cancels and folds in cheaply. |

### Verdict to produce

Phase 1 ends with a written verdict on exactly one of:

- **(a) Viable as-is** — `r` low **and** `z(g)` favourable at an affordable granularity.
- **(b) Viable with co-design** — §6.2 shows `r` is malleable to a useful level at acceptable accuracy cost.
- **(c) Dead** — `r ≈ 0.5`, `B ≈ 1`, and accuracy collapses when `r` is forced down. **If (c), say so plainly and return to the design space (README §9.3) to build on G2 / G5 / G6 instead.**

---

## 8. Deliverables

### Tables — `artifacts/tables/*.csv` + Markdown digest

1. `accuracy_match.csv` — our accuracy vs NeuroHDC Table II, per dataset
2. `firing_stats.csv` — F1–F10, F12, F13, per dataset × config × seed
3. **`granularity.csv`** — F11, all three families
4. `threshold_sweep.csv` — accuracy vs `r` Pareto over `V_thresh`
5. `rate_penalty_sweep.csv` — accuracy vs `r` Pareto over `λ`
6. `nt_sensitivity.csv` — Fig. 3 / Table I reproduction, plus `r` at each point
7. `identity_check.csv` — F14; must show zero disagreements

### Figures — `artifacts/figures/*.{pdf,png}`

1. **`raster_examples.pdf`** — raw `20×100` dot plots, 3–6 per dataset, one per class. **Look at these before trusting any aggregate.** Correlated or bursty structure is visible by eye long before F9 quantifies it.
2. `per_neuron_rate.pdf` — F4
3. `per_timestep_rate.pdf` — F5
4. `kt_histogram.pdf` — F8, overlaid with `Binomial(20, r)` to visualise F9
5. **`granularity_curve.pdf`** — `z(g)` vs `g`, all three families — **headline figure**
6. `sample_rate_hist.pdf` — F3 with P10/P50/P90/P99 marked
7. `accuracy_vs_rate.pdf` — threshold and `λ` Pareto fronts on shared axes
8. `class_l1.pdf` — F12

### Report

`artifacts/REPORT.md` — all tables, all figures, config hashes, seeds, git SHA, and a **Decision** section answering §7 in order and stating verdict (a), (b), or (c).

---

## 9. Repository layout

```
cim-neurohdc/
├── configs/            base.yaml, nmnist.yaml, dvsgesture.yaml, asldvs.yaml
├── src/neurohdc/
│   ├── config.py       dataclass config, YAML load, deterministic hash
│   ├── data.py         loaders, equal-event-count binning, SumPool
│   ├── neuron.py       IFLayer(n_in=512, n_out=20, v_thresh, w_bits=8)
│   ├── quant.py        int8 QAT STE; sign-STE
│   ├── model.py        NeuroHDC -> (scores, raster)
│   ├── train.py        Mode-1 joint training (+ optional rate penalty)
│   ├── capture.py      inference with raster capture -> npz + json
│   ├── stats.py        F1-F10, F12, F13
│   ├── granularity.py  F11
│   ├── identity.py     F14
│   └── plots.py
├── scripts/            00_prepare_data … 08_make_report
├── artifacts/          checkpoints/ rasters/ tables/ figures/ logs/
└── tests/
    ├── test_binning.py          every bin holds N_e events (± remainder)
    ├── test_sumpool.py          total event count conserved
    ├── test_if_neuron.py        hard reset, no leak, threshold semantics
    ├── test_encoder_shape.py    D_hv == n*T; flatten-only path
    ├── test_score_identity.py   F14 on synthetic random h, C — run first
    └── test_quant.py            int8 round-trip
```

### Key module contracts

- **`data.build_dataset(name, split, T, beta, cfg)`** → yields `(frames: int32 [T,2,16,16], label: int, n_events: int)`. Must use equal-event-count binning (SpikingJelly `split_by='number'`). Must return `N_e = n_events // T`.
- **`neuron.IFLayer.forward(frames: [B,T,512])`** → `raster: [B,T,20]`, optional `v_trace: [B,T,20]`.
- **`capture.capture(model, loader, out_path)`** → writes the `.npz` + `.json` of §3.
- **`granularity.zero_group_fraction(raster, family, g)`** → float, for `family ∈ {"spatial","temporal","2d"}`.
- **`identity.verify(raster, class_hv, class_l1)`** → asserts 100% argmax agreement; returns the exact disagreement count.

### Engineering requirements

- Seed everything; log seeds; ≥3 seeds for the primary config.
- Every artifact carries config hash + git SHA in its sidecar. No untraceable numbers.
- `test_score_identity.py` runs on synthetic random `h`, `C` **before** any real data is touched.
- Must run on CPU for the small sweeps; no hard CUDA dependency.
- ASL-DVS has ~100 k samples — subsample the test split if needed and **record the subsample size in the sidecar**.
