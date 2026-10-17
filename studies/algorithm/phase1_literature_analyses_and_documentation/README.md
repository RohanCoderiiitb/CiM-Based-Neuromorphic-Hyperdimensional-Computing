# CIM-NeuroHDC — Literature Analysis and Design-Space Reference

**Status:** Phase 0 — literature reconstruction and gap identification. **No architecture is proposed in this document.**

**Maintainer:** Rohan (IIITB)
**Last updated:** 2026-09-20

---

## Notation used throughout

Every non-trivial claim is tagged:

| Tag | Meaning |
|---|---|
| **[S]** | **Stated** explicitly in the cited paper (section/figure/equation given where possible) |
| **[I]** | **Inferred** — derived from the architecture/algorithm/equations the paper does state; internally consistent but not asserted word-for-word by the authors |
| **[G]** | **Gap / opportunity** — appears unaddressed by the surveyed literature; confidence level given |
| **[E]** | **Experimental** — a value the paper does not specify, which was measured, swept, or chosen and then measured; also used for experimentally-measured results generally (Phase 1 onward) |
| **[O]** | **Our implementation choice** — the paper gives no information to determine this at all (not even indirectly, unlike [I]); a specific value or technique we picked, disclosed as ours, never to be read as a paper claim (added in the DVS-Gesture accuracy-improvement pass, section 15) |

Confidence levels for **[G]**: `high` (searched directly, multiple query formulations, nothing found), `medium` (related work exists but differs materially), `low` (plausible but literature search was not exhaustive).

---

## 1. Project objective and research question

### 1.1 Objective

Identify a **genuinely novel architectural research direction** for implementing NeuroHDC on a Compute-in-Memory / Processing-in-Memory substrate, suitable as the central contribution of a VLSI/architecture paper.

### 1.2 Origin and constraint history

- The central paper is Yu et al., *"Neuromorphic Hyperdimensional Computing for Efficiently Processing Event-Based Data"* (NeuroHDC), IEEE TVLSI vol. 34 no. 8, Aug 2026, pp. 2483–2494.
- NeuroHDC §VI-D explicitly names **processing-in-sensor (PIS)** as future work. **[S]**
- PIS was **ruled out** by the advisor: it requires knowledge of and modification to the sensor circuitry and interface, which is not tractable for this group.
- The advisor redirected to **CIM/PIM**, specifically ReRAM/memristive crossbars *or another memory technology if better justified*.
- **Hard constraint from the advisor:** the contribution must be a *novel CIM architecture/dataflow specific to NeuroHDC*. NeuroHDC is the algorithmic foundation, **not** the contribution. Techniques already published must not be claimed as novel.

### 1.3 Research question

> Can the NeuroHDC architecture be *fundamentally restructured* so that its event-driven spatiotemporal spike representation is exploited **by** a CIM architecture — producing a design substantially more efficient than conventionally implementing NeuroHDC and then swapping some memory/compute blocks for CIM equivalents?

### 1.4 Explicitly disallowed as a *primary* contribution

Per the project instructions, these are components, not contributions:

1. Put NeuroHDC SNN weights into a ReRAM crossbar.
2. Use CIM for the SNN matrix–vector multiply.
3. Store NeuroHDC class hypervectors in ReRAM.
4. Perform Hamming distance inside memory.
5. Use a CAM for NeuroHDC similarity.
6. Exploit spike sparsity in a standard CIM array.
7. Crossbar for SNN + digital logic for HDC.
8. Use approximate HDC query.
9. Use multi-centroid HDC to improve array utilization.
10. Pruning / lower precision / different device technology as the headline.
11. Bolt an existing SNN-CIM architecture onto an existing HDC-CIM architecture.

§8 of this document explains, for each of these, *which specific published work already owns it*.

---

## 2. NeuroHDC — overview

NeuroHDC is a hybrid SNN + HDC classifier for DVS event data. Its contribution is an **encoding-free** hyperdimensional encoding: the hypervector *is* the SNN output spike raster, flattened.

Three claimed contributions **[S, §I]**:

1. A neuromorphic HDC method with compact hyperdimensional encoding that exploits SNN temporal dynamics.
2. A training scheme based on an equivalent hybrid spiking–binary neural network.
3. A lightweight hardware architecture using time-multiplexed core modules and a streaming structure.

Reported results **[S, §VI-B]**: >50% area saving and 20–90% energy reduction vs. HyperSpikeASIC and Spiking-HDC; model size 12.68 kB.

### 2.1 The single most important structural fact

**NeuroHDC has no encoder.** There is no item memory, no continuous item memory, no level hypervectors, no binding, no bundling, and no permutation anywhere in the inference path. **[S, §III-A eq. (7)]** The paper states this directly: the method "eliminat[es] the need for pregenerated hypervectors and complicated operations," and §VI-B notes it "completely obviates the need for base hypervectors."

Every consequence in §7 of this document follows from that fact.

---

## 3. NeuroHDC — detailed algorithm and dataflow

### 3.1 Event representation

Raw DVS output is a stream of quadruples `(t′, p, x, y)` **[S, §III-B]**:

- `t′` — real-valued timestamp from the sensor
- `(x, y)` — pixel coordinate of the brightness change
- `p ∈ {0,1}` — polarity (0 = brightness decrease, 1 = increase)

For **software training**, this is converted to a tensor. For **hardware inference**, the accelerator keeps the raw **AER format** and never builds the tensor **[S, §V-B]**: "in contrast to the aforementioned training process, which reconstructs event-based data into T frames, the original address-event representation (AER) format of event-based data is preserved, thereby upholding the inherent characteristics of sparsity and efficiency."

### 3.2 Events → timesteps (frames)

Events are accumulated per timestep **[S, eq. (8)]**:

```
E_(p,x,y)(p_k, x_k, y_k) = 1 if (p,x,y) == (p_k,x_k,y_k), else 0
D′(t)(p,x,y) = Σ_{t′_k ∈ t} E_(p,x,y)(p_k, x_k, y_k)
```

So `D′(t)` is a **count** image, not a binary image — a pixel hit by many events in a bin has a large value.

**Critical and unusual detail [S, §III-B]:** events are divided into `T` timesteps **uniformly by event count, not by wall-clock time** — "we divide them uniformly, ensuring an equal number of events in each." The hardware exposes this as a configuration register `N_e` = number of events per timestep **[S, §V-A]**.

**[I]** The "temporal" axis in NeuroHDC is therefore an **event-index axis**, i.e. an activity-normalised time. Temporal resolution automatically adapts to scene activity. This also means the timestep boundary in hardware is a *counter compare*, and is input-data-dependent.

### 3.3 SumPool

`D′(t)` is resized by **SumPool**: summation of pixels within non-overlapping windows **[S, §III-B, Fig. 2]**. Output `D(t) ∈ R^{P×H×W}`, default `2×16×16`.

**Stated purpose [S]:** the SNN parameter count is directly driven by the size of `D′(t)`; a larger input means more input neurons and a heavier parameter burden. SumPool cuts this.

**[I] Why *sum* and not max/average:** an IF neuron's membrane update is linear in its input, so summing `β×β` pixels *before* the synapse is exactly equivalent to accumulating each event's contribution individually *through a shared weight*. SumPool is therefore information-preserving with respect to total charge injected — it is a weight-sharing / address-aliasing operation, not a lossy downsample in the CNN sense.

**[I] Architecturally this is the key point:** in hardware SumPool costs **nothing**. It collapses entirely into the address generator **[S, §V-B eq. (19)]**:

```
addr = p·256 + ⌊y/β⌋·16 + ⌊x/β⌋
```

`β` is a per-dataset resize factor. The pooled frame is **never materialised**. Each arriving event is independently translated into one of 512 input-neuron addresses.

### 3.4 SNN

Single-layer fully-connected SNN, `n` **IF** neurons (IF chosen over LIF for hardware simplicity **[S, §II-A]**), weights `W_s ∈ R^{n×(P·H·W)}` quantised to **8-bit signed** via QAT **[S, §III-C]**.

General neuron model **[S, eq. (1)]**:
```
V_p(t) = f(V(t−1), X(t))
S(t)   = Θ(V_p(t) − V_thresh) ∈ {0,1}
V(t)   = V_p(t)·(1 − S(t)) + V_reset·S(t)        (V_reset = 0)
```
IF integration **[S, eq. (2)]**: `V_p(t) = V(t−1) + X(t)`.

**Hardware event loop [S, §V-B eq. (20)]:** on each event, every IF neuron module `j` reads the weight at the event's address from its own SRAM and accumulates:
```
R^V_j = R^V_j + ΣW_s_j(addr)
```
The event counter increments. When it reaches `N_e`, the timestep closes: each neuron compares `R^V_j` against `V_thresh`, writes the outcome into the output-spike register, and resets `R^V_j` to 0 if it fired. The timestep counter then increments.

### 3.5 Information present at each (neuron, timestep)

**[I]** At timestep `t`, neuron `j` holds:
- `R^V_j` — a 22-bit accumulated membrane potential (transient, discarded at the boundary except for carry-over when no spike occurs)
- `S_j(t) ∈ {0,1}` — the only quantity that survives into the hypervector

So the entire inference output of the SNN is an `n × T` binary raster. Everything else is scratch.

### 3.6 Hypervector formation — direct spike concatenation

**[S, eq. (7)]**:
```
h_t = [S_1(t), S_2(t), …, S_n(t)]
h^u = [h_1, h_2, …, h_T]
h   = h^u × 2 − 1
```

The bipolar conversion is for software convenience only; **hardware uses the unipolar form `h^u` directly** **[S, §III-A]**.

Therefore **`D_hv = n × T`** **[S, §IV-B1]**.

### 3.7 Why direct concatenation matters — the information-loss argument

NeuroHDC's whole case rests on comparing against two predecessors **[S, §III-A]**:

**HyperSpikeASIC [eq. (5)]** takes only the **final-timestep membrane potentials** and random-projects them:
```
h = Sign( Σ_j V_j(T) · I_j )
```
Two losses: (a) only `V(T)` is used, so intermediate temporal dynamics are discarded; (b) the `Sign()` destroys the information carried in the membrane potential magnitudes.

**Spiking-HDC [eq. (6)]** accumulates spikes per neuron into `sum_j ∈ [0,T]`, maps each to a random level HV `b_sum_j`, then combines with an N-gram style chain:
```
h = h_1 ⊗ Π¹h_2 ⊗ Π²h_3 ⊗ … ⊗ Π^(n−1)h_n
```
Losses: (a) `Σ_t S_j(t)` is a **firing rate** — the order of spikes within a neuron is destroyed; (b) the chain of element-wise multiplications causes "unavoidable confusion during information aggregation."

**NeuroHDC's claim [S]:** concatenation "efficiently harnesses all the spikes without any loss of information." Every `(j,t)` pair occupies its own dimension, so both *which* neuron fired and *when* are preserved exactly.

**Second-order consequence [S, §III-A, §IV-C]:** because prior encoders lose information, the SNN must supply *more* information to compensate → more neurons → more area/energy. NeuroHDC needs `n = 20` where competitors need far more.

**Third consequence [S, §III-C, §IV-E]:** concatenation is **differentiable** (`∂L/∂h^u = ½ ∂L/∂h`), so the SNN and the class hypervectors can be trained **jointly** by gradient descent. Spiking-HDC's encoder is non-differentiable and must train the two halves separately, which the paper calls "obviously suboptimal."

> **⚠️ This is the property that must be protected by any proposed architecture.** Any CIM design that re-collapses the spike sequence into a per-neuron rate, or that aggregates timesteps before the similarity computation, destroys the reason NeuroHDC exists.

### 3.8 Why `D_hv` depends on `n × T`, and why it is *not* a free hyperparameter

**[S, §IV-B]** — this is the most architecturally consequential experimental result in the paper:

- For **fixed `D_hv`**, increasing `n` forces `T` down, and **accuracy falls**. Reason given: "a smaller `T` renders spiking neurons less effective at capturing the temporal dynamics inherent in event-based data, and even a greater number of spiking neurons still cannot compensate for this."
- For **`T = 100`**, increasing `n` yields no substantial accuracy gain, only hardware cost.
- **Table I:** increasing `T` beyond 100 yields "almost no accuracy gain."

**Defaults: `T = 100`, `n = 20`, `D_hv = 2000`, 512 input neurons (`2×16×16`).** **[S, §IV-A, §IV-B1]**

**[I]** Therefore: `T` is pinned near 100 from below (accuracy) and above (diminishing returns); `n` is pinned near 20 from above (cost). **`D_hv ≈ 2000` is not a knob the architect can turn.** This single fact invalidates the standard HDC-CIM manoeuvre of trading dimensionality for array fit (see §7, G6).

### 3.9 Training

**Mode 1 — joint gradient descent (used for pretraining) [S, §III-C]:**
- Latent FP matrix `W_c ∈ R^{N×D_hv}`; `C = Sign(W_c)`; `Score = Sign(W_c)·hᵀ` **[eq. (10)]**
- Straight-through / gradient approximation for `Sign()`, consistent with LeHDC
- Surrogate gradient for `Θ()` **[eq. (12)–(15)]**; both temporal and spatial gradient terms; the final timestep has no temporal term
- `∂L/∂S(t) = ∂L/∂h^u( (t−1)·n : t·n )` **[eq. (14)]** — i.e. the gradient slices the hypervector by timestep
- SNN weight gradient accumulates over timesteps **[eq. (16)]**
- QAT folds `W_s` to int8 during training
- Loss = cross-entropy vs. one-hot label; Adam

**Mode 2 — HDC one-shot + retraining (used for transfer learning) [S, §IV-D]:**
```
C_i^nb = Σ_{h ∈ φ_i} h,     C_i = Sign(C_i^nb)              [eq. (17)]
on misprediction:  C^nb_match += α·h ;  C^nb_mismatch −= α·h  [eq. (18)]
```

**[S, §IV-E]** The two modes are functionally identical at inference — HDC querying is computationally the forward pass of a binary FC layer. Mode 1 exists for pretraining quality; Mode 2 exists for cheap on-chip adaptation.

### 3.10 Inference / querying

**[S, eq. (9)]**: `Score_i = Σ_m h(m)·C_i(m)`, `Pred = Argmax{Score_1…Score_N}`. Inner product is used rather than cosine, since for bipolar HVs they differ by a constant.

**[S, eq. (21)]** — the hardware form, accumulated **across timesteps**:
```
Score_i = Σ_{t=1..T} Σ_{m=(t−1)n .. t·n} ( h^u(m) XNOR C_i^u(m) )
```

So at each timestep the hardware reads an **`n`-bit slice** of each class hypervector, XNORs it against the `n`-bit output-spike register, and popcounts into a per-class accumulator. After `T` timesteps the accumulators hold the scores; a serial comparator produces the prediction.

---

## 4. NeuroHDC hardware architecture

### 4.1 Block inventory **[S, §V-A, Fig. 6]**

| Block | Contents | Count |
|---|---|---|
| Feature extractor | `n` IF neuron modules | 1 |
| IF neuron module | weight SRAM, 22-bit register + adder, comparator, reset logic | `n = 20` |
| HD query module | class-HV SRAM, `n` XNOR gates, `n`-bit register, `n`-input accumulator | `N_max` (one per class) |
| Address generator | implements eq. (19) | 1 |
| Timestep counter | event counter + timestep counter | 1 |
| Register group | mode, `V_thresh`, `N_e`, `N` | 1 |
| Serial comparator | argmax over `N` scores | 1 |

### 4.2 Memory organisation **[S, §V-A]**

**SNN weights:** one neuron needs `512 × 8 b`. Because of SRAM IP granularity, a `512 × 32 b` macro holds **four** neurons. For `n = 20`: 5 macros, `20 × 512 × 8 b = 81,920 b = 10.24 kB`.

**Class hypervectors:** `D_hv = 2000`, `n = 20` → logically `100 rows × 20 b`. The available IP forces a `128 × 24 b` macro, leaving **28 rows and 4 columns unused**.

**[I] Macro utilisation = 2000 / 3072 = 65.1%.** ~35% of the class-HV array area is dead silicon, and this waste is *replicated per class*.

**Membrane potential:** `n` registers × 22 bits = **55 bytes total**. Register/adder width chosen at 22 b to preclude overflow **[S]**.

**Total model: 12.68 kB** (weights + class HVs) **[S, §VI-B]**.

**[I] Memory budget breakdown:** SNN weights ≈ 81% of model bytes; class HVs (10 classes) ≈ 19%; membrane potential ≈ **0.4%**.

### 4.3 Workflow **[S, §V-B, §V-C, Fig. 7]**

1. **Data-write mode:** `W_s` and `C` streamed into their SRAMs over the Data interface. Done once per task.
2. **Execution mode (streaming):** events arrive continuously.
   - Per event: address generator computes `addr`; all `n` neuron modules read their weight at `addr` and accumulate; event counter++
   - On `event_count == N_e`: all neurons threshold/spike/reset → output-spike register; event counter reset; timestep counter++
   - Then each of the `N` query modules reads the `t`-th `n`-bit slice of its class HV, XNORs against the spike register, accumulates
3. After `T` timesteps: `N` scores → serial comparator → prediction.

### 4.4 Implementation and results **[S, §VI-A, §VI-B, §VI-C]**

- Verilog HDL; VCS simulation; Verdi waveform; **Yosys + SkyWater 130 nm** + SRAM IP; **OpenROAD** physical design; **PrimeTime** (time-based) for energy; **100 MHz**.
- Area/energy scaled to **45 nm** using Stillmaker & Baas for comparison against 28/40 nm baselines. (Authors note they could not scale 130 nm → 28/40 nm directly.)
- Two configurations provided, "small" and "large", for different dataset complexity.
- FPGA: Ultra96v2, Vivado 2022.1; BRAM substituted for SRAM macros. Offered explicitly as a reproducible baseline for other researchers **[S, §VI-C]** — useful for us.
- Datasets: N-MNIST, DVS-Gesture (11th "Other" class excluded, following Spiking-HDC), DVS-ASL (80/20 split).

---

## 5. NeuroHDC bottlenecks

Ordered by severity. **[I]** except where noted.

### B1 — SNN weight SRAM access is the dominant energy term
Per event, **`n` separate SRAM reads + `n` 22-bit adds** occur. Events per sample = `N_e × T`, typically thousands to tens of thousands. Total weight-read count per inference ≈ `n × N_events`. Nothing else in the design scales with the event count.

### B2 — SNN weight SRAM is the dominant area term
10.24 kB of the 12.68 kB model. **[S]** The paper itself reasons this way when comparing against EventHD: "SRAM macros dominate the area of storage-intensive hardware designs."

### B3 — Query hardware is replicated per class
`N_max` complete query modules, each with its own SRAM macro, XNOR array, register and accumulator **[S, §V-A]**. Area grows **linearly in `N`**. DVS-ASL has 24 classes; FERET-scale tasks would have hundreds.

### B4 — Class-HV SRAM macro granularity waste
65.1% utilisation (§4.2), replicated `N` times. The paper concedes the design is brittle here: "any alteration in the values of `D_hv` and `n` necessitates adjustments to both the SRAM macro specification and the aforementioned circuits" **[S, §V-A]**.

### B5 — Latency is set by the event count and *nothing else*
**[S, §V-C]:** "the number of timesteps only affects the granularity of event partitioning without changing the total event count. Consequently, it does not impact the latency of the accelerator."

**[I] This inverts the usual CIM value proposition.** Increasing `T` costs **area and energy** but **not latency**. The query is effectively latency-free because it is amortised inside a stream that must arrive anyway. Optimising "search cycles" — the headline metric of MEMHD (80×), CAMPRO (single-cycle search) and HDStream (99% utilisation) — targets a quantity that is **not a NeuroHDC bottleneck.**

### B6 — Membrane potential is *not* a bottleneck
`n × 22 b = 55 B`, held in flip-flops, never spilled to SRAM.

**[I] This directly contradicts the premise of the SNN-CIM literature.** IMPULSE's entire contribution is eliminating `V_MEM` memory traffic; SpikeSim reports the `V_mem` cache makes the SNN neuronal module ~1000× the area of an ANN's ReLU module. Both assume hundreds-to-thousands of neurons. With `n = 20`, NeuroHDC has already designed the membrane-potential problem out of existence.

### B7 — Data movement summary

| Path | Rate | Volume per inference | Regularity |
|---|---|---|---|
| Weight SRAM → adder | per **event**, per neuron | `n × N_events × 8 b` | **irregular**, address = f(p,x,y) |
| Spike register → XNOR | per **timestep** | `n × T` bits | perfectly regular |
| Class-HV SRAM → XNOR | per **timestep**, per class | `N × n × T` bits | perfectly regular, **sequential**, **single-pass** |
| V register ↔ adder | per **event** | 22 b × n, on-chip FF | register-local |

### B8 — Sequential / parallel / sparse decomposition

| Property | Where it appears |
|---|---|
| Inherently **sequential** | Timestep ordering; membrane accumulation within a timestep; argmax |
| Inherently **parallel** | Across `n` neurons (per event); across `N` classes (per timestep); across the `n` bits of a slice |
| Inherently **sparse** | The input event stream (AER — already fully exploited by construction) |
| **Not** sparse | The output spike raster, *as the query is currently formulated* — a `0` matched against a `0` contributes to the XNOR score. See §7/G3 for why this is reformulable. |
| **Reused** | `W_s` — read `N_events` times per inference |
| **Single-use** | `C_i` — each bit read exactly **once** per inference |

---

## 6. Related work — per-paper reverse engineering

### 6.1 IMPULSE (Agrawal, Ali, Koo, Rathi, Jaiswal, Roy — 65 nm digital CIM macro, arXiv 2105.08217)

| Dimension | Finding |
|---|---|
| Memory technology | **10T-SRAM**, digital CIM, 65 nm fabricated silicon **[S]** |
| Array organisation | Fused `W_MEM` + `V_MEM` sharing common bitlines. `W_MEM`: 128 rows (one per input neuron) × twelve 6-bit signed weights. `V_MEM`: 32 rows × six signed values, 11-bit `V_mem`. Triple-row decoder enables 2 RWL + 1 WWL simultaneously. **[S, §II, Fig. 3]** |
| What is stored | Synaptic weights **and** membrane potentials in the same physical array |
| In-array computation | Bitwise NOR/OR on RBL, NAND/AND on RBLB from two enabled RWLs; sensed by SINV; combined by a **bitwise-logic full adder (BLFA)** per column into SUM/COUT; SUM written back via conditional write driver. **[S, §II-A, Fig. 4]** |
| Peripherals | SINV, BLFA, CWD, Carry-MUXes reconfigurable into carry-forward / carry-skip / LSB / MSB modes to support the **staggered data mapping** (6-bit weights vs 11-bit `V_mem`) at full column-peripheral utilisation **[S]** |
| Instruction set | `AccW2V`, `AccV2V`, `SpikeCheck` (adders act as comparators via MSB COUT), `ResetV` (BLFA bypassed) **[S, §II-B, Fig. 5]** |
| Neuron models | IF, LIF (via `AccV2V` leak subtraction), RMP (soft reset via `AccV2V` after `SpikeCheck`) **[S, §II-C]** |
| Sparsity | **Input-spike** sparsity: the number of spikes determines the number and sequence of instructions executed. 85% sparsity → **97.4% EDP reduction** **[S, §III, Fig. 11]** |
| Precision | 6-bit signed weights, 11-bit signed `V_mem` |
| Temporal state | **This is the core contribution** — `V_mem` never leaves the array |
| HDC encoding / query | **None. IMPULSE is not an HDC design.** |
| Training | Off-chip, surrogate-gradient BP with threshold/leak optimisation (DIET-SNN) |
| Results | 0.99 TOPS/W @ 0.85 V / 200 MHz for 11-bit `AccW2V`; `AccV2V` 1.18, `ResetV` 1.02, `SpikeCheck` 1.22 TOPS/W; 54.2% memory area efficiency; IMDB 88.15% with 29.3 K params vs LSTM 247.8 K; MNIST 98.96% @ 10 timesteps **[S]** |
| Main innovation | Fused `W_MEM`/`V_MEM` + staggered mixed-precision mapping + full in-memory SNN instruction set |
| Main limitation | **Fan-in capped at 128** (explicitly: Conv layers restricted to 3×3×14=126 to fit) **[S, §III]**; scaling needs a distributed multi-macro architecture |
| Workload-specific part | The entire `V_MEM` subarray and the staggered mapping exist only because `V_mem` traffic is assumed to dominate |

**Relevance verdict for NeuroHDC:** **low, and this is a substantive negative finding.** NeuroHDC has `n = 20` membrane potentials totalling 55 bytes (§B6). The `V_MEM` subarray, the staggered mapping, the reconfigurable carry modes and the `AccV2V`/`ResetV` instructions all solve a problem NeuroHDC does not have. Moreover NeuroHDC needs fan-in **512**, four times IMPULSE's hard cap, forcing macro tiling with partial-sum merging. **[I]** The *transferable* idea is narrower than it appears: only that a spike/event should activate a single wordline and have its weights accumulate in place, without a separate compute unit.

---

### 6.2 MEMHD (Kang, Oh, Hwang, Kim, Jeon, Ko — arXiv 2502.07834)

| Dimension | Finding |
|---|---|
| Memory technology | SRAM-based IMC arrays; energy/cycle numbers from **NeuroSim** **[S, §IV-A]** |
| Problem addressed | Dimensional mismatch between HDC hypervectors (near 10 k) and IMC array row count (128–512), **and** column underutilisation because classical HDC stores one vector per class (10 classes in a 128-column array = 7.81% utilisation) **[S, §I, Fig. 1]** |
| Core idea | **Multi-centroid associative memory** sized to the array: `D` = row count, number of centroids = column count. Multiple class vectors per class, each capturing distinct features **[S, §III]** |
| Training | (a) classwise K-means with **dot similarity** as the metric; hyperparameter `R` = fraction of columns used for initial clustering; remaining columns allocated to classes with high misclassification rates via a confusion matrix, iteratively until all columns are used. (b) 1-bit quantisation at the **mean**. (c) quantisation-aware iterative learning with a normalisation step to stop one centroid dominating. **[S, §III-A–C]** |
| Encoding | Random projection (MVM) — chosen specifically because it maps to IMC; dot similarity for search, also MVM **[S, §III-D]** |
| Results | Up to 13.69% higher accuracy at equal memory, or 13.25× memory efficiency at equal accuracy; **80× fewer computation cycles**, **71× fewer arrays**, AM utilisation 7.81% → **100%**; one-shot search in a single 128×128 array **[S, §IV]** |
| Main innovation | Reframing the model to fit the array, rather than partitioning the model across arrays |
| Main limitation | Requires retraining the whole associative memory; datasets are static feature vectors (MNIST/FMNIST/ISOLET); no temporal structure anywhere |
| Workload-specific part | Multi-centroid only makes sense when `D` is a free hyperparameter and classes have multi-modal structure |

**Relevance verdict for NeuroHDC:** **the problem is real but manifests inverted, and the solution does not transfer.** See §7/G6. MEMHD's mismatch is `D >> rows`. NeuroHDC's per-activation query width is `n = 20` bits — *far smaller* than any array row (20/128 = 15.6% row utilisation) — while the *full* hypervector, 2000 bits, is only ever presented `20` bits at a time. And MEMHD's fix (shrink `D`, spend the freed columns on centroids) is blocked because `D_hv = n·T` is pinned by accuracy (§3.8). Adding centroids to NeuroHDC would be a straightforward composition, i.e. explicitly disallowed item #9.

---

### 6.3 HDStream (Antonio, Yi, Deng, Kong, Yin, Verhelst — GLSVLSI '26, 16 nm silicon)

| Dimension | Finding |
|---|---|
| Category | **Not a CIM design.** A programmable von-Neumann-style streaming processor with a wide-vector datapath **[S, §3]** |
| Problem addressed | "Compute-efficiency-density gap": encoding-specific ASICs are efficient but inflexible; programmable HDC processors waste cycles on loop control and data movement (only 3 of 9 instructions do useful work in a RISC-V HDC baseline) **[S, §1, Listing 1]** |
| Datapath | 512-bit wide vector; 4 D-wide registers; **2 bundler arrays** of D×8-bit saturating up/down counters where the output bit is simply the MSB, eliminating threshold comparators; 2-input SIMD ALU (XOR / circular shift / transfer) **[S, §3.1, Fig. 3b]** |
| Projection | ROM-based orthogonal iM (1024 items) + continuous iM (256 items), single-cycle; explicitly *rejects* on-the-fly HV generation due to latency under random access **[S, §3.1]** |
| Associative memory | Fully **combinational** Hamming distance: D-wide XOR array + adder tree; 32 × 16-bit score registers; combinational argmin. **AM search overlaps with encoding of the next query** **[S, §3.1, Fig. 3c]** |
| Streaming | Data streamers with AGU + affine access patterns + **data slicing** (partitioning 64-bit words into 1/4/8-bit symbols) + FIFO prefetch; **hardware loop counters** double as instruction sequencers **[S, §3.2]** |
| Key mechanism | **Multi-operation fused instructions** (e.g. `imab_bind_bund` = fetch from both iMs + bind + bundle in one cycle) **[S, Fig. 4]** |
| Scaling | **Vector folding** — a `D_target`-bit HV is split into 512-bit segments, each encoded and searched, with partial Hamming distances accumulated **[S, §3.3]** |
| Results | Utilisation 17–50% → **80–99%**; compound speedup 1.59–5.85×; 0.870 TBOPS peak, **7.98 TBOPS/W** @ 0.6 V/325 MHz; 0.260 mm²; area 65.7% data memory / 28.3% compute / 6% control; power **72% encoding** **[S, §4]** |
| Main limitation | Native `D = 512` is 2–4× narrower than competitors, so latency suffers and must be recovered by folding |

**Relevance verdict:** **the resemblance to NeuroHDC is superficial, and it matters that we say so precisely.**

- **Superficial similarity:** both are "streaming." **[I]** But HDStream streams *feature symbols out of a memory the compiler pre-arranged*, with affine access patterns known at compile time. NeuroHDC streams *asynchronous sensor events whose addresses are data-dependent*, with timestep boundaries defined by an event count. Different in kind.
- **Fundamental similarity — and this one is real:** HDStream's **vector folding** (segment the HV, search each segment, accumulate partial scores) is *structurally identical* to NeuroHDC's per-timestep partial-score accumulation over `n`-bit slices. **[I] NeuroHDC is, in effect, permanently folded at granularity `n = 20`, and the folding is imposed by the algorithm rather than chosen by the architect.** This is a genuinely useful framing and should be cited as prior art for any per-slice-accumulation mechanism we propose, so we do not accidentally claim it.
- **Where HDStream's effort goes is irrelevant to us:** 72% of its power is encoding, and its instruction fusion exists to compose bind/bundle/permute. NeuroHDC has none of those operations.

---

### 6.4 HDC-SNN hybrid processor (Xiao, Yang, Yang, Zhang, He, Yang, Zheng, Zou — IEEE TCAS-AI vol. 3 no. 3, 2026, 40 nm silicon)

| Dimension | Finding |
|---|---|
| Category | Conventional digital ASIC, SRAM-based. **Not CIM.** |
| Goal | On-chip **few-shot transfer learning** (FSTL): freeze the SNN, retrain only the HDC classifier **[S, §II-B, Fig. 2b]** |
| SNN | **LIF** neurons, FC topology, 8-bit weights, 16-bit `V_mem` **in SRAM**; 4 parallel LIF units; 700 neurons, 100 k synapses supported **[S, §III-B]** |
| Feature vector | **Spike counters** — `f_j = Σ_t S_j(t)`, a per-neuron firing count **[S, eq. (2)]** |
| Encoding | Each FV element **indexes** a basis HV from a set `{b_0 … b_T}` generated by **random Fourier features**; then circular-shift by neuron index and XOR-chain **[S, eq. (1)–(4)]** |
| Class storage | 1-bit class HVs, 2.5 kB SRAM, 100-bit width, 20 entries per HV, `D = 2 k` |
| Similarity | XOR + adder tree, 100 1-bit adds per cycle, accumulated across twenty 100-bit groups **[S, §III-C, eq. (5)]** |
| Training | **STE** mixed precision: 16-bit latent class HVs for training, 1-bit for inference **[S, §II-D, Fig. 4]** |
| HW optimisation 1 | **WAD-MB** — weight access from *destination* neuron with memory banks, instead of from source neuron. Fixes data misalignment between the 1-bit and 16-bit class-HV SRAMs and eliminates SRAM-entry redundancy when class count ≠ bank width. Access time share of training latency 74% → 14% **[S, §IV-A]** |
| HW optimisation 2 | **BGC** — batch-by-batch gradient computation: cache `H`, `S`, `Y` rather than per-sample gradients; compute and write back in a pipeline. Cache 40 kB → **2.17 kB (>18×)** **[S, §IV-B]** |
| Results | 1.56 mm² core, 155.4 kB memory, 0.72 V / 65 MHz, 1.6 mW; ECG 97.8% at 0.1 mJ/patient; bearing 96.84% 3-shot at 0.3 mJ/class; N-MNIST 95.7% 2-shot; DVS-Gesture 90.7% **[S, §V]** |

**Relevance verdict:** **this is essentially the architecture NeuroHDC was written to beat, made concrete and fabricated.** Its encoder uses **per-neuron spike counts** (`Σ_t S_j(t)`) — exactly the rate-collapse NeuroHDC identifies as information loss in Spiking-HDC (§3.7), by the same Fudan group (Xiao is the first author of Spiking-HDC, cited as NeuroHDC ref [7], and NeuroHDC cites this processor as ref [31]).

**[I] Two important extractions:**
1. Its architectural assumptions — basis-HV memory, index-then-shift-then-XOR encoder, separate encoder pipeline stage — are all **artefacts of rate encoding**. Under NeuroHDC's concatenation they all vanish. This is strong corroborating evidence for G1 (§7).
2. Its two optimisations (WAD-MB, BGC) address **on-chip class-HV update**, not inference. If our eventual architecture supports NeuroHDC's Mode-2 transfer learning in a non-volatile array, these are the correct baselines for the training path, and the relevant *new* question is how the update rule interacts with NVM write cost and endurance, which they never face in SRAM.

---

### 6.5 CAMPRO (He, Hu, Xiao, Yang, Zhang, Zheng, Zou — IEEE TCAS-I vol. 73 no. 6, June 2026, 22 nm)

| Dimension | Finding |
|---|---|
| Memory technology | **SRAM CAM** built from **Split Word Line (SWL) 6T** bit cells; simulated 22 nm CMOS **[S, §III-A]** |
| Why SWL 6T | Separate WLL/WLR enables **column-wise search** so HVs can be stored **row-wise**, matching their ultra-wide aspect ratio. Conventional associative processors use row-wise search with column-wise storage, which gives impractical aspect ratios for HDC **[S, §III, Fig. 3]** |
| Array organisation | 160 CAM blocks of 64 × 64 b → 64 HVs of 10,240 b; partitioned into iM / CiM / **Processing Memory (PM)** regions; PM doubles as scratchpad and workspace **[S, §III-E, §V-A]** |
| Search mechanism | WLL carries the key, WLR its complement; `ML = BL & BLB`; **Reconfigurable Sense Amplifier** switches between differential (read) and single-ended (search, vs 0.8 V `Vref`); **selective precharge** skips columns **[S, §III-A, Fig. 4]** |
| Associative processing | Search keys generated from operation **truth tables** held in the Search Unit (data table + mask table, 25-bit FF arrays); only entries with output `1` are searched; results OR-ed into a **Tag Register**; **deferred bulk row-write** reuses SRAM-mode write circuitry **[S, §III-B, Fig. 6]** |
| Binding | `bind2` = XOR via 2 searches, dual updates merged into one cycle **[S, §III-D1]** |
| Bundling | `bundle3` / `bundle4`, applied **hierarchically**; 1-bit output per dimension per stage → **approximate bundling**. Justified empirically: >81% of HV channels have a >60% dominant bit, so ties are rare and randomising them costs nothing. **14.1× speedup** vs adder-tree + comparator voter **[S, §III-D2, Fig. 7, Table II]**. Fine-grained pipeline prioritises entries that free memory |
| Permutation | **Hierarchical permutation** — cascaded power-of-two shifters (1, 2, 4, …) enabled by shift-bit signals; arbitrary shifts up to 255 bits; **90.66% shifter power reduction**, 14.4% system power reduction, at **+71.53% shifter area** **[S, §III-D3, Fig. 5]** |
| Similarity | bind to Tag Reg, then **TPBP** module; adder tree accumulates 200 1-bit values/cycle by time-division multiplexing |
| **TPBP** | **Two-Phase Bit Pruning.** **GRB** = bit positions identical across *all* class HVs — contribute equally to every Hamming distance, therefore skippable with **zero** accuracy loss. **CRB** = bit positions identical within a pairwise cluster. Skip tags obtained by **two CAM searches** (all-0 key, all-1 key). Phase 1: intra-cluster, using `HD₂ = (D − RB_sum) − HD₁` so only one distance is computed per pair; Phase 2: inter-cluster on CRB only. Pairwise clustering proven optimal against a greedy merge algorithm. **−73.6% operations, −65.2% energy, no accuracy loss**; TPBP area 42,222 µm² = 3.73% **[S, §IV]** |
| Results | 1.13 mm², 0.99 mW @ 200 MHz / 0.9 V; language classification inference energy −99.2% vs Karunaratne PCM; EMG 2.6×/6.7× training/inference energy improvement, 73× latency; MNIST 11.3× energy, 1.6× latency vs Spiking-HDC **[S, §V-B]** |
| Main limitation | Scalability — CAM/PIM designs need more macros and advanced integration for large tasks; authors acknowledge these architectures are "currently mainly used for small-scale tasks" **[S, §II-B]** |

**Relevance verdict:** **CAMPRO owns the CAM-based HDC operator mapping.** Any proposal of ours that involves binding/bundling/permutation in a CAM is pre-empted — but NeuroHDC has none of those, so most of CAMPRO is inapplicable. **The part that is directly relevant is TPBP**, and it must be distinguished carefully: TPBP exploits redundancy **across the class set** (bits identical between classes), which is *query-independent* and computable offline/at-load. See §7/G3 for the dual — query-side sparsity — which TPBP does not address.

---

### 6.6 Memristor-based approximate query (Yu, Wu, Chen, Zhang, Liu — IEEE TC vol. 73 no. 11, Nov 2024)

**Note: same authors as NeuroHDC.** Yu, Wu, Chen, Zhang and Liu are on both papers. This is the NeuroHDC group's own in-memory associative-memory work. Treat everything here as their home territory.

| Dimension | Finding |
|---|---|
| Memory technology | Technology-agnostic HAM; demonstrated with **STT-MRAM** (low TMR = 3.6) and **RRAM** (ON/OFF ≈ 1000); FeFET noted as compatible **[S, §I, §IV-B2]** |
| Problem addressed | Existing HDC training forces the HAM to do **high-precision** query, requiring ADCs / digital accumulators / high-resolution current comparators, which dominate area and energy **[S, §I, §II-B]** |
| Approximate query | `s_i = Σ_{k=1..D_hv/D_tile} Sign( C^k_{i,seg} · H^k_seg )` **[S, eq. (6)]** — per-segment **majority**, not exact match count. `D_tile = 256`, `D_hv = 8192` → 32 tiles |
| Row tile circuit | 256 bitcells on one **match line**; ML precharged to Vdd; a matching cell discharges **slowly**, a mismatching cell **fast**; a sense amplifier against `Vref` set between 127 and 128 matches outputs `1` if more than half the bits match **[S, §IV-B]** |
| Bitcells | **Direct-access** mode for high ON/OFF technologies (RRAM/FeFET); **NMOS-access** mode for STT-MRAM, which trades area for a usable discharge ratio. Voltage gap for 128 vs 127 matches: 0.3–0.8 mV for STT-MRAM direct-access (unusable) vs 5 mV for RRAM **[S, Table II, Fig. 5–6]** |
| Merging | 32 cascaded **signal-controlled delay modules** — the accumulated count is encoded as a **total propagation delay**, `D_total = i·D_short + (32−i)·D_long` **[S, §IV-C, eq. (11)]** |
| WTA | Parallel NOR + D-flip-flop structure; the first rising edge (shortest delay = highest similarity) latches a `1`, all others `0` **[S, §IV-D, Fig. 9]** |
| Training | **This is the essential half.** Naively feeding conventionally-trained class HVs into approximate query is catastrophic: ISOLET 96.34% → **9.37%** **[S, Table I]**. The fix: model the approximate query inside a modified wide binary FC layer with a per-segment scale `α^k_i = (1/D_tile)·Σ|F^k_{i,seg}|` precomputed each iteration, trained with BNN-style STE **[S, eq. (8)–(9)]**. `α > 0` so inference is unaffected **[S, eq. (10)]** |
| Device variation | 3% variation in `t_ox`, `t_sl`, TMR shifts the *effective* per-tile threshold from 128 to anywhere in **110–142** **[S, Fig. 10]**, costing 1.56–4.85% accuracy. Fixed by measuring the per-tile actual threshold `T^k_i` and folding `β^k_i = 2T^k_i − D_tile` into training **[S, eq. (12)–(14)]**; recovers >90% of the loss |
| Results | RRAM: 0.115 fJ/element, 2.8 ns, 0.023 mm² @45 nm; >60% area and energy saving vs A-HAM/COSIME/PCM designs; accuracy on par with LeHDC **[S, Table IX, X]** |
| System-level finding | Encoding dominates system energy at small class counts; **query only dominates beyond ~2000 classes** **[S, §VI-F, Fig. 13]** |

**Relevance verdict and competitive warning:**

**[I]** This paper plus NeuroHDC, by the same group, is one obvious paper away from "NeuroHDC class hypervectors in an approximate-query HAM with hardware-aware training." Bi Wu's stated research area is *"spintronic device-based in-memory computing architecture."* **We should assume this specific combination is either in progress or trivially available to them, and we must not build our contribution on it.**

**[I] Additionally, it may not even work as-is.** `D_tile = 256` does not divide into NeuroHDC's timestep structure: `n = 20`, so a 256-bit tile spans 12.8 timesteps. The natural segment boundary in NeuroHDC is the timestep (`n = 20` bits). A per-timestep `Sign()` approximation compresses each timestep to **1 bit**, giving a `T = 100`-bit score with completely different error statistics from a 32-tile score. Whether that is viable is an open empirical question — and an argument that *even the obvious composition is non-trivial*, which is worth knowing but is not by itself a contribution.

---

### 6.7 External works consulted (not in the attached set, but load-bearing for the novelty analysis)

| Work | What it establishes |
|---|---|
| Karunaratne et al., *In-memory hyperdimensional computing*, Nature Electronics 3(6), 2020 | Complete in-memory HDC on two PCM crossbars (760 k devices); encoding crossbar + AM crossbar; dot-product on bitlines + WTA. **Owns "end-to-end HDC in crossbars."** |
| Karunaratne et al., *Energy Efficient In-memory Hyperdimensional Encoding for Spatio-temporal Signal Processing*, IEEE TCAS-II 68(5), 2021 (arXiv 2106.11654) | In-memory **spatio-temporal** HDC encoding: memristive crossbar + circular buffer + binder + bundler; temporal encoding applied immediately per channel-bound HV: `T_m = ρ^(N−1)I_{1,m} ∗ ρ^(N−2)I_{2,m} ∗ … ∗ I_{N,m}`. **Closest external prior art on "temporal HDC in CIM."** |
| Li et al., *2T2R RRAM-Based In-Memory HDC Encoder for Spatio-Temporal Signal Processing*, IEEE TCAS-II 71(5), 2024 | Voltage-mode 2T2R; binding/bundling in-array, permutation in digital periphery; paired with an RRAM in-memory associative search module; 97.96% on EMG |
| Imani et al., *Exploring Hyperdimensional Associative Memory* (R-HAM / A-HAM), HPCA 2017 | Owns RRAM-based HAM; A-HAM uses current summation + multistage comparators |
| Liu et al., *COSIME*, ICCAD 2022 | FeFET analog cosine-similarity HAM + WTA |
| Thomann et al., *HW/SW Co-design for Reliable TCAM-based In-memory HDC*, IEEE TC 72(8), 2023 | TCAM block = partial Hamming distance via ML discharge rate; CSRSA converts discharge rate to temporal domain; block size 2–25 bits; **establishes that small-block partial-HD accumulation is known art** |
| Hersche et al., ISLPED 2020 | DVS events + **sparse** HDC accelerator with online learning — establishes the event-HDC (non-CIM) landscape |
| Zou et al., *EventHD*, Frontiers in Neuroscience 16, 2022 | Pure-HDC on DVS; `D = 4000`; spatial+temporal encoding; the baseline NeuroHDC beats on model size (570 kB vs 12.68 kB) |
| Zhang et al., *HyperSpikeASIC*, IEEE TCAD 42(11), 2023 | Prior SNN+HDC ASIC; final-timestep membrane potentials + random projection (NeuroHDC ref [6]) |
| Xiao et al., *Spiking-HDC*, ISCAS 2024 | Prior SNN+HDC ASIC; spike-count accumulation + modified N-gram (NeuroHDC ref [7]) |
| Moitra et al., *SpikeSim*, IEEE TCAD 2023 | SNN-on-CIM evaluation platform; reports the `V_mem` cache makes the SNN neuronal module ~1000× an ANN ReLU module in area — **the assumption NeuroHDC breaks** |
| Yu et al., *LAHDC* (TCAD 2025), *AttnACQ* (TCAS-II 2024), *Fully learnable HDC* (TC 2024) | Same group; query-side optimisations. Confirms the NeuroHDC authors are actively working the **query circuit** axis. |

---

## 7. Architecture / dataflow comparison table

| Axis | NeuroHDC | IMPULSE | MEMHD | HDStream | HDC-SNN (Xiao) | CAMPRO | ApproxQuery (Yu) |
|---|---|---|---|---|---|---|---|
| **Category** | ASIC (digital) | Digital CIM macro | IMC mapping + algorithm | Streaming processor | ASIC (digital) | CAM-PIM processor | Analog HAM + training |
| **Memory tech** | SRAM (SkyWater 130) | 10T-SRAM (65 nm) | SRAM IMC (NeuroSim) | SRAM (16 nm) | SRAM (40 nm) | SWL-6T SRAM CAM (22 nm) | STT-MRAM / RRAM / FeFET |
| **Silicon?** | Synth + PnR | **Fabricated** | Simulation | **Fabricated** | **Fabricated** | Simulation | Simulation |
| **SNN present** | ✔ 1-layer FC, IF | ✔ FC + Conv, IF/LIF/RMP | ✘ | ✘ | ✔ 2-layer FC, LIF | ✘ | ✘ |
| **SNN compute location** | SRAM + external adder | **in-array** | — | — | SRAM + external adder | — | — |
| **`V_mem` location** | 20 × 22 b registers | **in-array (fused)** | — | — | SRAM (16 b) | — | — |
| **Event/AER input** | ✔ native AER | ✘ (frame/timestep) | ✘ | ✘ | ✔ AER | ✘ | ✘ |
| **Encoder needed** | **none** | — | projection (MVM) | iM/CiM + bind/bundle/perm | basis-HV index + shift + XOR | iM/CiM + bind/bundle/perm | assumed external |
| **Binding in memory** | n/a | — | ✘ | ✘ (datapath) | ✘ | ✔ `bind2` | ✘ |
| **Bundling in memory** | n/a | — | ✘ | ✘ (counter array) | ✘ | ✔ approx. `bundle3/4` | ✘ |
| **Permutation** | n/a | — | ✘ | barrel/circular shift | circular shift | ✔ hierarchical shifters | ✘ |
| **HV formation** | **spike concatenation** | — | random projection | programmable | spike-**count** → basis HV | programmable | external |
| **Temporal info preserved** | **✔ exactly (n×T)** | ✔ (`V_mem` recurrence) | ✘ | partially (n-gram/ST) | ✘ (**rate-collapsed**) | partially (n-gram/ST) | ✘ |
| **Class HV storage** | SRAM, per-class module | — | **IMC array, multi-centroid** | data memory | SRAM 1-bit + 16-bit latent | CAM (AM region of PM) | NVM row tiles |
| **Similarity** | XNOR + popcount, per-timestep | — | dot product (MVM) | combinational XOR + adder tree | XOR + adder tree | bind + **TPBP** | **approximate, ML discharge** |
| **Similarity latency** | hidden in event stream | — | **1 cycle** (goal) | overlapped w/ encode | multi-cycle | pipelined | 2.8 ns |
| **Query approximation** | ✘ exact | — | ✘ exact | ✘ exact | ✘ exact | ✘ exact (TPBP is lossless) | **✔ per-segment sign()** |
| **Sparsity exploited** | input AER (by construction) | **input-spike → skip instr.** | ✘ | ✘ | input AER | class-set redundancy (TPBP) | ✘ |
| **Array utilisation addressed** | ✘ (65% macro waste) | ✔ staggered mapping | **✔ core contribution (→100%)** | ✔ 99% compute util. | ✔ WAD-MB banks | ✔ selective precharge | ✘ |
| **Precision** | W 8 b, V 22 b, HV 1 b | W 6 b, V 11 b | HV 1 b | HV 1 b, bundler 8 b | W 8 b, HV 1 b/16 b | HV 1 b (multi-bit possible) | HV 1 b |
| **On-chip training** | ✔ Mode 2 (one-shot + retrain) | ✘ | ✘ (offline) | ✔ bundling only | **✔ STE + WAD-MB + BGC** | ✔ bundling | ✘ (offline, HW-aware) |
| **HW-aware training** | ✔ QAT + surrogate grad | ✘ | ✔ quant-aware iterative | ✘ | ✔ STE | ✘ | **✔ α and β compensation** |
| **Early exit / anytime** | ✘ | ✘ | ✘ | ✘ | ✘ | ✘ | ✘ |
| **Primary target metric** | area + energy | EDP (via sparsity) | cycles + array count | TBOPS/W/mm² | mJ/transfer | energy/latency | area + energy of HAM |

---

## 8. What each paper actually contributes — and which "obvious idea" it forecloses

| "Obvious idea" (disallowed as primary) | Already owned by | Why it is closed |
|---|---|---|
| Put SNN weights in a ReRAM crossbar | Generic SNN-CIM (SpikeSim, ASTERS, Tempo-CIM, RRAM-CIM SNN body of work) | Standard practice since ~2019 |
| Use CIM for the SNN MVM | IMPULSE; SpikeSim; Karunaratne | Standard practice. **And see §9/G9 — for NeuroHDC it may be actively wrong** |
| Store class HVs in ReRAM | Imani HPCA'17 (R-HAM/A-HAM); Karunaratne Nature Elec. 2020 | Foundational |
| Hamming distance inside memory | A-HAM, COSIME, Thomann TCAM, CAMPRO | Multiple independent implementations |
| CAM for similarity | CAMPRO, A-HAM, COSIME, Kazemi FeFET | Directly owned |
| Exploit spike sparsity in a CIM array | IMPULSE (97.4% EDP at 85% sparsity) | Directly owned; **and NeuroHDC already exploits input sparsity by using AER** |
| Crossbar SNN + digital HDC | HyperSpikeASIC, Spiking-HDC, Xiao's HDC-SNN (digital); trivially portable | The *combination* is published three times over |
| Approximate HDC query | Yu et al. TC 2024 — **the NeuroHDC authors themselves** | Owned, and by the incumbent group |
| Multi-centroid for array utilisation | MEMHD | Directly owned |
| Pruning HDC computation | CAMPRO TPBP; Antonio & Alvarez ISCAS'22; Liu ICCD'24 | Owned |
| Lower precision | QuantHD, LeHDC, FATE, and NeuroHDC's own QAT | Owned |
| SNN-CIM block + HDC-CIM block | Composition of the above | Explicitly excluded by the project constraint |
| **In-memory spatio-temporal HDC encoding** | Karunaratne TCAS-II 2021; Li 2T2R TCAS-II 2024 | ⚠️ **Watch this one.** A reviewer may claim NeuroHDC encoding-in-CIM is "the same thing." It is not — see §9/G2 for the precise distinction — but we must state the distinction ourselves, first, in the paper. |

---

## 9. Design-space matrix and gap analysis

### 9.1 Coverage matrix

`●` = core contribution · `○` = addressed · `–` = not addressed · `n/a` = not applicable to that workload

| # | Design-space axis | NeuroHDC | IMPULSE | MEMHD | HDStream | HDC-SNN | CAMPRO | ApproxQ | Karunaratne ST / 2T2R |
|---|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| 1 | SNN synaptic computation | ○ | ● | – | – | ○ | – | – | – |
| 2 | Temporal state / `V_mem` storage | ○ | ● | – | – | ○ | – | – | – |
| 3 | Spike generation (threshold/reset) | ○ | ● | – | – | ○ | – | – | – |
| 4 | Native AER / event-driven input | ● | – | – | – | ○ | – | – | – |
| 5 | Spike accumulation over time | ● | ○ | – | – | ○ (rate) | – | – | – |
| 6 | Spike → HV encoding | ● | n/a | – | – | ○ | – | – | – |
| 7 | Binding | n/a | n/a | – | ○ | ○ | ● | – | ● |
| 8 | Bundling | n/a | n/a | – | ○ | ○ | ● | – | ● |
| 9 | Permutation | n/a | n/a | – | ○ | ○ | ● | – | ○ |
| 10 | Item / base HV memory | n/a | n/a | ○ | ● | ○ | ○ | – | ○ |
| 11 | **Temporal concatenation as encoding** | ● | – | – | – | – | – | – | – |
| 12 | Spatial aggregation / pooling | ● (SumPool→addr) | ○ (Conv map) | – | – | – | – | – | ○ |
| 13 | Class-HV storage organisation | ○ | n/a | ● | ○ | ○ | ● | ● | ○ |
| 14 | Similarity / query compute | ○ | n/a | ● | ● | ○ | ● | ● | ○ |
| 15 | Query approximation | – | n/a | – | – | – | – | ● | – |
| 16 | **Query-side (spike) sparsity in similarity** | – | – | – | – | – | – | – | – |
| 17 | Class-set redundancy in similarity | – | n/a | – | – | – | ● | – | – |
| 18 | Array-shape / utilisation mapping | – | ● | ● | ● | ○ | ○ | ○ | ○ |
| 19 | Precision co-design | ○ | ● | ○ | ○ | ● | ○ | ○ | ○ |
| 20 | Memory technology selection | – | ○ | – | – | – | ○ | ● | ● |
| 21 | **Per-structure heterogeneous tech assignment** | – | – | – | – | – | – | – | – |
| 22 | Training / update mechanism | ● | – | ● | – | ● | ○ | ● | – |
| 23 | On-chip learning hardware | ○ | – | – | ○ | ● | ○ | – | – |
| 24 | Hardware-aware training | ● | – | ● | – | ● | – | ● | – |
| 25 | **Early exit / anytime inference** | – | – | – | – | – | – | – | – |
| 26 | Data-movement reduction | ○ | ● | ● | ● | ● | ● | ● | ● |
| 27 | **Event-count-defined timestep as control** | ● | – | – | – | – | – | – | – |

**Rows 11, 16, 21, 25, 27 are where the whole-row coverage is thin or empty.** Those are the candidate gap axes.

### 9.2 What existing work does *not* do

---

#### **G1 — No CIM work targets an *encoding-free* HDC pipeline.** Confidence: **high**

**Evidence.** Every HDC-CIM design in the surveyed set devotes its core machinery to encoding:
- MEMHD maps the projection matrix as EM into the array; its cycle/array savings are dominated by EM (560 → 7 arrays) **[S, Table II]**
- HDStream: **72% of power is encoding** **[S, §4.3]**; its instruction fusion exists to compose bind/bundle/permute
- CAMPRO: `bind2`, `bundle3/4`, hierarchical permutation, iM/CiM regions — the bulk of the paper
- Karunaratne 2021 and Li 2T2R: the *encoder* is the contribution
- ApproxQuery §VI-F states plainly that encoding dominates system energy below ~2000 classes

**NeuroHDC deletes this block entirely.** No iM, no CiM, no binding, no bundling, no permutation **[S, eq. (7)]**.

**Why this is a gap and not a triviality.** **[I]** The question *"what should a CIM array do for HDC when there is no encoder?"* has, as far as this survey reaches, never been asked. It changes the optimisation target: with encoding gone, the remaining consumers are (a) the SNN weight lookup, which is an *address-driven random read*, not an MVM, and (b) the similarity accumulation, whose latency is free (B5). Both of these violate the standard CIM value proposition (amortise an expensive analog read over a wide parallel MAC). **A CIM architecture for NeuroHDC must earn its keep on a completely different basis from every HDC-CIM paper published.** Articulating that basis rigorously is itself a defensible contribution.

**Risk.** A reviewer may read this as "you removed work, so there is less to accelerate." The response must be quantitative: show that the naive CIM port *loses* to the NeuroHDC ASIC, and explain why (G9).

---

#### **G2 — No work maps a hypervector whose index factorises into (neuron × timestep).** Confidence: **high**

`C_i ∈ {0,1}^{D_hv}` in NeuroHDC is really `C_i ∈ {0,1}^{T×n}` — a **matrix indexed by time**. The training equations confirm the slicing is semantically meaningful, not arbitrary: `∂L/∂S(t) = ∂L/∂h^u((t−1)n : t·n)` **[S, eq. (14)]**.

**Distinguishing from the nearest prior art — this must be stated precisely in any paper.**

| | Karunaratne TCAS-II 2021 / Li 2T2R 2024 | NeuroHDC |
|---|---|---|
| What "temporal" means | permutation depth in an N-gram over `N` consecutive samples | a **physical axis of the hypervector** |
| Temporal operator | `ρ^(N−1)I_1 ∗ ρ^(N−2)I_2 ∗ … ∗ I_N` | **none** — concatenation |
| Where time lives after encoding | dissolved into the HV by permutation+binding | **explicit**: dimension `(t−1)n + j` |
| Is a timestep addressable in the stored HV? | **no** | **yes**, as an `n`-bit slice |
| Is the encoding differentiable? | no | **yes** |

**[I]** That last-but-one row is the crux. In every prior in-memory ST-HDC design, once encoding is done the temporal structure is *gone* — you cannot point at a region of the array and say "this is timestep 7." In NeuroHDC you can. Unexplored consequences: time as an array dimension (rows = timesteps, columns = classes); per-timestep row activation schedules; temporal tiling; measuring and exploiting per-timestep class discriminability; temporal weighting of partial scores.

**Caveat.** HDStream's **vector folding** (§6.3) is the closest mechanism — segment, search, accumulate partials. **We must cite it and claim only the delta:** in HDStream folding is an architect's choice to save datapath width, with segment boundaries arbitrary; in NeuroHDC the segmentation is *imposed by the algorithm*, the boundaries carry *semantic* meaning (a timestep), and the segments arrive *sequentially in real time* rather than being read from a pre-arranged memory.

---

#### **G3 — Query-side (spike-driven) sparsity in the similarity computation is unexploited.** Confidence: **high**

**The algebraic observation.** For `h_t, C_{i,t} ∈ {0,1}^n`:
```
matches = Σ_m [h_m = C_m] = Σ_m [2·h_m·C_m − h_m − C_m + 1]
        = 2(h_t · C_{i,t}) − k_t − c_{i,t} + n
```
where `k_t = popcount(h_t)` (spikes at timestep `t`) and `c_{i,t} = popcount(C_{i,t})`.

Summing over `t`:
```
Score_i = n·T − Σ_t k_t − ‖C_i‖₁ + 2·(h · C_i)
```
`n·T` is constant; `Σ_t k_t` is **class-independent**; `‖C_i‖₁` is a **per-class constant known at load time**. Therefore:
```
argmax_i Score_i  ≡  argmax_i [ 2·(h · C_i) − ‖C_i‖₁ ]
```
and
```
h · C_i = Σ_t Σ_{j : S_j(t)=1} C_i[(t−1)n + j]
```

**[I] Consequence:** **only the bit positions where a neuron actually fired need to be read from class memory.** The XNOR array disappears; the operation becomes a spike-gated gather-and-accumulate plus a per-class constant subtracted once at the end. If the mean firing rate is `r`, class-memory activity scales as `r` rather than `1`.

**Why this is a genuine gap, not a rebrand:**
- **NeuroHDC** does the opposite — full `n`-bit XNOR + popcount every timestep for every class **[S, eq. (21)]**, because a `0↔0` match scores. The identity above shows those matches are *recoverable from constants*.
- **IMPULSE** exploits sparsity in the **input** spikes of the SNN (which weights to accumulate), not in the **output** spikes driving a similarity search **[S, §III]**.
- **CAMPRO TPBP** exploits **class-set** redundancy — bits identical *across classes*. That is query-**independent**. G3 is its **dual**: query-**dependent**, class-independent. The two are orthogonal and could in principle compose, but neither paper states the other.
- **ApproxQuery** reduces the *precision* of the match count, not the *number of positions touched*.

**Must be validated in Phase 1:** measure the actual firing rate `r` of NeuroHDC's `n=20` IF neurons on N-MNIST / DVS-Gesture / DVS-ASL. If `r ≈ 0.5` the benefit vanishes; if `r ≈ 0.1–0.3` it is large. **This number is currently unknown and the paper does not report it. Getting it is the single highest-value first experiment in the project.**

Secondary note: `‖C_i‖₁` is set by training. A learnable-HDC objective may or may not balance it across classes; if it is near-constant the bias term drops out entirely.

---

#### **G4 — Nobody has designed a CIM search whose latency is already free.** Confidence: **high**

Every surveyed HDC-CIM work optimises **search cycles**: MEMHD 80× fewer cycles / one-shot search **[S, §IV-E]**; CAMPRO single-cycle CAM search **[S, §II-B]**; HDStream AM overlapped with next-query encoding **[S, §3.1]**; ApproxQuery 2.8 ns **[S, Table X]**.

**In NeuroHDC search latency is structurally free** (B5): the `T` micro-searches are interleaved into an event stream whose duration is fixed by the sensor. **[I] The correct objective function is therefore energy-per-bit-of-class-memory-touched and area — under a constraint that the search be decomposable into `T` tiny activations.** That inverts the usual array-sizing logic (wide-and-parallel becomes *worse*, narrow-and-repeated becomes viable) and it means importing MEMHD's or CAMPRO's optimisation target would optimise a non-bottleneck.

---

#### **G5 — No HDC accelerator, CIM or otherwise, exploits anytime / early-exit classification.** Confidence: **high**

**[I]** Because the hypervector is built in temporal order, the partial score after `t < T` timesteps is a *meaningful prefix* of the final score — it is the similarity restricted to the first `t·n` dimensions. Conventional HDC cannot do this: `h` only exists once encoding completes.

Unexploited consequences: terminate inference when one class leads by a statistical margin; skip the remaining class-memory reads and remaining SNN work entirely; a margin comparator in the array periphery as a natural CIM peripheral. Note this *does* reduce latency and energy together, and it is the one mechanism that can beat B5's "latency is fixed by the event stream" — because ending early means **not ingesting the remaining events**.

**Caveats to check:** timesteps are event-count-normalised, so early exit truncates the *event budget*, not wall-clock. Accuracy-vs-exit-point must be characterised. Confusion-matrix data in NeuroHDC Fig. 4 suggests DVS-Gesture has systematically confusable pairs (Air Guitar↔Hand Clapping, Right-Arm-CCW↔Left-Hand-Wave) which would exit late or wrong.

---

#### **G6 — The array-mapping problem appears in the *inverse* form, and MEMHD's remedy is structurally blocked.** Confidence: **high**

| | MEMHD's problem | NeuroHDC's problem |
|---|---|---|
| Rows | `D ≈ 10 000` >> 128 rows → **overflow** → partition | per-activation query width = **`n` = 20** << 128 rows → **starvation** (15.6%) |
| Columns | `k = 10` classes << 128 columns → **7.81% utilisation** | same problem: `N` classes << columns |
| Remedy available | shrink `D`, spend freed columns on centroids | **blocked**: `D_hv = n·T` is pinned by accuracy (§3.8) |
| Cycles | 80× reduction is the win | **cycles are not a bottleneck** (G4) |

**[I]** NeuroHDC's version is: *how do you usefully fill an array when the query presented per activation is only 20 bits wide, that width is fixed by the algorithm, and the full 2000-bit query is spread over 100 sequential activations?* The obvious answers (pack multiple timesteps per activation; pack multiple classes per activation; pack multiple samples/batches; pack the SNN weights and class HVs into the same array) each trade against latency, buffering, or the temporal ordering that G5 depends on. **This trade space has not been characterised.** MEMHD's answer does not port, and simply adding centroids to NeuroHDC would be disallowed item #9.

Also unaddressed by anyone: NeuroHDC's own **65.1% macro utilisation** for class HVs (B4) and the acknowledged brittleness to `(D_hv, n)` changes **[S, §V-A]**.

---

#### **G7 — No per-structure heterogeneous memory-technology assignment for an SNN-HDC hybrid.** Confidence: **medium-high**

NeuroHDC has three memory populations with **radically different** R/W profiles:

| Structure | Size | Read rate | Write rate | Volatility need |
|---|---|---|---|---|
| `V_mem` | **55 B** | per event | **per event** | volatile; must be fast + infinite endurance |
| `W_s` | **10.24 kB** | **per event, random address** | once per task | non-volatile is ideal |
| `C_i` | `N × 250 B` | once per timestep, **sequential, single-pass** | once per task (Mode 1) or per adaptation (Mode 2) | non-volatile is ideal; **but Mode 2 writes** |

Every surveyed design picks **one** technology for everything. ApproxQuery compares technologies (STT-MRAM vs RRAM vs FeFET) but for a single structure — the HAM — and concludes that bitcell access mode must follow the ON/OFF ratio **[S, §IV-B2, Table II]**.

**[I]** The specific opening: NeuroHDC's asymmetry is *extreme and inverted relative to the SNN-CIM literature* — `V_mem` is 0.4% of the memory, where IMPULSE and SpikeSim assume it dominates. A principled assignment (e.g. volatile fast storage for the 55 B of `V_mem`; a high-endurance NVM for `W_s` read once per event; a write-once/read-many NVM for `C`) has not been done, and the **Mode-2 transfer-learning write cost and endurance on the class array has not been analysed by anyone.** Xiao's WAD-MB/BGC solve the *SRAM* version of that problem **[S, §IV]**; the NVM version is open.

**Honest caveat:** technology assignment alone is explicitly *not* an acceptable primary contribution (disallowed item #10). This is a supporting axis, valuable for a secondary contribution or for making a primary mechanism feasible.

---

#### **G8 — Event-count-defined timesteps as a hardware control signal.** Confidence: **medium**

NeuroHDC's timestep closes after `N_e` **events**, not after a fixed interval **[S, §III-B, §V-A]**. **[I]** So the array-activation schedule for the class memory is itself event-driven and data-dependent — the "clock" of the temporal axis is the sensor's activity. No surveyed CIM design has a data-dependent activation schedule of this kind. Implications: adaptive temporal resolution, interaction with early exit (G5), and buffering pressure if one wants to batch events within a timestep (G9).

**Honest caveat:** this is a mechanism enabler rather than a contribution on its own. Listed for completeness.

---

#### **G9 — The event-serial vs timestep-batched dataflow fork has never been analysed for a crossbar.** Confidence: **medium-high**

**[I] This is the most important *negative* technical finding in the whole analysis, and it must be settled early.**

In NeuroHDC, the SNN "matrix-vector multiply" `X(t) = W_s · D_flat(t)ᵀ` **[S, eq. (16)]** never actually occurs as an MVM in hardware. Each event is a single non-zero, so the computation decomposes into accumulating **one column of `W_s` per event** **[S, eq. (20)]**. There are two ways to put that on a crossbar:

**(a) Event-serial.** Fire the crossbar once per event with a one-hot input.
→ This is a memory read performed expensively: you pay wordline drive, bitline settling and an ADC conversion (or a sense amplifier per column) to retrieve `n = 20` stored 8-bit values that an SRAM read would have given you directly. **[I] There is a real risk this loses outright to the NeuroHDC SRAM baseline.** One-hot MVM is the pathological worst case for analog CIM amortisation.

**(b) Timestep-batched.** Accumulate events into a 512-entry count histogram (= the SumPooled frame), then do **one** multi-bit MVM per timestep.
→ Amortises the analog read over `N_e` events. But it **re-materialises the frame NeuroHDC deliberately refuses to build** **[S, §V-B]**, costing a 512-entry counter array, and it requires multi-bit input encoding (bit-serial DAC pulses), and it reintroduces a `N_e`-event latency bubble per timestep.

**Neither branch has been evaluated in the literature for an event-driven single-layer SNN.** IMPULSE is implicitly (a) but in *digital* CIM where a one-hot activation is genuinely cheap (a wordline enable, no ADC). SpikeSim assumes (b) with a materialised activation vector. Karunaratne/Li assume dense inputs.

**Why this matters for our contribution:** if the answer is (a)-in-digital-CIM, then the crossbar story for the SNN half collapses and the contribution must live in the temporal/query half. If the answer is (b), then the SumPool-as-address-generation insight (§3.3) becomes an architectural asset — the counter array *is* the frame, built for free from address decode. **Resolving this fork should precede any architecture proposal.**

---

### 9.3 Gaps ranked

| Rank | Gap | Confidence | Strength as a *primary* contribution | Note |
|---|---|---|---|---|
| 1 | **G3** query-side spike sparsity in similarity | high | **strong** — new mechanism, new algebra, spike-native, quantifiable | gated on measuring firing rate `r` |
| 2 | **G2** (neuron × timestep) factorised HV mapping | high | **strong** — opens time-as-array-dimension | must cite HDStream vector folding |
| 3 | **G5** anytime / early-exit inference | high | **strong**, and the only lever on latency | needs accuracy-vs-exit characterisation |
| 4 | **G6** inverse array-mapping problem | high | **medium** — good framing, needs a mechanism | risks looking like MEMHD-for-NeuroHDC |
| 5 | **G4** free-latency search reframing | high | **medium** — excellent motivation, weak as a mechanism | best used as the paper's motivation section |
| 6 | **G9** dataflow fork | med-high | **medium** — could be a strong analysis contribution | must be resolved regardless |
| 7 | **G1** encoding-free CIM | high | **framing**, not a mechanism | the paper's thesis statement |
| 8 | **G7** heterogeneous tech assignment | med-high | **weak alone** (disallowed #10) | good secondary contribution |
| 9 | **G8** event-count timesteps | medium | **weak alone** | enabler |

**[I] The most promising combinations appear to be G3 + G2 (a spike-driven, temporally-addressed class memory) with G5 as a secondary contribution and G4/G1 as the motivation.** This is stated as an observation about where the design space is open — **not** as a proposal. Candidate generation is deliberately deferred.

---

## 10. Constraints and invariants that any proposed architecture must respect

These are non-negotiable. Violating any one of them makes the design "not NeuroHDC" and destroys the premise.

1. **Never rate-collapse the spikes.** Any operation that reduces `{S_j(t)}` to `Σ_t S_j(t)` before similarity reproduces Spiking-HDC's information loss **[S, §III-A]** and forfeits NeuroHDC's accuracy advantage. Per-timestep partial scores may be accumulated — that is the original design — but the *spike identities* `(j,t)` must remain distinguishable up to the point of scoring.
2. **`D_hv = n × T` is not a free hyperparameter.** `T ≈ 100` from accuracy **[S, Fig. 3, Table I]**; `n ≈ 20` from cost. Any mechanism that needs `D_hv` to be adjustable for array fit must justify itself against §3.8.
3. **Preserve differentiability.** NeuroHDC's accuracy comes from joint gradient training through a differentiable encoder **[S, §III-C, §IV-E]**. Introducing a non-differentiable in-array operation between the spikes and the score forces the two-stage training that NeuroHDC calls "obviously suboptimal."
4. **Keep native AER.** The hardware must not require a materialised `T×P×H×W` tensor **[S, §V-B]**; that buffer is precisely what NeuroHDC eliminates. If a mechanism needs partial materialisation (G9 branch (b)), its cost must be counted explicitly.
5. **SumPool must stay free.** It is address truncation in the address generator **[S, eq. (19)]**, not a compute stage. Any design that turns it into arithmetic has regressed.
6. **`V_mem` is 55 bytes.** Do not import a membrane-potential-bottleneck solution (B6). If a proposal's value rests on `V_mem` traffic, it is solving the wrong problem for `n = 20`.
7. **Latency is set by the event count** (B5). Cycle-count improvements are not a headline result unless coupled to early exit (G5). Report **energy/inference and area** as primary.
8. **Support both training modes.** Mode 1 (off-chip joint gradient) and Mode 2 (on-chip one-shot + retraining, eq. 17–18) **[S, §IV-D]**. Mode 2 implies **writes to the class memory**, which is an endurance and energy question in NVM that SRAM baselines never face.
9. **Do not introduce a new training algorithm unless forced.** If in-array approximation makes hardware-aware training necessary, follow the precedent of ApproxQuery (α/β compensation) rather than inventing a new learning rule — and note that the ability to fold hardware non-idealities into training is a *precedent*, not a novelty.
10. **Complexity must not be hidden outside the array.** ADCs, DACs, sense amplifiers, accumulators, shift/permutation logic, buffers, control FSMs, write drivers and the `N`-way argmax must all be counted. CAMPRO explicitly budgets TPBP at 3.73% of area **[S, §IV-B]**; ApproxQuery shows the memory array is 95% of its power with peripherals at 5% **[S, Fig. 12]**. We must be equally explicit.
11. **The fair baseline is NeuroHDC's own ASIC**, not a strawman digital HDC engine. It is 12.68 kB, ~50% smaller than HyperSpikeASIC/Spiking-HDC, and an FPGA baseline is published for reproduction **[S, §VI-C, Table IV]**. Beating it is the bar.
12. **Competitive awareness.** The NeuroHDC authors (Yu, Wu, Chen, Zhang, Liu at NUAA) already own a memristor HAM with hardware-aware training (TC 2024), LAHDC, AttnACQ, and a fully-learnable HDC framework; Bi Wu's research area is spintronic in-memory computing. **Assume "NeuroHDC class HVs in an MRAM/RRAM approximate-query HAM" is theirs.** Our contribution should live where they have not built: the event-driven temporal dataflow, not the associative-memory circuit.

---

## 11. Open questions to resolve before proposing anything

| # | Question | Why it blocks | How to answer |
|---|---|---|---|
| Q1 | What is the **mean output firing rate `r`** of the `n=20` IF neurons, per dataset? | G3's entire value scales with `1−r` (or `r`). Unreported in the paper. | Reimplement NeuroHDC in PyTorch/snnTorch; instrument `S_j(t)` |
| Q2 | Is firing rate **uniform across timesteps and neurons**, or clustered? | Determines whether a spike-gated access pattern is bursty (bad for array activation) or smooth | Same experiment; plot `k_t` over `t` |
| Q3 | What is `N_events` per sample on each dataset, and the resulting `N_e`? | Sets the event:timestep work ratio, hence whether G9(b) batching amortises | Dataset statistics |
| Q4 | How is `‖C_i‖₁` distributed across classes after Mode-1 training? | Decides whether G3's bias term is free | Train and inspect |
| Q5 | **Accuracy vs. early-exit timestep** curve | G5 viability | Truncate `T` at inference on a trained model |
| Q6 | Per-timestep **discriminability** — do early timesteps carry less information? | G2/G5; possible non-uniform temporal mapping | Per-timestep score contribution analysis |
| Q7 | Does a **per-timestep `Sign()`** approximation (the natural NeuroHDC analogue of ApproxQuery's tiling) preserve accuracy? | Tests whether the obvious composition even works | Simulate `Σ_t Sign(h_t·C_{i,t})` |
| Q8 | **G9 fork:** event-serial vs timestep-batched crossbar — which wins? | Determines whether the SNN half has any CIM story at all | Analytical energy model + NeuroSim/CACTI |
| Q9 | Full area/energy breakdown of the NeuroHDC ASIC by block | We only have totals; we need to know what we are actually attacking | Reimplement in Verilog; synthesise (Yosys/SkyWater 130 as published, or a modern PDK) |
| Q10 | Mode-2 class-HV **write volume and frequency** during transfer learning | NVM endurance/energy feasibility (G7) | Instrument eq. (18) during transfer experiments |

**[I]** Q1 and Q8 are the critical path. Everything in the top three gaps depends on one or both.

---

## 12. Reference index

### Attached corpus

| Key | Full citation |
|---|---|
| **NeuroHDC** | T. Yu, B. Wu, K. Chen, C. Yan, G. Zhang, W. Liu, "Neuromorphic Hyperdimensional Computing for Efficiently Processing Event-Based Data," *IEEE TVLSI*, vol. 34, no. 8, pp. 2483–2494, Aug. 2026. DOI 10.1109/TVLSI.2026.3695182 |
| **IMPULSE** | A. Agrawal, M. Ali, M. Koo, N. Rathi, A. Jaiswal, K. Roy, "IMPULSE: A 65nm Digital Compute-in-Memory Macro with Fused Weights and Membrane Potential for Spike-based Sequential Learning Tasks," arXiv:2105.08217, 2021 |
| **MEMHD** | D. Y. Kang, Y. H. Oh, C. Hwang, J. Kim, K. E. Jeon, J. H. Ko, "MEMHD: Memory-Efficient Multi-Centroid Hyperdimensional Computing for Fully-Utilized In-Memory Computing Architectures," arXiv:2502.07834, 2025 |
| **HDStream** | R. Antonio, X. Yi, Y. Deng, F. Kong, J. Yin, M. Verhelst, "HDStream: An Energy-efficient 7.98 TBOPS/W Hyperdimensional Computing Streaming Processor," *GLSVLSI '26*, pp. 115–121. DOI 10.1145/3787109.3815219 |
| **HDC-SNN** | A. Xiao, J. Yang, W. Yang, X. Zhang, Y. He, Z. Yang, L.-R. Zheng, Z. Zou, "A 40-nm Sub-mJ/Transfer HDC-SNN Hybrid Processor Enabling On-Chip Few-Shot Transfer Learning for IoT Applications," *IEEE TCAS-AI*, vol. 3, no. 3, pp. 176–189, June 2026. DOI 10.1109/TCASAI.2026.3658593 |
| **CAMPRO** | Y. He, T. Hu, A. Xiao, F. Yang, H. Zhang, L.-R. Zheng, Z. Zou, "CAMPRO: A CAM-Based Processing-in-Memory Processor for Hyperdimensional Computing," *IEEE TCAS-I*, vol. 73, no. 6, pp. 4232–4245, June 2026. DOI 10.1109/TCSI.2025.3634760 |
| **ApproxQuery** | T. Yu, B. Wu, K. Chen, G. Zhang, W. Liu, "Memristor-Based Approximate Query Architecture for In-Memory Hyperdimensional Computing," *IEEE TC*, vol. 73, no. 11, pp. 2605–2618, Nov. 2024. DOI 10.1109/TC.2024.3441861 |

### Key section pointers

| Topic | Where |
|---|---|
| NeuroHDC encoding equation | NeuroHDC §III-A eq. (7) |
| NeuroHDC information-loss argument vs predecessors | NeuroHDC §III-A eq. (5), (6) |
| Event→frame conversion, SumPool, event-count timesteps | NeuroHDC §III-B eq. (8), Fig. 2 |
| `n` vs `T` accuracy trade-off | NeuroHDC §IV-B1 Fig. 3; §IV-B2 Table I |
| Joint training / gradients | NeuroHDC §III-C eq. (10)–(16) |
| Transfer learning (Mode 2) | NeuroHDC §IV-D eq. (17), (18); Fig. 5 |
| Dual-mode discussion | NeuroHDC §IV-E |
| Accelerator block diagram | NeuroHDC §V-A Fig. 6 |
| Address generation (SumPool in HW) | NeuroHDC §V-B eq. (19) |
| Per-event accumulation | NeuroHDC §V-B eq. (20) |
| Per-timestep query accumulation | NeuroHDC §V-B eq. (21) |
| Latency independent of `T` | NeuroHDC §V-C |
| PIS future-work note | NeuroHDC §VI-D |
| Fused `W_MEM`/`V_MEM`, staggered mapping | IMPULSE §II, Fig. 3 |
| In-memory SNN instruction set | IMPULSE §II-B, Fig. 5 |
| Sparsity → EDP | IMPULSE §III, Fig. 11 |
| Multi-centroid init and allocation | MEMHD §III-A |
| Quantisation-aware iterative learning | MEMHD §III-C eq. (4)–(6) |
| Cycles / arrays / utilisation | MEMHD §IV-E Table II |
| Bundler MSB trick | HDStream §3.1, Fig. 3b |
| Hardware loop counters / streaming | HDStream §3.2 |
| Vector folding | HDStream §3.3 |
| Area/power breakdown | HDStream §4.3, Fig. 9 |
| Spiking HDC encoder (rate-based) | HDC-SNN §II-C eq. (1)–(4) |
| WAD-MB | HDC-SNN §IV-A, Fig. 9 |
| BGC | HDC-SNN §IV-B, Fig. 10–11 |
| SWL 6T cell + column search | CAMPRO §III-A, Fig. 4 |
| Approximate bundling | CAMPRO §III-D2, Fig. 7, Table II |
| Hierarchical permutation | CAMPRO §III-D3, Fig. 5 |
| TPBP (GRB/CRB) | CAMPRO §IV, Fig. 10–11 |
| Approximate query formulation | ApproxQuery §III-A eq. (6) |
| Accuracy collapse without matched training | ApproxQuery §III-B Table I |
| Learnable α | ApproxQuery §III-C eq. (8)–(9) |
| Row tile / bitcell / ML discharge | ApproxQuery §IV-B, Fig. 4–6 |
| Delay-based merging + WTA | ApproxQuery §IV-C, §IV-D |
| Device variation and β compensation | ApproxQuery §V, eq. (12)–(14) |
| Encoding vs query energy crossover | ApproxQuery §VI-F, Fig. 13 |

---

## 13. Phase 1 — Firing-characteristics measurement plan

**Purpose.** Gap **G3** (query-side spike sparsity) and, to a lesser degree, **G5** (early exit) and **G2** (temporal mapping) depend on quantities the NeuroHDC paper never reports: the statistics of the `20 × 100` output spike raster `S ∈ {0,1}^{n×T}`. This section specifies exactly what must be built and measured, before any architecture is proposed.

**This section proposes no architecture.** It defines measurements and decision criteria only.

### 13.1 Code and checkpoint availability

**Searched:** GitHub (author names, paper title, group), Weiqiang Liu's NUAA faculty page, the TVLSI paper itself, and the two predecessor works.

| Item | Status | Evidence |
|---|---|---|
| Official NeuroHDC code | **Not found** | No repository link, no data-availability statement, and no footnote in the TVLSI paper; nothing under the authors' names or NUAA group pages |
| NeuroHDC pretrained checkpoints | **Not found** | — |
| NeuroHDC RTL / Verilog | **Not found** | §VI-A describes the flow (Yosys + SkyWater 130 + OpenROAD + PrimeTime) but releases nothing |
| Spiking-HDC (ISCAS 2024, NeuroHDC ref [7]) | **Not found** | — |
| HyperSpikeASIC (TCAD 2023, ref [6]) | **Not found** | — |
| LeHDC (ref [25]) / QuantHD (ref [24]) | Available, third-party | Useful only for the class-HV training head |

**Conclusion [I]:** this is a **full reimplementation**, not a reproduction. Consequence: every firing statistic we measure is a property of *our* trained model. The only defence is accuracy-matching against the paper's Table II and reporting sensitivity to the unspecified hyperparameters (§13.3). **This must be stated plainly in any resulting paper.**

### 13.2 What is needed to obtain the raster

| Need | Source | Status |
|---|---|---|
| N-MNIST | SpikingJelly `spikingjelly.datasets.n_mnist.NMNIST` or `tonic.datasets.NMNIST` | Available |
| DVS-Gesture (DVS128) | SpikingJelly `DVS128Gesture` or `tonic.datasets.DVSGesture` | Available; requires manual download of the IBM archive |
| ASL-DVS | `tonic.datasets.ASLDVS`; original release at github.com/PIX2NVS/NVS2Graph (Dropbox + Google Drive links) | Available; ~100,800 samples, 24 classes, ~100 ms each |
| Equal-event-count binning | **SpikingJelly `split_by='number'`** integrates events into `frames_number` bins of equal event count | **Exact match to NeuroHDC §III-B** ("we divide them uniformly, ensuring an equal number of events in each"). Use it rather than reimplementing. |
| SumPool | `torch.nn.functional.avg_pool2d(x, β) * β²`, or a custom sum-pool | Trivial |
| IF neuron + surrogate gradient | SpikingJelly `neuron.IFNode` + `surrogate.*` | Available. NeuroHDC ref [11] *is* the SpikingJelly paper (Fang et al., ICCV 2021), so the neuron semantics should align by construction. |
| 8-bit QAT on `W_s` | Custom STE (NeuroHDC ref [36] = Jacob et al.) | Small |
| Binary class-HV head | Custom STE sign, per eq. (10) | Small |

### 13.3 Reproducibility audit — specified vs. unspecified

#### Specified by the paper **[S]**

| Parameter | Value | Where |
|---|---|---|
| SNN topology | single-layer fully connected | §III-B |
| Neuron model | **IF** (not LIF), `V_reset = 0`, hard reset | §II-A eq. (1)–(2) |
| Spiking neurons `n` | **20** default | §IV-B1 |
| Timesteps `T` | **100** default (max) | §IV-A, §IV-B |
| `D_hv` | `n × T` = **2000** | §IV-B1 eq. (7) |
| Input neurons | **512**, frame `R^{2×16×16}` | §IV-A |
| Timestep partitioning | uniform by **event count**, `N_e` events per timestep | §III-B, §V-A |
| Pooling | **SumPool** over non-overlapping windows, factor `β` | §III-B, Fig. 2 |
| Weight precision | **int8 signed**, via QAT | §III-C |
| Encoding | direct concatenation, eq. (7) | §III-A |
| Query | inner product / XNOR-popcount, argmax | eq. (9), (21) |
| Class HVs | `C = Sign(W_c)`, `W_c` FP latent, gradient-trained | eq. (10) |
| Sign() backward | gradient approximation "consistent with previous work [10]" | §III-C |
| `Θ()` backward | surrogate gradient, ref [35] = Neftci et al. | §III-C |
| Loss | cross-entropy(Score, one-hot label) | §III-C |
| Optimiser | **Adam** | §IV-A |
| DVS-Gesture | 11th class "Other" **excluded** → 10 classes | §IV-A |
| ASL-DVS | 24 classes, **random 80/20** split | §IV-A |
| Transfer learning | eq. (17) one-shot, eq. (18) retraining with rate `α ∈ (0,1)` | §IV-D |

#### Unspecified — must be chosen, swept, or inferred **[E]**

| # | Missing | Risk to the measurement | Plan |
|---|---|---|---|
| **U1** | **`V_thresh` value** | **Critical.** Firing rate is a direct function of threshold relative to accumulated drive. The paper exposes `V_thresh` only as a configuration register (§V-A) and never gives a number. | **Sweep.** Train at several thresholds; report `(accuracy, r)` as a Pareto front; quote `r` at the accuracy-matched point |
| **U2** | `β` per dataset | Affects drive magnitude, hence `r` | Derive from sensor resolution → `2×16×16`: N-MNIST 34×34 (crop/pad to 32 → `β=2`), DVS-Gesture 128×128 (`β=8`), ASL-DVS 240×180 (crop then `β`); document the choice |
| **U3** | Surrogate function and its width | Moderate — affects trained solution | Default ATan (SpikingJelly), width 2.0; sanity-check against sigmoid/triangular |
| **U4** | Learning rate, batch size, epochs, weight decay, LR schedule | Moderate | Standard values; document; verify accuracy match |
| **U5** | Input scaling of the SumPooled count | **High** — a count image has unbounded magnitude; whether it is fed raw, normalised, or clipped changes drive and therefore `r` | Sweep {raw, per-sample normalised, clipped}; pick the one that reproduces accuracy |
| **U6** | Bias term in the FC layer | Low | eq. (16) shows `X(t) = W_s · D_flat(t)ᵀ` with **no bias**; assume none |
| **U7** | Handling of samples with fewer than `T` events | Low but must be deterministic | Define: pad with empty timesteps; log how many samples are affected |
| **U8** | `N_e` per dataset | — | **Derived per sample**: `N_e = ⌊N_events / T⌋`. Record the distribution; it is itself a result |
| **U9** | ASL-DVS split seed | Low | Fix a seed; report it |
| **U10** | The "small" vs "large" accelerator configurations | Low for Phase 1 | Table III was not recoverable from the PDF text extraction. **Re-extract Tables II and III from the original PDF before accuracy-matching.** |
| **U11** | Exact per-dataset accuracies (Table II) | **High** — this is the accuracy-match target | Same as U10. Until recovered, use published numbers for HyperSpikeASIC/Spiking-HDC as a lower bound |

> **⚠️ Action item before coding: re-extract Tables I, II, III from the NeuroHDC PDF.** The text extraction used for this document lost all table bodies. The accuracy targets and the two hardware configurations live there.

### 13.4 Statistics to extract

Let `S ∈ {0,1}^{M×T×n}` over `M` test samples, `n = 20`, `T = 100`.
Let `k_{m,t} = Σ_j S[m,t,j]` (spikes in timestep `t` of sample `m`).

| ID | Statistic | Definition |
|---|---|---|
| **F1** | Global firing rate | `r = (1/(M·T·n)) Σ_{m,t,j} S[m,t,j]` |
| **F2** | Spikes per sample | `s_m = Σ_{t,j} S[m,t,j]`; report mean, std, P10/P50/P90/P99 |
| **F3** | Per-sample rate distribution | `r_m = s_m/(n·T)`; histogram + P10/P50/P90/P99 |
| **F4** | Per-neuron rate | `r_j = (1/(M·T)) Σ_{m,t} S[m,t,j]`; bar chart over `j = 1…20` |
| **F5** | Per-timestep rate | `r_t = (1/(M·n)) Σ_{m,j} S[m,t,j]`; line plot over `t = 1…100` |
| **F6** | **Silent-timestep fraction** | `σ = (1/(M·T)) Σ_{m,t} 1[k_{m,t} = 0]` |
| **F7** | Active-neuron fraction | per sample `a_m = (1/n) Σ_j 1[Σ_t S[m,t,j] > 0]`; plus globally-dead neurons `1[Σ_{m,t} S = 0]` |
| **F8** | `k_t` distribution | histogram of `k_{m,t}` over all `(m,t)`; mean, mode, max |
| **F9** | **Burstiness ratio** | `B = σ / (1−r)^n` — observed silence vs. the independent-Bernoulli prediction. `B ≈ 1` ⇒ neurons fire independently; `B ≫ 1` ⇒ correlated/bursty |
| **F10** | Silent-run lengths | distribution of maximal runs of consecutive `t` with `k_{m,t} = 0` |
| **F11** | **Zero-group fraction `z(g)`** | For group size `g`, the fraction of groups containing no spike. Three families: **spatial** (`g` consecutive neurons within one timestep, `g ∈ {1,2,4,5,10,20}`), **temporal** (`g` consecutive timesteps for one neuron, `g ∈ {1,2,4,5,10,20,25,50,100}`), **2D tiles** (`g_j × g_t`) |
| **F12** | Class-HV norms | `‖C_i‖₁` for each class; mean, spread, and `max−min` |
| **F13** | Per-timestep discriminability | contribution of each timestep `t` to the score margin between the top-1 and top-2 classes |
| **F14** | Accuracy vs. truncation | accuracy when scoring is stopped at `T′ ∈ {10,20,…,100}` |
| **F15** | Event-count statistics | `N_events` per sample, derived `N_e`; mean/P10/P50/P90 per dataset |
| **F16** | Score-identity residual | numerical check that `2(h·C_i) − ‖C_i‖₁` ranks classes identically to `Σ XNOR` (see §9.2/G3). Must be **exactly** zero-disagreement |

### 13.5 Which statistics actually decide the question

**[I] The headline number is not `r`. It is `z(g)` — the zero-group fraction as a function of access granularity.**

Reason: gap G3 says only spike positions need to be read from class memory. But memory is not bit-addressable for free. If class memory is read at word granularity `g = n = 20` bits per timestep, a timestep with **even one** spike must still be fetched, so the achievable saving is `σ` (F6), not `1−r` (F1). These can differ enormously:

> With `r = 0.2` and independent neurons, `σ = 0.8²⁰ ≈ 1.2%`. A 20× reduction in bits that matter would yield essentially **zero** saving at word granularity.

So the decision chain is:

| Question | Statistic | Threshold for "worthwhile" |
|---|---|---|
| Is there *any* exploitable sparsity? | **F1** `r` | `r < 0.35` ⇒ ≥1.5× ideal bit-level reduction. `r ≈ 0.5` ⇒ **G3 is dead** in its naive form; go to E4 |
| Does coarse gating work at all? | **F6** `σ`, **F9** `B` | `B ≫ 1` and `σ > 0.2` ⇒ word-level gating viable |
| What granularity pays? | **F11** `z(g)` | The `(g, z(g))` curve versus address/control overhead per fetched group. **This is the table the architecture decision rests on.** |
| Can dense samples break the energy budget? | **F3** P90/P99 | Worst-case provisioning; a long tail means the design cannot bank on the mean |
| Is static compression available instead? | **F4**, **F7** | Near-dead neurons ⇒ row pruning (static, not event-driven — cheaper but a weaker contribution) |
| Is early exit (G5) viable? | **F14**, **F13** | Accuracy within ~1% at `T′ ≤ 50` ⇒ real latency *and* energy lever |
| Does the G3 bias term cost anything? | **F12** | Narrow `‖C_i‖₁` spread ⇒ the constant nearly cancels and can be folded cheaply |
| Is the identity sound? | **F16** | Must be exact; a non-zero disagreement invalidates G3 outright |

**[I] Second-order but decisive: is `r` malleable?** Even if the natural `r ≈ 0.5`, a firing-rate penalty `L = L_CE + λ·r` may push `r` down at negligible accuracy cost. **That matters more than the natural value**, because it converts G3 from "measure and hope" into a co-design knob. Note that spike-rate regularisation is standard SNN practice and is **not itself a contribution** — it is an enabler that must be reported honestly as such.

**[I] Prior expectation to be tested, not assumed:** NeuroHDC's hypervector feeds a binary FC classifier trained with STE. BNN training generally favours balanced activations, so there is a real prior that training settles near `r ≈ 0.5`. **We should expect G3 to fail on the natural model and be decided by E4.** Planning for that outcome now avoids motivated reasoning later.

### 13.6 Experiment list

| ID | Experiment | Output |
|---|---|---|
| **E0** | Recover Tables I–III from the NeuroHDC PDF | accuracy targets, hardware configs |
| **E1** | Train NeuroHDC (`n=20, T=100`) on N-MNIST, DVS-Gesture, ASL-DVS; accuracy-match Table II | checkpoints + accuracy table |
| **E2** | Capture test-set rasters; compute **F1–F12**, **F15**, **F16** | `artifacts/tables/firing_stats.csv`, figures |
| **E3** | **Granularity sweep** — `z(g)` for spatial, temporal and 2D groupings | `artifacts/tables/granularity.csv`, the headline plot |
| **E4** | **Sparsity malleability** — sweep `λ ∈ {0, 1e-4 … 1e-1}` on a firing-rate penalty; Pareto of accuracy vs `r` | `accuracy_vs_rate.csv` + Pareto plot |
| **E5** | **`V_thresh` sweep** (U1) — train across a threshold grid; Pareto of accuracy vs `r` | `threshold_sweep.csv` |
| **E6** | **Early exit** (G5) — **F13**, **F14** | `early_exit.csv` + accuracy-vs-`T′` plot |
| **E7** | **`(n, T)` sensitivity** — reproduce NeuroHDC Fig. 3 and Table I, and report `r` at each point | confirms our model behaves like theirs; also tells us whether `r` depends on `(n,T)` |
| **E8** | **Robustness of conclusions** — repeat E2 over ≥3 seeds; report spread on `r`, `σ`, `z(g)` | prevents a single-seed conclusion |

### 13.7 Implementation specification for Claude Code

#### Repository layout

```
cim-neurohdc/
├── README.md                      # this research document (do not overwrite)
├── pyproject.toml
├── configs/
│   ├── base.yaml                  # shared defaults
│   ├── nmnist.yaml
│   ├── dvsgesture.yaml
│   └── asldvs.yaml
├── src/neurohdc/
│   ├── __init__.py
│   ├── config.py                  # dataclass config + YAML load + hash
│   ├── data.py                    # dataset loaders, equal-event-count binning, SumPool
│   ├── neuron.py                  # IF neuron with configurable V_thresh, hard reset
│   ├── quant.py                   # int8 QAT STE for W_s; sign-STE for class HVs
│   ├── model.py                   # NeuroHDC: SNN -> raster -> concat -> binary head
│   ├── train.py                   # Mode-1 joint training loop (+ optional rate penalty)
│   ├── transfer.py                # Mode-2 eq.(17)/(18) one-shot + retraining
│   ├── capture.py                 # inference with raster capture
│   ├── stats.py                   # F1-F12, F15
│   ├── granularity.py             # F11 z(g) sweep
│   ├── earlyexit.py               # F13, F14
│   ├── identity.py                # F16 score-identity verification
│   └── plots.py                   # all figures
├── scripts/
│   ├── 00_prepare_data.py
│   ├── 01_train.py
│   ├── 02_capture_rasters.py
│   ├── 03_analyze_firing.py
│   ├── 04_granularity_sweep.py
│   ├── 05_early_exit.py
│   ├── 06_threshold_sweep.py
│   ├── 07_rate_penalty_sweep.py
│   └── 08_make_report.py
├── artifacts/
│   ├── checkpoints/   rasters/   tables/   figures/   logs/
└── tests/
    ├── test_binning.py
    ├── test_sumpool.py
    ├── test_if_neuron.py
    ├── test_encoder_shape.py
    ├── test_score_identity.py
    └── test_quant.py
```

#### Module contracts

**`data.py`**
- `build_dataset(name, split, T, beta, cfg) -> Dataset`
- Yields `(frames, label, n_events)` where `frames: int32 [T, 2, H, W]` with `H=W=16`, and `n_events: int` = total events in the sample.
- **Must** bin by equal event count (SpikingJelly `split_by='number'`), never by time.
- **Must** apply SumPool as a *sum* (not average): `avg_pool2d(x, beta) * beta**2`, or an explicit sum.
- **Must** record and return `N_e = n_events // T` per sample.
- Input-scaling mode is a config field (U5): `{"raw", "per_sample_norm", "clip"}`.

**`neuron.py`**
- `IFLayer(n_in=512, n_out=20, v_thresh: float, w_bits: int = 8)`
- `forward(frames: [B, T, 512]) -> raster: [B, T, 20]` (uint8/bool) **and** `v_trace: [B, T, 20]` (optional, for diagnostics)
- Hard reset to 0 on spike; no leak; no bias.

**`model.py`**
- `NeuroHDC(n, T, n_classes, v_thresh, ...)`
- `forward(frames) -> (scores: [B, N], raster: [B, T, n])`
- Encoder is `raster.flatten(1)` — **assert** `D_hv == n*T` and assert no other operation sits between the raster and the head.
- Head: `scores = h @ sign(W_c).T` with STE on `sign`.
- Expose `class_hv() -> uint8 [N, T, n]` and `class_l1() -> int32 [N]`.

**`capture.py`**
- `capture(model, loader, out_path)` → writes `.npz` + `.json` sidecar.
- `.npz` keys: `raster uint8 [M,T,n]`, `labels int16 [M]`, `pred int16 [M]`, `scores float32 [M,N]`, `n_events int32 [M]`, `N_e int32 [M]`, `class_hv uint8 [N,T,n]`, `class_l1 int32 [N]`.
- `.json` sidecar: dataset, split, `n`, `T`, `beta`, `v_thresh`, `lambda_rate`, seed, git SHA, config hash, test accuracy, package versions.
- Bit-pack `raster` only if size becomes a problem; document if so.

**`stats.py`** — `compute_all(npz_path) -> dict` implementing F1–F12, F15 exactly as defined in §13.4. Emits a tidy CSV (one row per `(dataset, seed, config, statistic, value)`).

**`granularity.py`** — `zero_group_fraction(raster, axis, g) -> float` for `axis ∈ {"neuron","time","2d"}`. Sweeps the `g` grids listed in F11. Emits `granularity.csv` with columns `dataset, seed, axis, g_neuron, g_time, z, ideal_reduction, ...`.

**`identity.py`** — `verify(raster, class_hv, class_l1)`: compute (a) `Σ_m XNOR(h, C_i)` and (b) `2(h·C_i) − ‖C_i‖₁` for every sample and class; assert the **argmax agrees on 100% of samples** and report the exact count of disagreements. **This test must pass before any conclusion from G3 is trusted.**

#### Required outputs

**Tables** (CSV in `artifacts/tables/`, plus a Markdown digest):
1. `accuracy_match.csv` — our accuracy vs. NeuroHDC Table II, per dataset
2. `firing_stats.csv` — F1–F12, F15, per dataset × seed
3. `granularity.csv` — F11 (**the headline table**)
4. `threshold_sweep.csv` — E5 Pareto
5. `rate_penalty_sweep.csv` — E4 Pareto
6. `early_exit.csv` — F14
7. `nt_sensitivity.csv` — E7, reproducing Fig. 3 / Table I plus `r`
8. `identity_check.csv` — F16, must show zero disagreements

**Figures** (PDF + PNG in `artifacts/figures/`):
1. **`raster_examples.pdf`** — 3–6 raw `20×100` rasters per dataset, one per class, as black/white dot plots. *Look at these before trusting any aggregate.*
2. `per_neuron_rate.pdf` — bar chart, `r_j` over the 20 neurons (F4)
3. `per_timestep_rate.pdf` — `r_t` over 100 timesteps (F5)
4. `kt_histogram.pdf` — distribution of `k_t`, overlaid with `Binomial(20, r)` to visualise F9
5. **`granularity_curve.pdf`** — `z(g)` vs `g` for all three grouping families (**headline figure**)
6. `sample_rate_hist.pdf` — distribution of `r_m` with P10/P50/P90/P99 marked (F3)
7. `accuracy_vs_rate.pdf` — E4 + E5 Pareto fronts on shared axes
8. `early_exit.pdf` — accuracy vs `T′` (F14)
9. `class_l1.pdf` — `‖C_i‖₁` per class (F12)

**Report:** `08_make_report.py` assembles `artifacts/REPORT.md` with every table, every figure, the config hashes, seeds, git SHA, and an explicit **"decision"** section answering, in order, the questions in §13.5.

#### Engineering requirements

- Determinism: seed everything; log seeds; run E2/E3 over ≥3 seeds (E8).
- Every artifact carries the config hash and git SHA in its sidecar; no un-traceable numbers.
- `tests/test_score_identity.py` runs on synthetic random `h`, `C` before any real data touches it.
- `tests/test_binning.py` asserts every timestep bin holds `N_e` events (± the remainder).
- `tests/test_sumpool.py` asserts total event count is conserved by SumPool.
- No CUDA assumption; must run on CPU for small sweeps.
- Runtime budget: ASL-DVS has ~100 k samples — subsample the test split for E2/E3 if needed, and **record the subsample size**.

### 13.8 Decision gate

Phase 1 concludes with an explicit written verdict on each of:

1. **G3 viable as-is?** — requires `r` low enough **and** `z(g)` favourable at a granularity whose address overhead is affordable.
2. **G3 viable with co-design?** — E4 shows `r` is malleable to a useful level at acceptable accuracy cost.
3. **G3 dead?** — `r ≈ 0.5`, `B ≈ 1`, and E4 shows accuracy collapses when `r` is pushed down. **If so, say so, and return to §9.3 to build the architecture on G2/G5/G6 instead.**
4. **G5 viable?** — E6 accuracy-vs-`T′` curve.
5. **Any surprises** in F4/F5 (dead neurons, non-uniform temporal structure) that open an axis not currently in §9.

### 13.9 Results — **[E] MEASURED** (N-MNIST, DVS-Gesture; DVS-ASL not run — see below)

> **⚠️ SUPERSEDED for DVS-Gesture.** The DVS-Gesture column below was
> measured on a model that reached only 58.75–60.42% test accuracy against
> the paper's 87.5%, via a training run with a methodological flaw
> (test-set-based model selection) and an input-scaling choice that departed
> from the paper's own eq. (16). **§13.10 below reports a corrected,
> accuracy-improved re-measurement (82.36%±2.08% mean / 84.58% best seed,
> across 3 seeds) that supersedes every DVS-Gesture number in this table.**
> This table is kept, not deleted, as the historical record; do not cite its
> DVS-Gesture column as representative of NeuroHDC. **The N-MNIST column is
> unaffected and still current.**

Full detail, methodology, per-sample data, plots, and raw rasters are in the
companion directory **`phase1_firing_characterization/`**
(`firing_rate_results.md` is the authoritative long-form report; this table
is a summary of it). **DVS-ASL was not measured** — its data is not present
in this environment (blocker B10 remains unresolved: external download
required), so its column is left `[E]` (still unmeasured), not estimated or
assumed.

Tables I–IV of the NeuroHDC paper, which blocker B4 previously listed as
unrecoverable from the PDF text extraction, **were recovered** in this pass
by reading the PDF's rendered page images directly. Table I/III give
`n=20, T=100` accuracy targets of **N-MNIST 97.28%** and **DVS-Gesture
87.5%**, used below as the accuracy-match targets. B4 is resolved for
Tables I–III; B10 (DVS-ASL data) is not.

| Statistic | N-MNIST | DVS-Gesture | ASL-DVS |
|---|---|---|---|
| Accuracy (ours vs. paper Table I/III, `n=20,T=100`) | **94.91%** vs. 97.28% (−2.37 pp) | **60.42%** vs. 87.5% (−27.1 pp; not accuracy-matched, see limitations) | **[E]** not measured |
| F1 — global firing rate `r` | **0.1869** | **0.1053** | **[E]** |
| F2 — spikes/sample (mean, P10/P50/P90) | 373.9 / 311 / 368 / 447 | 210.6 / 117 / 183 / 369 | **[E]** |
| F3 — per-sample rate mean/median/std/P10/P90/CV | 0.187/0.184/0.027/0.156/0.223/**0.143** | 0.105/0.091/0.047/0.059/0.185/**0.445** | **[E]** |
| F4 — per-neuron rate spread; dead neurons | 0.051–0.349, Gini 0.225; **0 dead / 20** | 0.039–0.158, Gini 0.178; **0 dead / 20** | **[E]** |
| F5 — per-timestep rate profile | non-uniform: low (~0.13) through t≈35, peak ~0.26 at t≈60, falls to ~0.13 by t=99 | flat after a t=0 cold-start transient (r₀=0.017); ~0.09–0.12 for t=1..99, CV 0.099 | **[E]** |
| F6 — silent-timestep fraction `σ` | **0.0377** | **0.1934** | **[E]** |
| F7 — active-neuron fraction (mean/sample) | 0.848 | 0.506 | **[E]** |
| F9 — burstiness ratio `B` | **2.365** | **1.790** | **[E]** |
| F11 — `z(g)` spatial, `g = 1, 4, 10, 20` | 0.813, 0.449, 0.147, **0.038** | 0.895, 0.640, 0.381, **0.193** | **[E]** |
| F12 — `‖C_i‖₁` spread (out of 2000) | mean 899.8, spread 111 (851–962) | mean 766.7, spread 91 (732–823) | **[E]** |
| F14 — accuracy at `T′ = 50` | not run (E6 out of scope this pass) | not run | **[E]** |
| F16 — identity argmax agreement | not independently verified (see limitations — algebraically exact by construction, not empirically re-checked) | same | **[E]** |
| Malleability: `r` at <1% accuracy loss | not run (E4 out of scope this pass) | not run | **[E]** |
| **Verdict (a) / (b) / (c)** | not adjudicated — see observations below; full E4/E5 sweeps needed first | not adjudicated; additionally not accuracy-matched | **[E]** |

**Standing caveat [I], now populated rather than hypothetical:** every value
above is a property of `(dataset=N-MNIST or DVS-Gesture, n=20, T=100,
V_thresh=trained-not-swept, β=address-generation-direct-from-native-resolution,
input_scaling=per_sample_norm, λ=0/not applied, seed=0)` and of *this specific
reimplementation* — not of NeuroHDC in the abstract, and not yet checked
across seeds.

#### What was measured

The complete `S ∈ {0,1}^{20×100}` output spike raster of a from-scratch
NeuroHDC reimplementation (§13.1–13.2; no official code or checkpoint exists),
captured on the full N-MNIST test split (10,000 samples) and full DVS-Gesture
test split (240 samples, 11th "Other" class excluded), at the paper's default
configuration (`n=20, T=100, D_hv=2000`). Per-sample firing statistics (F1–F9,
F11, F12) and dataset-level distributions were computed from the captured
rasters; **F13/F14 (early exit), F16 (independent identity re-check), and the
`V_thresh`/rate-penalty malleability sweeps (E4/E5) were not run** in this
pass — see limitations.

#### How it was measured

Events were parsed from the raw AER `.bin` files (N-MNIST) and pre-segmented
per-instance `.npy` event arrays (DVS-Gesture) already present in
`data/`. Timesteps were formed by equal-event-count binning (not wall-clock
time, per §III-B). SumPool was implemented exactly as address generation
(eq. 19), not as a materialized spatial filter. A single-layer IF SNN
(`n=20`, int8-QAT weights, hard reset, no leak, no bias) fed a binary
class-hypervector head (`Sign(W_c)`, straight-through), trained jointly by
gradient descent (Mode 1, §III-C) with an ATan surrogate for the spike
threshold. `V_thresh` — never specified by the paper (blocker B5) — was left
as a trainable parameter rather than manually swept, so the measured `r` is
the rate the paper's own training objective converges to on its own, not a
hand-picked operating point. Full methodology, every unspecified-parameter
choice, and every deviation from the paper or from
`firing_rate_experiment_spec.md`'s own suggested plan are in
`phase1_firing_characterization/firing_rate_results.md` §3–4 (marked
explicitly as deviations, not silently resolved).

#### Observations directly supported by the results

- **Bit-level sparsity is real but modest, and dataset-dependent**: `r =
  0.187` (N-MNIST) and `r = 0.105` (DVS-Gesture) — both comfortably below the
  `r ≈ 0.5` a BNN-trained classifier might default to, and both well above
  zero. Consistent with §13.5's "measure and hope" framing being answerable
  rather than moot.
- **Bit-level sparsity does not survive being read at word granularity.**
  `z(1) = 1−r` (0.81–0.90) collapses to `z(20) = σ` (0.038–0.193) once the
  access unit is a full `n`-bit timestep — a 5.3–9.5× nominal bit-level
  reduction becomes a 1.04–1.24× word-level reduction. This is the exact
  divergence `firing_rate_experiment_spec.md` §5 predicted as the key risk,
  now measured rather than hypothesized.
- **No dead neurons in either dataset** (0/20) — the static row-pruning
  fallback noted in §7's coverage matrix and the spec's F7 decision point
  ("near-dead neurons ⇒ row pruning") does not apply to either measured
  dataset.
- **Firing is temporally correlated, not independent**, in both datasets
  (burstiness `B = 2.37` N-MNIST, `1.79` DVS-Gesture, both `≫ 1`), visible
  directly in representative raster plots as long same-neuron firing runs
  rather than scattered independent spikes.
- **The per-timestep firing-rate profile is non-uniform and
  dataset-specific in shape**: a smooth unimodal envelope for N-MNIST vs. a
  flat profile (after one cold-start timestep) for DVS-Gesture. A design
  assuming a fixed, precomputed temporal access pattern would need to justify
  that assumption per dataset, not once in general.
- **Per-sample variability differs sharply by dataset**: N-MNIST's
  per-sample rate is tight (CV 0.143); DVS-Gesture's is wide and
  right-skewed (CV 0.445). A design provisioned only for a mean rate risks
  under-provisioning for DVS-Gesture's tail.
- **DVS-Gesture's own accuracy could not be matched** with this
  reimplementation (60.4% vs. 87.5%) even after adding weight decay and a
  training-only event-dropout augmentation absent from the paper; DVS-Gesture
  results here should be treated as provisional pending a better-trained
  model, more explicitly than N-MNIST's (94.91% vs. 97.28%, a materially
  closer match).

#### Reproducibility limitations (full list in the companion report §9)

No official code/checkpoint (full reimplementation, as already documented in
§13.1); DVS-Gesture accuracy not matched to the paper; N-MNIST trained on a
subsampled training split (full test split used for all reported statistics);
single seed only, not the ≥3 the spec calls for; `V_thresh` learned rather
than exhaustively swept, so no threshold Pareto front was produced;
`(n,T)` sensitivity, early-exit, and rate-penalty-malleability experiments
(E4, E6, E7) were not run in this pass; DVS-ASL entirely out of scope (data
unavailable); DVS-Gesture model selection used best-test-epoch in the absence
of a held-out validation split, which optimistically biases its reported
accuracy; two training-only additions not in the paper were introduced and
disclosed (a fixed logit-temperature rescaling that does not change
`argmax`, and DVS-Gesture-only weight decay/event-dropout to counter
overfitting). A preprocessing deviation from `firing_rate_experiment_spec.md`'s
own suggested N-MNIST crop/pad plan (not from the paper, which specifies no
`β` value at all) is documented in the companion report §3.

**This measurement answers a narrower question than full Phase-1 adjudication
requires.** It establishes that output-raster sparsity exists at the bit
level and mostly disappears at word level, for two of three datasets, at one
seed, without a malleability or early-exit sweep. It does **not** yet
adjudicate verdict (a)/(b)/(c) from §13.8, and does **not** propose or imply
any CIM architecture — that remains explicitly deferred, per this section's
scope and per the project's standing constraint (§1.4).

---

### 13.10 DVS-Gesture accuracy-improvement and re-measurement — **[E] CURRENT, supersedes §13.9's DVS-Gesture column**

Full detail: `dvs_accuracy_report.md` (accuracy work),
`neurohdc_implementation_audit.md` (paper-vs-implementation audit),
`phase1_firing_characterization/firing_rate_results.md` (updated firing-rate
report, DVS-Gesture section rewritten, N-MNIST section unchanged).

#### Why this was needed

§13.9's DVS-Gesture measurement (60.42% test accuracy vs. the paper's
87.5%, a 27-point gap) was far enough from the paper's operating point that
its firing-rate statistics could not be trusted as representative of
NeuroHDC. Before spending further analysis on those numbers, the
implementation was audited against the paper parameter-by-parameter
(`neurohdc_implementation_audit.md`) and the gap was closed as far as a
systematic, non-exhaustive search reasonably allows.

#### Audit finding **[S]/[I]**

`neurohdc_implementation_audit.md` Part A checked 16 core algorithm/dataflow
items (encoding, SNN, quantization technique, query, gradient flow) against
the paper — **all matched**; no architectural discrepancy was found or
introduced. Part B classified 16 training-procedure parameters: 2 are
**[S]**/**[I]** (Adam optimizer; the canonical train/test split), the
remaining 14 are **[O]** — the paper gives no information to determine them,
confirmed by full-text search of the paper PDF (zero hits for "batch",
"epoch", "learning rate" [other than the unrelated transfer-learning rate],
"dropout", "regulariz", "weight decay", "seed", "normali", "clip",
"initializ"/"Xavier"/"Kaiming"/"Gaussian" tied to `W_s`/`W_c`).

**One [O] choice in the previous run actively contradicted the paper**: an
added per-sample input normalization, where paper eq. (16) states
`X(t) = W_s·D_flat(t)ᵀ` applied directly to the raw, unnormalized SumPooled
count tensor. This is fixed in the current run (§ below).

#### What changed — all **[O]**, none claimed as **[S]** (full list and effect size in `dvs_accuracy_report.md` §2–3)

1. Input scaling: `raw` (restores eq. 16), not `per_sample_norm`.
2. Label-free threshold calibration at initialization.
3. Model selection: best-**validation**-epoch (5 of 23 training users held
   out), never the test set — fixes a methodological bug in the previous run.
4. Per-channel (per-neuron) 8-bit weight quantization.
5. Weight decay (`1e-4`) and event-dropout augmentation (`p=0.1`), disclosed
   as not paper-supported.
6. **Gradient clipping** (`clip_grad_norm_`, max norm 0.5) — absent from
   every earlier run; found to be **the single largest contributor** to the
   accuracy improvement (`dvs_accuracy_report.md` §3), consistent with this
   architecture being a 100-step BPTT-trained unrolled recurrence through a
   hard-reset nonlinearity (paper eq. 12–16) with no clipping used anywhere
   before this pass.

Ten controlled experiments were run (one variable changed at a time, one
confound caught and corrected), documented in full in
`dvs_accuracy_report.md` §3. Two standard techniques tried and found to
**hurt** in isolation (label smoothing, dropout on the flattened
hypervector before the class-HV head) were excluded from the final
configuration.

#### Accuracy result — **[E]**

| | Paper | Previous (§13.9) | **Current (frozen, 3 seeds)** |
|---|---|---|---|
| DVS-Gesture test accuracy | 87.5% | 60.42% (test-set-selected, methodologically flawed) | **82.36% ± 2.08%** mean / **84.58%** best seed (validation-selected) |

All 3 seeds fully converge on the training set (100% train accuracy) and
their validation curves plateau by epoch ~150–200 with no further
improvement — the residual seed-to-seed spread (79.6–86.2% val) reflects
genuine differences between converged solutions, not under-training.
`dvs_accuracy_report.md` §7 discusses the residual ~3–5 point gap to 87.5%
and judges it more likely attributable to genuinely undisclosed paper
details than to a further reachable fix, without asserting certainty.

#### Re-measured firing-rate statistics — **[E]**, DVS-Gesture only (N-MNIST unaffected, unchanged from §13.9)

| Statistic | Previous (60.4% acc, superseded) | **Current (84.6% acc, seed 0)** |
|---|---|---|
| Global firing rate `r` | 0.1053 | **0.3755** |
| Silent-timestep fraction `σ` | 0.1934 | **0.00021** (5 of 24,000 timestep-observations) |
| Burstiness `B` | 1.790 | **2.555** (noisy at this near-zero `σ`, see firing_rate_results.md §8.3) |
| `z(g)` spatial, `g=20` (word-level) | 0.193 | **0.0002** |
| Dead neurons | 0/20 | **0/20** |
| Per-sample rate CV | 0.445 | **0.207** |

Cross-seed check (all 3 frozen seeds): `r` ranges 0.376–0.455, `σ` ranges
0.00017–0.00029 (4–7 exact silent timesteps out of 24,000 per seed) — the
**qualitative** finding (dense, essentially never silent at word
granularity) is consistent across all 3 independently-trained seeds, not an
artifact of one run.

#### Observations directly supported by the re-measurement — **[E]**

- **The properly-trained model's raster is denser, not sparser**, than the
  undertrained one (`r`: 0.105 → 0.376) and **essentially never silent at
  word granularity** (`σ`: 0.193 → 0.0002, a ~900× reduction) — the exact
  opposite of what the earlier, undertrained measurement suggested.
- **The word-level sparsity ranking between datasets reverses.** Previously
  DVS-Gesture looked *more* word-sparse than N-MNIST (`σ`: 0.193 vs. 0.038);
  now it is far *less* word-sparse (`σ`: 0.0002 vs. 0.038, N-MNIST
  unchanged).
- **The per-timestep temporal profile's shape flips direction**: a rising
  profile in the undertrained model (low at `t=0`) becomes a decaying
  transient in the accuracy-matched model (high at `t=0`, settling by
  `t≈20`) — see firing_rate_results.md §8.1.
- **This is direct evidence that firing-rate statistics on a NeuroHDC
  reimplementation are sensitive to how close the model is to the paper's
  reported accuracy**, not just to the dataset — a methodological point for
  any future measurement on this codebase or a similar one.

#### Explicitly not concluded — per the standing research constraint (§1.4)

This section does **not** conclude that output-raster sparsity is or is not
useful for a CIM query mechanism. It measures what the raster of an
accuracy-matched NeuroHDC reimplementation looks like on DVS-Gesture and
reports how that differs from an earlier, less-trustworthy measurement. No
architecture is proposed here or implied.

---

## 14. Changelog

| Date | Change |
|---|---|
| 2026-09-20 | Initial version. Steps 1–3 only: NeuroHDC reconstruction, seven-paper reverse engineering, design-space matrix, nine identified gaps (G1–G9), twelve invariants, ten open questions. No architecture proposed. |
| 2026-09-20 | Added §13 Phase 1 measurement plan: code-availability audit (no official release — full reimplementation required), specified-vs-unspecified parameter table (U1–U11), sixteen firing statistics (F1–F16), decision criteria centred on the zero-group fraction `z(g)` rather than the raw firing rate, eight experiments (E0–E8), and a file-by-file implementation specification. Added the `[E]` tag. Still no architecture proposed. |
| 2026-09-20 | Added §13.9 unmeasured-results placeholder (all cells `[E]`) and companion file `firing_rate_experiment_spec.md` — the directly-implementable version of §13 for Claude Code, including the blocker list (B1–B10), the capture point, the zero-group sweep, per-dataset/per-config measurement protocol, and the (a)/(b)/(c) verdict criteria. Confirmed via a second search pass (Gitee, OpenI, NUAA faculty pages) that no official code or checkpoints exist. Still no architecture proposed. |
| 2026-09-21 | **[E]** Ran the Phase 1 firing-rate characterization end to end for N-MNIST and DVS-Gesture (DVS-ASL out of scope — data unavailable). Full reimplementation under `phase1_firing_characterization/` (no code from the paper existed to build on). Recovered Tables I–IV from the PDF page images, resolving blocker B4. Filled §13.9's results table with measured F1–F9, F11, F12 statistics, accuracy-match figures, and observations. Key measured results: bit-level firing rate `r` = 0.187 (N-MNIST) / 0.105 (DVS-Gesture), both moderately sparse; word-level (`n`-bit-timestep) sparsity `σ` = 0.038 / 0.193, a sharp collapse from the bit-level number; burstiness `B` = 2.37 / 1.79 (temporally correlated, not independent firing); no dead neurons in either dataset; non-uniform, dataset-specific per-timestep rate profiles. N-MNIST accuracy-matched reasonably (94.91% vs. 97.28%); DVS-Gesture did not (60.42% vs. 87.5%) despite added regularization, and its numbers are flagged as provisional. E4 (rate-penalty malleability), E6 (early exit), E7 ((n,T) sensitivity), and the ≥3-seed requirement were **not** run in this pass. No CIM architecture proposed; no novelty claimed. Full methodology, per-sample data, plots, and limitations in `phase1_firing_characterization/firing_rate_results.md`. |
| 2026-09-21 | **[E]/[O]** DVS-Gesture accuracy-improvement pass, per a follow-up task requiring the firing-rate statistics come from a model representative of the paper's reported accuracy before being trusted. Added the **[O]** tag (our implementation choice, distinct from [I]). Audited the implementation against the paper parameter-by-parameter (`neurohdc_implementation_audit.md`): core algorithm/dataflow matched on all 16 checked items (no redesign); found one prior **[O]** choice (per-sample input normalization) that actively contradicted paper eq. (16), plus a model-selection bug (test-set-based checkpoint choice). Ran 10 controlled experiments (`dvs_accuracy_report.md`) fixing input scaling to raw (eq. 16-faithful), adding label-free threshold calibration, per-channel QAT, validation-based model selection (5 of 23 training users held out, test set touched once per seed), disclosed weight decay/event dropout, and — the single largest fix — gradient clipping (absent from every earlier run despite this architecture being a 100-step BPTT-trained unrolled recurrence). DVS-Gesture test accuracy improved from 60.42% (methodologically flawed) to **82.36%±2.08%** mean / **84.58%** best seed across 3 seeds (paper: 87.5%), frozen and re-measured. New §13.10 records the accuracy work and a superseding firing-rate re-measurement: `r` 0.105→**0.376** (denser, not sparser), `σ` 0.193→**0.00021** (word-level sparsity nearly vanishes), consistent across all 3 seeds. Old §13.9 DVS-Gesture numbers marked SUPERSEDED in place, not deleted; N-MNIST unaffected. No CIM architecture proposed; sparsity usefulness for CIM still not concluded either way. |
