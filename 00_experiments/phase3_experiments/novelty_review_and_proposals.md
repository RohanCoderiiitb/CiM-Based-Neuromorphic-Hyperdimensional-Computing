# CIM-NeuroHDC — Deep Novelty Review and Architecture Proposals

**Scope.** Literature review beyond the seven project papers, then concrete
architectural proposals ranked by *research feasibility × novelty potential*.
CIM for the SNN matrix-vector multiply is assumed as the **foundation** — the
contribution must sit on top of it.

**Skepticism rule applied throughout:** an idea is marked novel only after an
explicit search failed to find it. Where the search was inconclusive it says so.
Two of my earlier ideas were **downgraded or killed** by this review; that is
recorded rather than hidden.

**Tags:** `[S]` stated in a paper · `[M]` measured in our Phase 1 ·
`[D]` derived here (`feasibility.py`, `traffic.py`, `energy_model.py`) ·
`[?]` uncertain.

---

## 0. Executive summary

**What the literature review changed:**

1. **My "membrane potential on the bitline" idea is substantially pre-empted.**
   An event-driven SOT-MRAM CIM macro (arXiv 2511.03203, 2025) already
   accumulates the analog result on a capacitor (`C_rt`), reads out with a
   **comparator rather than an ADC**, and uses asynchronous event-flag control.
   Analog capacitive integration + comparator readout in an event-driven CIM
   macro is **published art**. It cannot be the contribution.

2. **The leak budget makes that idea conditionally viable at all** — and the
   condition is itself interesting. At chip rate (one event/cycle, 100 MHz) a
   timestep is 40.7 µs and droop is **0.4–4 mV** — fine. At sensor real-time
   (~6 s per DVS-Gesture sample → 60 ms/timestep) droop is **600–6000 mV** —
   catastrophic `[D]`. So any analog-state design **must burst-process buffered
   events and cannot stream at sensor rate**. That is a hard architectural
   constraint nobody has had to state for NeuroHDC before.

3. **The strongest surviving idea is one I had not considered until this review:
   factorizing the class hypervector along its (neuron × timestep) axes.** The
   HDC-compression literature is crowded — LogHD, DecoHD, ByteHD, DPQ-HD — but
   **every one of them compresses along the class axis or treats dimensions as
   unstructured**, because in conventional HDC the dimension index is
   meaningless by construction. DecoHD states this explicitly: it "makes no
   assumptions about meaningful hypervector dimensions."

   **NeuroHDC is the first HDC where the dimension index has semantics**
   (dimension `m = (t−1)·n + j` *is* neuron `j` at timestep `t`). That opens a
   compression/mapping axis that is structurally unavailable to every prior HDC
   work. Storage drops **16.7×** and the query array goes from a pathological
   2000×10 (**7.6% macro utilization**) to a stationary 20×10 `[D]`.

---

## 1. What is actually exploitable about NeuroHDC

Not a list of features — a list of properties that *change what hardware should
do*, with the consequence spelled out.

| # | Property | Source | Why it changes the hardware |
|---|---|---|---|
| P1 | **No encoder at all.** Spikes *are* the hypervector (eq. 7) | `[S]` §III-A | The interface between the SNN and the classifier is **1 bit per neuron**. No ADC needed between stages — a comparator suffices. Every other SNN+HDC design (HyperSpikeASIC, Spiking-HDC, Xiao's 40 nm chip) has an encoding stage with item memory and XOR chains in between, and cannot do this. |
| P2 | **`D_hv = n × T`: the hypervector index factorizes** | `[S]` §IV-B1 | The class hypervector is a **`T×n` matrix with physically meaningful axes**, not an unstructured 2000-bit string. Memory can be laid out along either axis, and the class vector can be *factorized* along them (→ Idea C). No conventional HDC class vector has axes. |
| P3 | **IF neuron, no leak, hard reset to 0** | `[S]` §II-A | Pure integrate-and-dump. A capacitor does this natively; no leak model, no decay circuit. Note the inversion: the paper chose IF because it is *simpler in digital*; in analog IF is the **harder** one (a leak-free node is hard to build, a leaky one is free). |
| P4 | **`n = 20` output neurons** | `[S]` §IV-B1 | Absurdly narrow, and that is an **enabler**: 20 analog integrators + 20 comparators is affordable. A 512-output SNN layer would need 512 of each. NeuroHDC's smallness is what makes per-column analog state viable. |
| P5 | **Timesteps cut by event *count*, not time** (`N_e` register) | `[S]` §III-B, §V-A | Every timestep contains exactly `N_e` events, so the input vector's **L1 norm is constant by construction**. Enables a zero-cost per-timestep calibration reference (→ Idea D). Normal SNNs cut by time and have wildly varying input norms. |
| P6 | **SumPool collapses into address generation** (eq. 19) | `[S]` §V-B | No pooling arithmetic exists. The "input frame" is a 512-entry counter array indexed by `addr = p·256 + ⌊y/β⌋·16 + ⌊x/β⌋`. Building the frame is nearly free — which matters because batching events is the only way a crossbar sees a real MVM. |
| P7 | **Membrane potential is 55 bytes total** | `[D]` | `n × 22 b`. IMPULSE's entire contribution (fused `W_MEM`/`V_MEM`) solves a problem NeuroHDC does not have. Do not import it. |
| P8 | **Query latency is structurally free** | `[S]` §V-C | Latency is set by event count, not by `T`. Cycle-count optimizations are not a headline result here; energy and area are. |
| P9 | **Traffic is 99.97% SNN weight reads** | `[D]` | 8,142,478 weight reads vs 1,000 class-HV reads per DVS-Gesture sample. Any contribution that only touches the query is optimizing 0.03% of the chip. |
| P10 | **Measured raster: `r ≈ 0.38–0.46`, `σ ≈ 0.0002`** | `[M]` | Whole-timestep sparsity is extinct. Neuron-level sparsity (≈62.5% zeros) exists but, per the Phase-2 analysis, converts to ~6% in NeuroHDC's own SRAM and 25–45% in a crossbar (ADC floor). Not a contribution on its own. |

---

## 2. Literature findings

### 2.1 What is already taken (do not claim)

| Mechanism | Prior work | Status |
|---|---|---|
| Analog capacitive accumulation of CIM column current + **comparator (not ADC)** readout, event-driven/asynchronous control | [Event-Driven Spiking CIM Macro based on SOT-MRAM](https://arxiv.org/html/2511.03203v1) (2025) — `C_rt` accumulates mirrored column current; comparator toggles to emit the second of a dual-spike pair; global `Event_flag` gives asynchronous control | **Taken.** Closest prior art to my Idea A. Its inputs are applied **in parallel across all 128 rows with dual-spike temporal encoding**, not one-hot per event — that is the only remaining gap, and it is narrow. |
| Analog IF/LIF neurons built on capacitors, memristor-coupled | [Adjustable LIF neurons from memristor-coupled capacitors](https://www.sciencedirect.com/science/article/pii/S259004982100062X); [Adiabatic LIF neurons](https://www.nature.com/articles/s44335-024-00013-1); [IF neuron circuit robust to synapse variability](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/2023/1052063) | **Taken**, decades deep. |
| Spike-driven / event-based digital CIM | [FlexSpIM](https://arxiv.org/html/2609.08446) (event-based digital CIM, flexible operand resolution) — **I could not read this page; arXiv rate-limited the fetch, so it is characterized from its abstract only** `[?]`; [IMPULSE](https://arxiv.org/pdf/2105.08217) (input-spike sparsity → instruction skipping) | **Taken.** |
| RRAM/MRAM SNN CIM with in-situ neurons | ASTERS (DAC'22), Tempo-CIM (JETCAS'23), DS-CIM (TCAS-I'24); survey: [Reliability of ReRAM-based CIM for SNN](https://arxiv.org/html/2412.10389v1) | **Taken.** |
| Capacitive in-memory computing as a paradigm | [Toward Capacitive In-Memory Computing](https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/aidi.202500143); [Nonvolatile capacitive crossbar](https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/aisy.202100258) | **Taken.** |
| End-to-end HDC in crossbars (encode + AM) | [In-memory HDC](https://arxiv.org/pdf/1906.01548v1), Nature Electronics 2020; [analogue memristive HDC](https://pmc.ncbi.nlm.nih.gov/articles/PMC13522599/) | **Taken.** |
| HDC classifier compression | [LogHD](https://arxiv.org/html/2511.03938) (logarithmic **class-axis** reduction); [DecoHD](https://arxiv.org/html/2511.03911) (decomposition **along the class axis**, explicitly "no assumptions about meaningful hypervector dimensions"); [ByteHD](https://link.springer.com/article/10.1007/s12559-026-10593-8); DPQ-HD; HyperDyn | **Taken — but all along the class axis or generic.** See §2.2. |
| Early exit / early stop in SNNs | [SEENN: Temporal Spiking Early Exit](https://www.researchgate.net/publication/401445579_SEENN_Towards_Temporal_Spiking_Early_Exit_Neural_Networks); [FPGA event-driven SNN accelerator with structured sparsity and early-stop](https://www.researchgate.net/publication/391376487_An_FPGA-Based_Event-Driven_SNN_Accelerator_for_DVS_Applications_With_Structured_Sparsity_and_Early-Stop) | **Taken as a concept.** The *exit signal source* and *what it gates* still differ (→ Idea E). |
| Cascaded crossbar pipelines | [Cascaded ReRAM crossbar for Transformers](https://dl.acm.org/doi/10.1145/3701034) | **Taken**, but with multi-bit interfaces requiring ADCs between stages. |
| SNN+HDC hybrids | [HyperSpike](https://www.researchgate.net/publication/360730631_HyperSpike_HyperDimensional_Computing_for_More_Efficient_and_Robust_Spiking_Neural_Networks), [HyperSpikeASIC](https://dl.acm.org/doi/abs/10.1109/TCAD.2023.3264167), [SpikeHD](https://www.nature.com/articles/s41598-022-11073-3), [SynapseHD](https://www.sciencedirect.com/science/article/abs/pii/S0925231225024294), [HyperEncoding](https://dl.acm.org/doi/10.1145/3716368.3735233), [HD decoding of SNNs](https://arxiv.org/abs/2511.08558) | **Taken as a family** — but **all are digital or algorithmic; none is a CIM implementation of an encoder-free spike-raster hypervector.** |

### 2.2 The gap the search did *not* close

Every HDC compression/mapping work found treats the hypervector as **an
unstructured bag of i.i.d. dimensions** — because in conventional HDC it *is*.
Dimensions come from random projection or random item memories; dimension 37 has
no relationship to dimension 38.

DecoHD says this outright: decomposition is along the **class axis**, and it
"makes no assumptions about meaningful hypervector dimensions."

**NeuroHDC breaks that assumption.** Its dimension `m` decomposes uniquely as
`(t, j)` — timestep and neuron. I found **no work that exploits structure in the
hypervector *dimension index*** for storage, mapping, or in-memory computation.
Searches run: structured/separable hypervectors with meaningful axes; tensor
product factorization of spatiotemporal hypervectors; VSA with meaningful
dimension semantics in hardware. `[?]` — absence of evidence, and the HDC/VSA
literature is large, so this needs a librarian-grade check (IEEE Xplore + ACM DL
full-text) before any paper claims it.

---

## 3. Proposals

Each: mechanism · why NeuroHDC-specific · closest prior work · what is actually
novel · tradeoffs · validation.

---

### Idea C — Axis-factorized class hypervector *(strongest)*

**Mechanism.**
The class hypervector is a `T×n` matrix `C_i[t,j]`. Constrain it during training
to a rank-`R` factorization over its two physical axes:

```
C_i[t,j] = sign( Σ_{r=1..R}  a_i^r(j) · b_i^r(t) )
```

with `a_i^r ∈ R^20` (a *neuron profile*) and `b_i^r ∈ R^100` (a *temporal
profile*). The query then reassociates:

```
Score_i = Σ_t Σ_j S_j(t)·C_i[t,j]
        = Σ_t Σ_r b_i^r(t) · [ Σ_j S_j(t)·a_i^r(j) ]
                              └── 20-wide spike-gated dot product ──┘
```

**Hardware consequence — this is the point, not the compression.** The inner
bracket is a **20×(N·R) crossbar that never changes across timesteps**. The
spike register gates its 20 rows directly. The outer sum is a small `T×(N·R)`
coefficient table and an accumulator.

| | Baseline | Factorized (R=1) |
|---|---|---|
| Query array | 2000 × 10 | **20 × 10** |
| 128×128 macros | 16 | **1** |
| Macro utilization | **7.6%** | — (fits one macro) |
| Class-HV storage | 20,000 bits | **1,200 bits (16.7×)** |
| Dataflow | row-block cycling, 100 different blocks | **fully stationary** |
| Rows active per access | 7.5 of 2000 (**0.38%**) | 7.5 of 20 (**37.5%**) |

`[D]`. That last row is the real prize: the time-unrolled array is pathological
for a crossbar (you energize a 2000-row array to use 7.5 rows). The factorized
array is a well-shaped, stationary, spike-gated crossbar — **exactly the thing
crossbars are good at.**

**Why NeuroHDC specifically.** Requires `D_hv = n×T` with both axes physically
meaningful (P2). In Random-Projection, Level-ID, or N-gram HDC the dimensions
are i.i.d. random — there is no `(t,j)` to factorize along and a rank
constraint would be meaningless. **This idea cannot be stated for any prior HDC
system.**

**Closest prior work.** DecoHD (class-axis decomposition, explicitly assumes
unstructured dimensions), LogHD (class-axis), ByteHD/DPQ-HD (generic
quantization), MEMHD (multi-centroid for array fit — the *opposite* move:
spends more columns, keeps D). **None factorizes along dimension semantics.**

**What is actually novel.** Not "compress the class vectors" — that is crowded.
The claim is: *NeuroHDC's hypervector index carries physical structure, and that
structure can be pushed into the memory organization, converting an unmappable
2000-row time-unrolled array into a small stationary spike-gated crossbar.*
The compression is a side effect of the mapping, not the point.

**Tradeoffs.**
- **Accuracy is the whole risk.** R=1 is severe: `2^(n+T)` reachable patterns out
  of `2^(nT)`. May cost several points. R=4 gives 4.2× compression and much more
  freedom `[D]`.
- Needs a `T×(N·R)` coefficient table (small) and a multiplier if `b` is
  multi-bit. If `b` is constrained to ±1, it degenerates to a per-timestep sign
  flip — nearly free.
- Changes training. Must be framed as **co-design**, with the memory
  organization as the contribution and the training constraint as the enabler —
  otherwise it reads as "we compressed the model," which the project rules
  exclude as a primary contribution.

**Validation — cheap and decisive.** Add the rank constraint to the existing
PyTorch model; sweep `R ∈ {1,2,4,8,full}`; plot accuracy vs `R` on DVS-Gesture
and N-MNIST. **No new hardware modeling needed to kill or confirm it.** If R=4
holds accuracy within ~1 point of 84.6%, the idea is live. Estimated effort:
hours, using code you already have.

---

### Idea B — Two-level nested analog integration with a binary waist

**Mechanism.** Two coupled analog arrays, no ADC anywhere in the datapath.

```
ARRAY 1 (SNN)  512 rows × 20 cols          ARRAY 2 (classifier)
  event → 1 wordline pulse                   spike-gated rows
  column cap integrates  =  V_mem            column cap integrates = Score_i
  event counter hits N_e                     after T timesteps
      ↓ 20 comparators vs V_thresh               ↓ N conversions (once)
      └────── 20-bit BINARY WAIST ──────────────┘
              (drives Array 2's wordlines directly)
      cap discharged = hard reset
```

*Inner loop:* events integrate onto `V_mem`, dumped every `N_e` events.
*Outer loop:* spikes integrate onto the score, dumped once per sample.
This mirrors NeuroHDC's own two-level structure (events inside timesteps,
timesteps inside a sample).

**Why NeuroHDC specifically.**
- P3: IF + hard reset = integrate-and-dump, exactly a capacitor + switch.
- P4: `n = 20` — only 20 integrators and 20 comparators needed.
- P1: **no encoder**, so the inter-array interface is 1 bit/neuron. A comparator
  is sufficient; no ADC. Every other SNN+HDC design needs an encoder here.
- P5: the dump boundary is a **digital event counter**, not an analog timer.
- Outer loop: whole-sample accumulation gives **10 conversions instead of 1,000**
  `[D]`.

**Closest prior work.** The SOT-MRAM event-driven macro — analog cap
accumulation, comparator readout, asynchronous event control. **This is very
close.** Differences: (i) it applies inputs in parallel across rows with
dual-spike temporal encoding; NeuroHDC's events are genuinely one-hot, so no
input encoding scheme is needed at all; (ii) its capacitor holds a *per-MVM
intermediate*, not a membrane potential persisting across a long
multi-thousand-event window; (iii) nothing downstream — there is no second
array and no binary waist.

**What is actually novel.** Only the **composition and the waist**: two analog
arrays cascaded with a 1-bit interface, in which the intermediate value that
formally exists in the mathematics (the 2000-bit hypervector) **never physically
exists anywhere on the chip.** Cascaded crossbars exist but digitize between
stages because their interfaces are multi-bit; here P1 makes the interface
binary. `[?]` — needs a dedicated search on binary-interface cascaded analog
arrays before claiming.

**Tradeoffs — and one hard constraint this review established.**

Leak budget `[D]`:

| Operating mode | Timestep duration | Droop (C=100 fF, 1 pA) | Verdict |
|---|---|---|---|
| Chip rate, 1 event/cycle @100 MHz | **40.7 µs** | 0.41 mV | **OK** |
| Chip rate @1 GHz | 4.1 µs | 0.04 mV | OK |
| **Sensor real-time (~6 s/sample)** | **60 ms** | **600 mV** | **FAILS** |

> **The chip must burst-process buffered events. It cannot integrate in analog
> at the sensor's own rate.** That is a real architectural constraint, it is
> derived rather than assumed, and it has not been stated for NeuroHDC before.

If the leak margin is still too thin, the fallback is a **burst-accumulate
hybrid**: integrate `B` events in analog, dump to a digital accumulator, repeat.
Conversions per sample `[D]`:

| `B` | conversions/sample | vs 8.14M SRAM reads | burst duration |
|---|---|---|---|
| 64 | 127,226 | 64× fewer ops | 0.64 µs |
| 256 | 31,807 | 256× | 2.56 µs |
| 1,024 | 7,952 | 1,024× | 10.2 µs |
| 4,070 (full timestep) | 2,001 | 4,070× | 40.7 µs |

`B` becomes a first-class co-design parameter traded against leak, ADC
resolution and accumulated device variation. Other risks: conductance variation
accumulating over thousands of events without re-quantization; the threshold
comparator's offset now sits directly in the algorithm's `V_thresh`.

**Validation.** SPICE/Verilog-A for one column (integrator + comparator +
reset) over a realistic event stream; a behavioral PyTorch model with injected
droop, comparator offset and device variation, checked against the 84.6%
baseline; NeuroSim/CACTI for the energy comparison against the SRAM baseline.

---

### Idea E — Similarity-margin early termination that gates *event ingestion*

**Mechanism.** In Idea B's outer loop the class scores exist as analog voltages
that grow monotonically over time. Add `N−1` comparators to watch the margin
between the leading and runner-up columns. When the margin exceeds a threshold,
**stop ingesting events and emit the answer.**

**Why NeuroHDC specifically.** The score is *already* an analog voltage being
accumulated — the exit signal costs `N−1` comparators and no computation. There
is no confidence head, no softmax, no extra classifier. And because P9 says
99.97% of the energy is event ingestion, **an exit saves the expensive part, not
the cheap part** — the 0.03% query controls the 99.97% SNN. P8 says latency is
free *only because* events must arrive; early exit is the one mechanism that
breaks that and buys real latency as well as energy.

**Closest prior work.** SEENN (temporal spiking early exit); the FPGA
event-driven SNN accelerator with early-stop. Both exit on a *computed
confidence* from the SNN and stop *timestep processing*.

**What is actually novel.** `[?]` Modest and uncertain. The differences are
(i) the exit signal is a free by-product of analog accumulation rather than a
computed confidence, and (ii) what is gated is **sensor event ingestion**, not
network timesteps. Whether that clears a novelty bar on its own — no. **As a
secondary contribution inside Idea B, yes.**

**Tradeoffs.** Needs accuracy-vs-exit-point characterization; classes with
overlapping spatiotemporal patterns (the paper's Fig. 4 confusion matrix shows
Air Guitar ↔ Hand Clapping and Right-Arm-CCW ↔ Left-Hand-Wave) will exit late or
wrong. Equal-event-count binning means an early exit truncates the *event
budget*, not wall-clock time — needs care.

**Validation.** **Computable today from the existing rasters, no retraining.**
Replay each captured raster, accumulate scores timestep by timestep, record when
the margin stabilizes, and plot accuracy vs mean exit timestep.

---

### Idea D — Constant-`N_e` self-calibration column

**Mechanism.** Because every timestep contains exactly `N_e` events (P5), the
input vector's L1 norm is constant. Add one column with all conductances equal:
its output is exactly `N_e` **every timestep, by construction**. Use it as a
live reference to cancel temperature, supply and conductance drift — refreshed
100× per inference at the cost of one column.

**Why NeuroHDC specifically.** Requires event-count binning. SNNs that bin by
time have input norms that vary with scene activity, so the reference would be
meaningless.

**Closest prior work.** Reference columns / dummy cells are standard CIM
practice. What is unusual is that the reference value is **known a priori and
constant**, rather than requiring a calibration phase.

**What is actually novel.** Little, as a mechanism. **Supporting contribution
only** — it makes Idea B's analog accumulation more defensible under variation,
which matters because that is Idea B's main weakness.

**Validation.** Circuit simulation with injected drift; measure residual error
with and without the reference.

---

### Idea A — Event-serial analog accumulation *(downgraded — do not pursue alone)*

Originally my strongest candidate. **The SOT-MRAM event-driven macro already
does analog capacitive accumulation with comparator readout under asynchronous
event control.** The only remaining gap is that its inputs are applied in
parallel with dual-spike encoding while NeuroHDC's are genuinely one-hot — too
narrow to carry a paper.

**Retained only as the inner loop of Idea B.** Recording the downgrade because
the earlier conversation presented it as the lead idea, and it should not be
silently promoted again.

---

## 4. Ranking (feasibility × novelty potential, not preference)

| Rank | Idea | Novelty | Feasibility | Kill-cost | Note |
|---|---|---|---|---|---|
| **1** | **C — axis-factorized class HV** | **Highest.** The one structural property no prior HDC has. Survived DecoHD/LogHD/ByteHD/DPQ-HD. | High — pure PyTorch to validate | **Hours.** An accuracy sweep decides it outright | Must be framed as memory-organization co-design, not compression |
| **2** | **B — two-level nested analog integration, binary waist** | **Moderate.** Components taken; composition + binary waist may survive | Medium — needs circuit modeling | Weeks | Leak constraint already derived; fallback (burst hybrid) already quantified |
| **3** | **E — margin-based early termination gating ingestion** | Low–moderate alone | **Highest** — existing rasters suffice | **Days** | Best as a secondary contribution inside B |
| **4** | **D — constant-`N_e` reference column** | Low | High | Days | Supporting only |
| **5** | **A — event-serial analog accumulation** | **Pre-empted** | — | — | Absorb into B |

**C and B are independent** — C reorganizes the classifier's memory, B
reorganizes the analog datapath. They compose: a factorized 20×(N·R) array is
*better* suited to analog spike-gated integration than the 2000×N array, because
its rows are stationary and 37.5% of them are active per access instead of
0.38% `[D]`. **That composition is the most promising full-system story I can
currently defend.**

---

## 5. What I would do next, in order

1. **Run the rank sweep for Idea C.** Hours, existing code, binary outcome. If
   accuracy collapses at every useful `R`, the strongest idea dies cheaply and
   you have lost a day.
2. **Run the early-exit replay for Idea E.** Days, existing rasters, no
   retraining.
3. **Measure input-frame sparsity** — how many of the 512 input addresses carry
   events in one timestep. Still unmeasured, and it decides whether the SNN
   crossbar sees a dense MVM or a near-empty one. Needed for B's energy model.
4. **Calibrate `α`** (per-access vs per-bit energy) for the candidate arrays.
   Still the gate on every quantitative comparison from the Phase-2 document.
5. **Librarian-grade novelty check on Idea C** before any writing: IEEE Xplore
   and ACM DL full-text for structured/factorized hypervector dimensions, tensor
   decomposition of class prototypes, and separable spatiotemporal hypervectors.
   My web search is suggestive, not conclusive.
6. **One-column SPICE model for Idea B** — integrator, comparator, reset — over
   a real event stream, with the leak and variation numbers from §3/Idea B.

---

## 6. Honest assessment

**Idea C is the first thing in this project that looks like a real
contribution.** It rests on a property (P2) that is structurally unavailable to
every prior HDC system, it changes the memory organization rather than merely
shrinking a model, it fixes a concrete pathology (7.6% macro utilization, 0.38%
row activation), and it can be falsified in an afternoon.

**Idea B is credible but crowded.** Its components are published. It would need
the binary waist, the leak-constrained burst design, and the nested two-level
integration to be argued together as a system — and a reviewer familiar with the
SOT-MRAM macro will push hard.

**Everything else is supporting material.**

**And the standing risk, unchanged:** NeuroHDC is a 12.68 kB model with 20
neurons and 10 classes. Crossbars want large, dense, parallel work. If the rank
sweep fails and the frame turns out sparse, the defensible outcome may be a
well-documented negative result — *NeuroHDC's scale and dataflow are mismatched
to CIM, here is the quantitative case* — which is publishable in a different
venue but is not the paper you set out to write. That possibility should stay on
the table until items 1–3 are done.

---

## Sources

Project papers (NeuroHDC TVLSI 2026; IMPULSE; MEMHD; HDStream; CAMPRO; HDC-SNN
40 nm; Memristor Approximate Query) are cited inline by section and are not
repeated here.

- [An Event-Driven Spiking Compute-In-Memory Macro based on SOT-MRAM](https://arxiv.org/html/2511.03203v1)
- [FlexSpIM: An Event-Based Digital Compute-In-Memory Accelerator](https://arxiv.org/html/2609.08446) — *page not readable; characterized from abstract only*
- [The Reliability Issue in ReRAM-based CIM Architecture for SNN: A Survey](https://arxiv.org/html/2412.10389v1)
- [SRAM-Based Compute-in-Memory Accelerator for Linear-decay SNNs](https://arxiv.org/html/2603.12739)
- [Toward Capacitive In-Memory Computing](https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/aidi.202500143)
- [Nonvolatile Capacitive Crossbar Array for In-Memory Computing](https://advanced.onlinelibrary.wiley.com/doi/full/10.1002/aisy.202100258)
- [Adjustable LIF neurons based on memristor-coupled capacitors](https://www.sciencedirect.com/science/article/pii/S259004982100062X)
- [Adiabatic LIF neurons with refractory period](https://www.nature.com/articles/s44335-024-00013-1)
- [An Area-Efficient Integrate-and-Fire Neuron Circuit](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/2023/1052063)
- [ASTERS: Adaptable Threshold Spike-timing Neuromorphic Design](https://dl.acm.org/doi/pdf/10.1145/3489517.3530591)
- [When In-memory Computing Meets SNNs — device-circuit-system-algorithm co-design](https://arxiv.org/html/2408.12767v1)
- [In-memory hyperdimensional computing](https://arxiv.org/pdf/1906.01548v1)
- [Hyperdimensional in-memory computing with analogue memristive crossbar arrays](https://pmc.ncbi.nlm.nih.gov/articles/PMC13522599/)
- [LogHD: Logarithmic Class-Axis Reduction](https://arxiv.org/html/2511.03938)
- [DecoHD: Decomposed Hyperdimensional Classification](https://arxiv.org/html/2511.03911)
- [ByteHD: Byte-Level Hypervector Compression](https://link.springer.com/article/10.1007/s12559-026-10593-8)
- [SEENN: Towards Temporal Spiking Early Exit Neural Networks](https://www.researchgate.net/publication/401445579_SEENN_Towards_Temporal_Spiking_Early_Exit_Neural_Networks)
- [FPGA Event-Driven SNN Accelerator with Structured Sparsity and Early-Stop](https://www.researchgate.net/publication/391376487_An_FPGA-Based_Event-Driven_SNN_Accelerator_for_DVS_Applications_With_Structured_Sparsity_and_Early-Stop)
- [A Cascaded ReRAM-based Crossbar Architecture for Transformer Acceleration](https://dl.acm.org/doi/10.1145/3701034)
- [HyperSpikeASIC](https://dl.acm.org/doi/abs/10.1109/TCAD.2023.3264167) · [HyperSpike](https://www.researchgate.net/publication/360730631_HyperSpike_HyperDimensional_Computing_for_More_Efficient_and_Robust_Spiking_Neural_Networks) · [SpikeHD](https://www.nature.com/articles/s41598-022-11073-3) · [SynapseHD](https://www.sciencedirect.com/science/article/abs/pii/S0925231225024294) · [HyperEncoding](https://dl.acm.org/doi/10.1145/3716368.3735233) · [HD Decoding of SNNs](https://arxiv.org/abs/2511.08558)
- [A Survey on HDC/VSA, Part I](https://dl.acm.org/doi/10.1145/3538531)
