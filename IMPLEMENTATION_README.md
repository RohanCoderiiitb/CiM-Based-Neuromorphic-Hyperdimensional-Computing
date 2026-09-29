# CIM-NeuroHDC — Implementation Plan and Phase 1 Guide

**Source of truth.** This document is derived from, and must not contradict:
`README.md` (literature analysis), `neurohdc_implementation_audit.md` (Part A —
paper-faithful behaviour), `dvs_accuracy_report.md` (frozen training config),
`firing_rate_results.md` + `firing_rate_summary.json` (Phase 1 measurements),
`phase3_results.md` (Experiments 1–4), `novelty_review_and_proposals.md`, and
`phase4_architecture_and_plan.md` (architecture freeze).

**No implementation code appears in this document.**

**Tags:** `[S]` stated in the NeuroHDC paper · `[M]` measured in this project ·
`[D]` derived here · `[O]` our design choice.

---

# PART 0 — Fixed reference data

Every number an implementer needs, in one place. Do not re-derive these.

## 0.1 Algorithm constants (paper-faithful — never change these)

| Parameter | Value | Source |
|---|---|---|
| Input neurons | 512 (= 2 polarity × 16 × 16) | `[S]` §IV-A |
| Spiking neurons `n` | 20 | `[S]` §IV-B1 |
| Timesteps `T` | 100 | `[S]` §IV-A |
| Hypervector dimension `D_hv` | `n·T` = 2000 | `[S]` eq. (7) |
| Neuron model | IF — no leak, no bias | `[S]` §II-A eq. (2) |
| Reset | hard, `V_reset = 0` | `[S]` §II-A eq. (1) |
| Address generation | `addr = p·256 + ⌊y/β⌋·16 + ⌊x/β⌋` | `[S]` §V-B eq. (19) |
| Timestep boundary | exactly `N_e` **events** (not time) | `[S]` §III-B, §V-A |
| Per-event accumulate | `R^V_j += W_s_j(addr)` | `[S]` §V-B eq. (20) |
| Encoding | direct concatenation, flatten only | `[S]` eq. (7) |
| Query | `Score_i = Σ_t Σ_m (h^u XNOR C_i^u)` | `[S]` eq. (21) |
| Weight precision | int8 signed, QAT | `[S]` §III-C |
| `β` (DVS-Gesture) | 8 (128→16) | `[S]`/`[D]` |

## 0.2 Frozen trained-model parameters (our reimplementation)

| Parameter | Value | Source |
|---|---|---|
| QAT granularity | **per-channel** (one scale per neuron) | `[O]` `dvs_accuracy_report.md` §4 |
| `V_thresh` | trainable scalar; seed-0 final = **11.3314** | `[O]` `firing_rate_summary.json` |
| Baseline test accuracy | 82.36% ± 2.08% (3 seeds); seed 0 = **84.58%** | `[M]` |
| Paper's reported accuracy | 87.5% | `[S]` |

## 0.3 Measured workload statistics (drive every sizing decision)

| Statistic | DVS-Gesture | N-MNIST | Source |
|---|---|---|---|
| Events per sample (mean) | 407,124 | 4,204 | `[M]` |
| `N_e` (events/timestep, mean) | 4,071 | 41.5 | `[M]` |
| **Active input addresses per timestep** | **51.0%** of 512 (P10 35.5, P50 51.2, P90 66.0) | 5.77% | `[M]` Exp 3 |
| Per-address event count | median 3, P90 34, P99 230 | median 1, P90 2, P99 4 | `[M]` Exp 3 |
| Consecutive-timestep active-set Jaccard | 0.545 | 0.359 | `[M]` Exp 3 |
| Output firing rate `r` | 0.3755 (s0), 0.4367 (s1), 0.4550 (s2) | 0.1869 | `[M]` |
| `k_t` (active neurons/timestep) | mean 7.51, **max 15, never 16–20** | 3.74 | `[M]` |
| Silent-timestep fraction `σ` | 0.0002 | 0.038 | `[M]` |
| Early exit θ=128 | **32.1% events saved, 0.0 pp loss** | 4.9% saved | `[M]` Exp 2 |
| Early exit θ=64 | 58.4% events saved, −0.4 pp | — | `[M]` Exp 2 |

## 0.4 Derived bit widths

| Quantity | Width | Derivation |
|---|---|---|
| Address | 9 b unsigned | 512 addresses |
| Weight | 8 b signed | `[S]` |
| Event count `c[addr]` | **12 b** worst case | `⌈log₂(N_e+1)⌉`; 8 b covers P99 — **measure the true max before freezing** |
| MVM output `X_j(t)` | **20 b signed** | `|X| ≤ N_e·128 = 521,088`. Tight **only because `Σ_addr c[addr] = N_e` exactly**, a consequence of event-count binning `[D]` |
| Membrane potential `V_j` | **27 b signed** worst case | `T · max|X|`. NeuroHDC used 22 b under different scaling — **measure our reference model's observed range; do not copy 22** |
| Weight memory | 512 × 160 b = 81,920 b = **10.0 kB** | matches NeuroHDC's 10.24 kB `[S]` |

> **Implementer note.** Two widths above are marked *measure before freezing*.
> Sizing them from worst-case bounds wastes area; sizing them from the P99 risks
> silent overflow. Phase 0 measures the true maxima over the full dataset and
> the spec is frozen from that.

---

# PART 1 — Full project implementation plan

## Phase structure

The user-suggested ordering is sound, with two changes justified below:

- **A Phase 0 is inserted.** Bit-exactness against the verified software model is
  a hard requirement. That is impossible without an integer-domain reference
  model and exported golden vectors existing *first*. Attempting RTL against a
  float model is the single most common way this class of project produces
  unverifiable results.
- **Hardware modelling (NeuroSim) runs as a parallel track from Phase 1, not as
  a late phase.** Array organization decisions in Phases 1–2 depend on its
  output; deferring it to Phase 5 means making those decisions blind.

```
Phase 0  Fixed-point reference + golden vectors        ── prerequisite
Phase 1  CIM-based SNN computation                     ── AER → 20-bit spike vector
Phase 2  CIM-based HDC query                           ── spikes → class scores
Phase 3  Integrated CIM-NeuroHDC pipeline              ── end-to-end inference
Phase 4  Margin-based temporal termination             ── the primary contribution
Phase 5  PPA: synthesis, P&R, NeuroSim                 ── (modelling starts at P1)
Phase 6  Validation, ablations, results                ── paper-ready numbers
```

---

## Phase 0 — Fixed-point reference model and golden vector export

**Objective.** Produce an integer-domain Python model that is bit-exact with the
verified float NeuroHDC model, and export golden vectors that every later phase
verifies against.

**System-level functionality.** Re-express the frozen trained model in the
integer domain used by hardware: integer weights, integer accumulations, and
per-neuron integer thresholds. Establish that the spike raster it produces is
identical to the float model's on the full test set.

**Hardware blocks.** None — software only.

**Inputs.** Frozen checkpoints `frozen_seed{0,1,2}.pt`; DVS-Gesture and N-MNIST
test splits; the existing verified model in `src/neurohdc.py`.

**Outputs.**
- Integer-domain reference model
- Weight memory image (hex/binary) per seed
- Per-neuron integer thresholds
- Golden vectors: event streams, per-timestep count vectors, per-timestep `X_j`,
  `V_j` traces, spike rasters, class scores, predictions
- Measured maxima for `c[addr]`, `X_j`, `V_j` → frozen bit widths

**Dependencies.** None.

**Main tasks.**
1. Formalize the integer mapping. Software computes `X_j = s_j · (W^int8_j · c)`
   where `s_j` is the per-channel scale. Hardware accumulates `V^int_j` in the
   integer weight domain and compares against `thresh^int_j = V_thresh / s_j`.
   Because `thresh^int_j` is generally non-integer, it is stored as fixed-point
   with `F` fractional bits and the comparison is `(V^int_j << F) ≥ thresh^fx_j`.
2. Sweep `F` and find the smallest value at which the integer model's spike
   raster matches the float model's **exactly** on the full test set.
3. Measure true maxima of `c[addr]`, `X_j`, `V_j` across both datasets; freeze
   `W_C`, `W_X`, `W_V`.
4. Export golden vectors in a stable, documented format.
5. Verify the batching identity holds bit-exactly (§P1.1.3).

**Verification requirements.**
- Integer model spike raster == float model spike raster, **240/240 DVS-Gesture
  test samples, bit-for-bit**, and on N-MNIST.
- Integer model prediction == recorded prediction for every sample.
- Where the chosen `F` leaves residual near-threshold mismatches, the count must
  be **zero**; if it cannot be made zero, the cause must be identified and
  documented before proceeding (do not proceed with "a few mismatches").

**Deliverables.** Integer reference model; frozen bit-width table; weight images;
golden vector set; `phase0_report.md` documenting `F`, measured maxima, and the
exact-match proof.

**Completion criteria.** Bit-exact match on both datasets, all three seeds, with
frozen bit widths and exported vectors under version control.

---

## Phase 1 — CIM-based SNN computation

**Objective.** RTL that converts an AER event stream into the `20×T` spike
raster, bit-exact with the Phase 0 reference.

**System-level functionality.** Address generation (SumPool), event accumulation
into a 512-entry count vector per timestep, bit-serial in-array MVM against the
512×20 int8 weight memory, IF neuron update with hard reset, spike vector
emission, timestep and inference control.

**Hardware blocks.** Address generator; event/timestep counter; 512-entry count
memory; weight CIM macro (bit-plane organized); bit-plane sequencer; AND-popcount
compute; shift-accumulate; IF neuron datapath ×20; spike register; control FSM;
configuration registers.

**Inputs.** AER events `(t', p, x, y)`; config (`N_e`, `β`, `thresh^fx_j`, `T`);
weight image.

**Outputs.** 20-bit spike vector + valid strobe + timestep index — **the binary
waist**; end-of-inference strobe.

**Dependencies.** Phase 0.

**Main tasks.** Detailed in Part 2.

**Verification requirements.** Bit-exact `20×100` raster against Phase 0 golden
vectors on the full DVS-Gesture test set; all assertions pass; lint clean.

**Deliverables.** RTL; cocotb testbench; per-module unit tests; access-count
instrumentation; `phase1_report.md`.

**Completion criteria.** See §P1.5.

---

## Phase 2 — CIM-based HDC query

**Objective.** RTL that consumes the 20-bit spike vector per timestep and
produces `N` class scores, bit-exact with the reference.

**System-level functionality.** Spike-gated access to the class-hypervector
array, per-timestep partial-score accumulation, per-class bias application,
argmax. Two configurations, both built:
- **Unfactorized:** 2000×`N` class memory, `n`-bit slice per timestep — the
  faithful baseline (`[S]` eq. 21)
- **R=1 factorized:** 20×`N` stationary array + `T`×`N` sign table — the
  contribution (16 macros → 1; row activation 0.38% → 37.5%) `[M]` Exp 1b

**Hardware blocks.** Class-HV array (both mappings); spike-gated row/column
enable; XNOR-popcount (unfactorized) or AND-popcount + sign-flip accumulate
(factorized); `N` score accumulators; per-class `‖C_i‖₁` bias registers; argmax
comparator.

**Inputs.** 20-bit spike vector + valid; class-HV image; per-class bias
constants.

**Outputs.** `N` scores; predicted class; score-valid strobe.

**Dependencies.** Phase 1 (interface), Phase 0 (golden scores).

**Main tasks.**
1. Implement both mappings behind a common interface, selected by parameter.
2. Implement the exact identity `argmax_i [2(h·C_i) − ‖C_i‖₁]` and assert
   equivalence with the XNOR-popcount form at every prefix length — this was
   verified in software on 100.0000% of 24,000 comparisons per seed `[M]` Exp 2
   and must hold in RTL.
3. Instrument per-timestep array activations and rows gated.

**Verification requirements.** Scores bit-exact vs reference at every timestep
prefix, not only at `t=T` (prefix correctness is what Phase 4 depends on).

**Deliverables.** RTL for both mappings; testbench; `phase2_report.md` with the
measured access counts for each mapping.

**Completion criteria.** Both mappings bit-exact on the full test set; prefix
scores match at all `t`; access counts logged and consistent with Exp 1b's
analytic table.

---

## Phase 3 — Integrated CIM-NeuroHDC pipeline

**Objective.** Phases 1 and 2 connected through the binary waist, running full
inferences end to end.

**System-level functionality.** Streaming AER in, prediction out, with correct
handshaking, backpressure, and timestep synchronization between the SNN and
query stages.

**Hardware blocks.** Top-level integration; handshake/backpressure logic;
shared configuration and control; optional event input FIFO.

**Inputs.** AER stream; full configuration.

**Outputs.** Prediction + valid; instrumentation counters.

**Dependencies.** Phases 1, 2.

**Main tasks.**
1. Define and implement the waist protocol (valid/ready, timestep index).
2. Resolve the stall policy during MVM (§P1.2.4) and verify no event loss.
3. End-to-end regression over the full test set.
4. Instrument every access counter needed by Phase 5.

**Verification requirements.** Predictions match the reference for 240/240
DVS-Gesture test samples. Zero dropped events. No protocol violations under
randomized inter-event gaps.

**Deliverables.** Integrated RTL; regression suite; `phase3_report.md`.

**Completion criteria.** Full-test-set prediction match; clean protocol
assertions; reproducible regression.

---

## Phase 4 — Margin-based temporal termination *(primary contribution)*

**Objective.** Add the exit mechanism: the class-score margin gates event
ingestion.

**System-level functionality.** After each timestep's score update, compare the
top-1 and top-2 partial scores. When the margin reaches `θ`, assert exit: stop
accepting events, emit the prediction, and idle both arrays.

**Hardware blocks.** Top-2 selection over `N` scores; margin comparator;
exit FSM; event-ingestion gate; `θ` configuration register.

**Inputs.** `N` partial scores per timestep; `θ`.

**Outputs.** Exit strobe; exit timestep; prediction; ingestion-enable.

**Dependencies.** Phase 3.

**Main tasks.**
1. Implement top-2 selection without a full sort (`N` is 10–24).
2. Implement the exit FSM and ensure the emitted prediction equals the argmax at
   the exit timestep.
3. Instrument events ingested vs. events available.
4. Sweep `θ` in hardware and reproduce the software curve.

**Verification requirements.** For every `θ`, hardware exit timestep and
prediction must match the software replay **exactly** (the software sweep is
already computed and stored in `exp2_early_exit.json`). At `θ=128`, accuracy
must equal the full-`T` accuracy and mean events ingested must reproduce the
measured 67.9% `[M]`.

**Deliverables.** RTL; `θ` sweep results; `phase4_report.md` with the hardware
accuracy-vs-events curve overlaid on the software curve.

**Completion criteria.** Hardware/software curves match; no accuracy loss at
`θ=128`; measured event saving within tolerance of 32.1%.

---

## Phase 5 — Hardware modelling and PPA *(parallel track from Phase 1)*

**Objective.** Area, energy and timing for the complete design, from a flow
directly comparable to NeuroHDC's own.

**System-level functionality.** Synthesis and place-and-route of the digital
logic; NeuroSim modelling of the CIM arrays; combination with Phase 3/4 access
counts into energy-per-inference.

**Hardware blocks.** All.

**Inputs.** RTL; SRAM/CIM macro models; access counts; technology libraries.

**Outputs.** Area breakdown; energy per inference; critical path / max
frequency; utilization.

**Dependencies.** Phases 1–4 for final numbers; **starts at Phase 1** for array
organization feedback.

**Main tasks.**
1. Yosys synthesis with the SkyWater 130 nm library — **the same flow NeuroHDC
   used** (`[S]` §VI-A: Yosys + SkyWater 130 nm + OpenROAD + PrimeTime), so the
   comparison is apples-to-apples.
2. OpenROAD floorplan/place/route; OpenSTA timing.
3. Generate SRAM macros with OpenRAM; mirror NeuroHDC's 512×32 b organization
   (4 neurons per macro, 5 macros) for comparability `[S]` §V-A.
4. NeuroSim modelling of both CIM arrays.
5. Scale to 45 nm using Stillmaker & Baas, as NeuroHDC did, for cross-node
   comparison `[S]` §VI-B.

**Verification requirements.** Timing closure at the target frequency; post-P&R
functional equivalence; energy model inputs traceable to logged access counts.

**Deliverables.** PPA tables; area/energy breakdowns; `phase5_report.md`.

**Completion criteria.** Closed timing, complete PPA numbers for every
configuration to be reported.

---

## Phase 6 — Validation, ablations, results

**Objective.** Paper-ready evidence, with each contribution separately
attributable.

**Ablations — these are what make the contributions separable.**

| Configuration | Isolates |
|---|---|
| Full design | — |
| Early exit **off** | value of Phase 4 |
| Factorization **off** (unfactorized class HV) | value of the R=1 mapping |
| Both off | the CIM pipeline alone vs NeuroHDC's ASIC |
| Event-serial vs batched Array 1 | value of event batching |
| N-MNIST instead of DVS-Gesture | dataset dependence — **must be reported** |

**Baselines.** NeuroHDC's own ASIC (the fair comparison — 12.68 kB, with an FPGA
baseline published for reproduction `[S]` §VI-C); IMPULSE as the SNN-CIM
reference; MEMHD and CAMPRO as HDC-CIM references.

**Metrics.** Energy/inference, area, latency, memory traffic, array utilization,
accuracy, events ingested.

**Completion criteria.** Every claimed contribution has an ablation isolating it;
every number traceable to a logged run; the reimplementation accuracy gap
(82.36% vs 87.5%) disclosed in the results section, not buried.

---

## Cross-phase rules

1. **Bit-exactness is non-negotiable through Phase 3.** Any divergence from the
   Phase 0 reference is a bug until proven otherwise.
2. **Never modify the algorithm.** Part A of the audit lists 16 paper-faithful
   items. Phase 2's factorization is the *only* sanctioned deviation, it is
   parameterized, and the unfactorized path must remain functional.
3. **Every run produces a sidecar** with config, git SHA, seed, and tool
   versions.
4. **Instrument from day one.** Access counters added retroactively are never
   trusted.
5. **Report dataset-dependence.** Exp 2 and Exp 3 both split sharply between
   DVS-Gesture and N-MNIST. A single-dataset claim presented as general is a
   defect.

---

# PART 2 — Phase 1 detailed implementation guide

## P1.1 System-level plan

### P1.1.1 Dataflow, end to end

```
AER event (t', p, x, y)
   │
   ├─► [A] Address generator          addr = p·256 + ⌊y/β⌋·16 + ⌊x/β⌋      1 cycle
   │                                   pure combinational; SumPool is FREE
   ├─► [B] Count memory               c[addr] += 1                         1 cycle R-M-W
   │
   └─► [C] Event counter              ev_cnt += 1
                                       ev_cnt == N_e ?  ──► TIMESTEP BOUNDARY
                                                              │
        ┌─────────────────────────────────────────────────────┘
        ▼
   [D] Bit-plane sequencer      for b in 0..W_C-1:
        │                          plane_b = { addr : c[addr][b] == 1 }   (512-bit vector)
        │                          if plane_b == 0 : SKIP          ◄── measured win
        ▼
   [E] Weight CIM macro         for each weight bit-plane k in 0..7:
        │                          partial[j][b][k] = popcount(plane_b AND Wbit[j][k])
        ▼
   [F] Shift-accumulate         X_j = Σ_b Σ_k (±)2^(b+k) · partial[j][b][k]
        ▼
   [G] IF neuron ×20            V_j += X_j
        │                        fire_j = (V_j << F) ≥ thresh_fx_j
        │                        V_j = fire_j ? 0 : V_j          (hard reset)
        ▼
   [H] Spike register           S(t) = {fire_0 … fire_19}
        │
        ├─► 20-bit spike vector + valid + timestep_idx   ──►  PHASE 2
        │
   [I] Timestep control         clear count memory; ev_cnt = 0; t += 1
                                 t == T ? ──► end-of-inference
```

### P1.1.2 Event and address handling

Events arrive in AER form. The address generator implements eq. (19) exactly.
With `β = 8` for DVS-Gesture (128→16) the divisions are right-shifts by 3, and
`⌊y/8⌋·16` is a shift-and-concatenate. **No arithmetic unit is required** —
this is why SumPool is free in hardware `[S]` §V-B.

`β` must be a configurable parameter (power-of-two shift amount) because it is
dataset-dependent.

### P1.1.3 Event accumulation — and why batching is bit-exact

NeuroHDC accumulates per event: `R^V_j += W_s_j(addr_e)` for each event `e`
`[S]` eq. (20). Batching accumulates counts first, then multiplies:

```
Σ_{e ∈ timestep} W_j[addr_e]  ≡  Σ_{addr} c[addr] · W_j[addr]
```

This is an exact re-association of the same sum over integers — **not an
approximation**. Both sides are computed in the integer weight domain with no
intermediate rounding, so the result is bit-identical. This identity must be
asserted in the Phase 0 reference and in the RTL testbench.

Two consequences worth stating in the paper:

- `Σ_addr c[addr] = N_e` **exactly**, by construction of event-count binning.
  This gives the tight bound `|X_j| ≤ N_e · 128` used to size `W_X` at 20 bits
  `[D]`. A time-binned SNN has no such bound.
- Weight reads drop from 407,124 per sample (event-serial) to ~26,112
  (batched, active addresses only) — **15.6× fewer** `[D]`, using the measured
  51.0% address occupancy `[M]`.

### P1.1.4 The 512×20 weight computation

Weights are int8 signed, stored **bit-plane transposed**: for each neuron `j`
and weight bit `k`, a 512-bit column `Wbit[j][k]`. The MVM decomposes as

```
X_j = Σ_addr c[addr] · W_j[addr]
    = Σ_{b=0}^{W_C-1} Σ_{k=0}^{7}  σ(k) · 2^(b+k) · popcount( plane_b  AND  Wbit[j][k] )
```

where `plane_b` is the 512-bit vector of bit `b` of all counts, and `σ(k) = −1`
for `k = 7` (the sign bit of two's-complement int8), `+1` otherwise.

`popcount(A AND B)` over 512 bits is the digital-CIM primitive — the same class
of operation IMPULSE builds in its column peripherals `[S]`. This is fully
synthesizable, requires no analog, and is bit-exact.

**Bit-plane skipping.** Measured per-address counts are median 3, P90 34, P99
230 `[M]`. Therefore planes 8–11 are empty for >99% of addresses `[D]`. Testing
`plane_b == 0` and skipping costs one 512-bit OR-reduce and removes 8 popcount
operations per skipped plane. **Instrument the skip rate — it is a result.**

### P1.1.5 IF neuron processing

Per neuron `j`, per timestep:

```
V_j ← V_j + X_j                          W_V-bit signed adder
fire_j ← (V_j << F) ≥ thresh_fx_j        W_V+F-bit signed comparator
V_j ← fire_j ? 0 : V_j                   hard reset, V_reset = 0
```

No leak term, no bias, no soft reset — any of those would break Part A of the
audit. With `n = 20` all twenty neurons update in parallel in one cycle;
time-multiplexing is available as a parameter if area demands it.

### P1.1.6 Timestep and inference control

- `ev_cnt` increments per accepted event; at `ev_cnt == N_e` the boundary fires.
- `N_e` is a configuration register, matching NeuroHDC's own control model
  `[S]` §V-A.
- At the boundary: stop accepting events (or switch buffers), run the MVM,
  update neurons, emit the spike vector, clear the count memory, reset `ev_cnt`,
  increment `t`.
- At `t == T`: assert end-of-inference and reset all `V_j`.
- **Short-sample policy:** if the stream ends before `T` timesteps, pad with
  empty timesteps — this matches the reference model's `pad_empty` policy and
  must be identical in RTL.

### P1.1.7 Interface to Phase 2 — the binary waist

| Signal | Width | Direction | Meaning |
|---|---|---|---|
| `spike_vec_o` | 20 | out | `S(t)`, one bit per neuron |
| `spike_valid_o` | 1 | out | asserted one cycle per timestep boundary |
| `timestep_idx_o` | 7 | out | `t`, 0…T−1 |
| `inference_done_o` | 1 | out | `t == T` reached, or early exit (Phase 4) |
| `ingest_en_i` | 1 | in | **event-ingestion gate — reserved for Phase 4** |

`ingest_en_i` must be present and functional in Phase 1 even though nothing
drives it low until Phase 4. Retrofitting an ingestion gate after integration is
where event-loss bugs come from.

---

## P1.2 Detailed module architecture

Classification: **[CIM]** in-array compute · **[DIG]** digital peripheral/control
· **[BUF]** storage · **[NS]** to be modelled in NeuroSim.

---

### [A] `addr_gen` — **[DIG]**

| | |
|---|---|
| **Purpose** | Implement eq. (19); realize SumPool as address truncation |
| **Inputs** | `p_i` (1 b), `x_i` (`log2(W_SENSOR)` b), `y_i`, `ev_valid_i`, `beta_shift_i` (3 b) |
| **Outputs** | `addr_o` (9 b), `addr_valid_o` |
| **Internal state** | None — purely combinational |
| **Representation** | Unsigned |
| **Dataflow** | `addr = {p, y >> beta_shift, x >> beta_shift}` with the field widths of eq. (19) |
| **Control** | Flow-through; one address per valid event |
| **Cycle** | 0-cycle combinational, registered at the output |
| **Configurable** | `beta_shift`, sensor width/height |

> Assert `addr_o < 512` for every valid event. An out-of-range address means a
> `β` or sensor-geometry misconfiguration and must fail loudly, not wrap.

---

### [B] `count_mem` — **[BUF]**

| | |
|---|---|
| **Purpose** | Accumulate per-address event counts within one timestep |
| **Inputs** | `addr_i`, `incr_i`, `clear_i`, `read_plane_i` (bit index) |
| **Outputs** | `plane_o` (512 b — one bit per address), `plane_nonzero_o` |
| **Internal state** | 512 × `W_C` counts |
| **Representation** | Unsigned, `W_C` frozen in Phase 0 |
| **Dataflow** | Read-modify-write on each event; bit-plane read at the boundary |
| **Control** | Bulk clear at the timestep boundary |
| **Cycle** | 1-cycle R-M-W; back-to-back events to the same address must be handled (forwarding or a 1-cycle stall) |
| **Configurable** | `W_C`, ping-pong on/off |

**Design decisions to make explicitly:**

1. **Storage style.** A 512×`W_C` register file is large (512×12 = 6,144 flops)
   but supports 1-cycle R-M-W and cheap bit-plane extraction. An SRAM is denser
   but bit-plane extraction requires reading all 512 entries. **Recommendation:
   register file for the first implementation**, revisit after Phase 5 area
   numbers. Document the cost — at 6,144 flops this is a non-trivial fraction of
   the design and must not be hidden.
2. **Ping-pong or stall.** Ping-pong doubles the cost (~1.6 kB for `W_C`=12) —
   13% of NeuroHDC's entire 12.68 kB model. A single buffer with a stall during
   the MVM costs ~13–52 cycles per 4,071 events (~1% throughput). **Recommend
   single buffer + stall**; make ping-pong a parameter.
3. **Same-address back-to-back events.** Measured counts have a long tail
   (P99 = 230) and the active set persists across timesteps (Jaccard 0.545)
   `[M]`, so repeated addresses are common. Handle by forwarding, not by
   assuming they don't happen.
4. **Overflow.** Must be impossible by construction, or flagged. Phase 0's
   measured maximum determines `W_C`.

---

### [C] `event_ctr` / `timestep_ctr` — **[DIG]**

| | |
|---|---|
| **Purpose** | Define the event-count timestep boundary |
| **Inputs** | `ev_accept_i`, `N_e_i` (13 b), `T_i` (7 b), `rst_n_i` |
| **Outputs** | `tstep_boundary_o`, `timestep_idx_o`, `inference_done_o` |
| **Internal state** | `ev_cnt` (13 b), `t_cnt` (7 b) |
| **Control** | `ev_cnt` resets at the boundary; `t_cnt` increments |
| **Configurable** | `N_e`, `T` |

> `N_e` and `T` are runtime-configurable registers, mirroring NeuroHDC's
> register group `[S]` §V-A. Do not hard-code them.

---

### [D] `plane_seq` — **[DIG]**

| | |
|---|---|
| **Purpose** | Sequence input bit-planes; skip empty ones |
| **Inputs** | `start_i`, `plane_nonzero_i` |
| **Outputs** | `plane_idx_o` (4 b), `plane_valid_o`, `planes_done_o`, `planes_skipped_o` (counter) |
| **Internal state** | Plane index, skip counter |
| **Control** | Iterate `b = 0 … W_C−1`, assert valid only when `plane_nonzero_i` |
| **Cycle** | 1 cycle per non-skipped plane |
| **Configurable** | `W_C`, skip enable (for ablation) |

`planes_skipped_o` is instrumentation and must be logged per timestep.

---

### [E] `cim_weight_macro` — **[CIM]** / **[NS]**

| | |
|---|---|
| **Purpose** | Store `W_s` bit-plane transposed; compute `popcount(plane AND Wbit)` |
| **Inputs** | `plane_i` (512 b), `plane_idx_i`, `wr_addr_i`, `wr_data_i`, `wr_en_i` |
| **Outputs** | `partial_o[20][8]` — popcounts, each `⌈log₂513⌉` = 10 b |
| **Internal state** | 512 × 160 b = 10.0 kB |
| **Representation** | Weights int8 two's complement, stored as 8 bit-planes per neuron |
| **Dataflow** | One 512-bit AND + popcount per (neuron, weight-plane) pair |
| **Control** | Driven by `plane_seq` |
| **Cycle** | Parameterizable: fully parallel (160 popcounts/cycle) vs time-multiplexed over neuron groups |
| **Configurable** | `N_PARALLEL_COLS`, macro tiling |

**Macro organization.** Mirror NeuroHDC's choice — 512×32 b macros holding 4
neurons each, 5 macros `[S]` §V-A — so the Phase 5 area comparison is
apples-to-apples.

**This is the block NeuroSim models.** The RTL implements the bit-exact
functional behaviour; NeuroSim supplies the energy/area/latency for the array
itself. Keep the RTL boundary clean so the macro can be swapped for a model.

**Weight loading.** A data-write mode must exist, as in NeuroHDC `[S]` §V-B.
Loading is bit-plane transposed; the transposition happens in the Phase 0 export
script, not in hardware.

---

### [F] `shift_accum` — **[DIG]**

| | |
|---|---|
| **Purpose** | Combine partial popcounts into `X_j` |
| **Inputs** | `partial_i[20][8]`, `plane_idx_i` |
| **Outputs** | `X_o[20]` (`W_X` = 20 b signed), `X_valid_o` |
| **Internal state** | 20 accumulators, `W_X` bits |
| **Representation** | Signed two's complement |
| **Dataflow** | `acc_j += Σ_k σ(k)·2^(b+k)·partial[j][k]`, with `σ(7) = −1` |
| **Control** | Accumulate across planes; emit at `planes_done` |
| **Cycle** | 1 cycle per plane |

> The `k = 7` sign handling is the single most likely source of a subtle
> bit-mismatch. Give it a dedicated directed test with weights at −128, −1, 0,
> +1, +127.

---

### [G] `if_neuron_array` — **[DIG]**

| | |
|---|---|
| **Purpose** | IF dynamics for 20 neurons |
| **Inputs** | `X_i[20]`, `X_valid_i`, `thresh_fx_i[20]`, `clear_v_i` |
| **Outputs** | `spike_o` (20 b), `spike_valid_o`, `V_o[20]` (debug) |
| **Internal state** | `V[20]`, `W_V` bits signed |
| **Representation** | `V` integer signed; `thresh_fx` fixed-point with `F` fractional bits |
| **Dataflow** | `V += X`; `fire = (V << F) ≥ thresh_fx`; `V = fire ? 0 : V` |
| **Control** | One update per timestep |
| **Cycle** | 1 cycle, all 20 in parallel |
| **Configurable** | `W_V`, `F`, parallel vs time-multiplexed |

**Per-neuron thresholds.** Because quantization is per-channel, each neuron has
its own `thresh_fx_j = V_thresh / s_j` `[O]`. A single shared threshold is
wrong and will silently degrade accuracy.

`V_o` is debug-only and must be excluded from synthesis by parameter.

---

### [H] `spike_reg` — **[BUF]** · **[I] `snn_ctrl`** — **[DIG]**

`spike_reg`: 20-bit register holding `S(t)`, driving the waist.

`snn_ctrl`: the top FSM —
`IDLE → LOAD_WEIGHTS → RUN(ACCEPT_EVENTS ⇄ MVM → NEURON → EMIT → CLEAR) → DONE`.
Mirrors NeuroHDC's three-state operating mode register (idle / data-write /
execution) `[S]` §V-A. Owns `ingest_en_i` handling and the stall policy.

---

## P1.3 Tools, technologies and packages

### Software / reference modelling

| Tool | Purpose |
|---|---|
| Python 3.10+ | Reference model, vector export, analysis |
| PyTorch | The verified float model already in `src/neurohdc.py` |
| NumPy | Integer-domain reference; bit-exact arithmetic with explicit dtypes |
| SpikingJelly | Dataset loading; **equal-event-count binning via `split_by='number'`** — matches eq. (8) |
| Tonic | Alternative loader; ASL-DVS if added later |
| pytest | Reference-model unit tests |
| pandas, matplotlib | Result tables and figures |

### RTL

| Tool | Purpose |
|---|---|
| SystemVerilog (IEEE 1800) | Design language |
| Verible | Linting and formatting; enforces naming conventions in CI |

### Simulation and debug

| Tool | Purpose |
|---|---|
| **Verilator** | Fast cycle-accurate simulation; primary regression engine |
| Icarus Verilog | Secondary simulator — catches tool-specific interpretation bugs |
| **cocotb** | **Python testbenches. This is the key choice: it lets the testbench import the PyTorch/NumPy reference directly, so the golden model is the actual verified model rather than a reimplementation of it.** |
| cocotb-test | pytest integration for cocotb |
| GTKWave / Surfer | Waveform debug |
| SVA | Inline assertions |

### Synthesis and physical design

| Tool | Purpose |
|---|---|
| **Yosys** | Synthesis — **the tool NeuroHDC used** `[S]` §VI-A |
| open_pdks / SkyWater 130 nm | **NeuroHDC's own node** — required for a fair area/energy comparison |
| OpenRAM | SRAM macro generation (weight memory, count memory) |
| **OpenROAD / OpenLane 2** | Floorplan, placement, CTS, routing |
| OpenSTA | Static timing |
| KLayout | Layout inspection, DRC |

### CIM modelling

| Tool | Purpose |
|---|---|
| **DNN+NeuroSim V2.0** | Array-level area, energy, latency for the CIM macros. **Replaces the abandoned CACTI/`α` approach** — CACTI models SRAM, NeuroSim models CIM and reports energy directly. MEMHD used it `[S]`. |

### Automation

| Tool | Purpose |
|---|---|
| Make or CMake | Build orchestration |
| pytest + cocotb-test | Regression driver |
| GitHub Actions (or local) | CI: lint → unit → module → integration |
| Git LFS | Golden vectors and weight images |

---

## P1.4 Codebase and implementation guidelines

### P1.4.1 Directory structure

```
cim-neurohdc/
├── README.md
├── docs/
│   ├── architecture_spec.md
│   ├── bitwidth_table.md            # frozen in Phase 0
│   └── interface_spec.md            # the binary waist protocol
├── model/
│   ├── neurohdc/                    # existing verified float model (unchanged)
│   ├── fixedpoint/                  # Phase 0 integer-domain reference
│   │   ├── int_model.py
│   │   ├── quantize.py              # per-channel scales, thresh_fx
│   │   └── batching.py              # count-vector equivalence
│   └── export/
│       ├── export_weights.py        # -> bit-plane transposed hex
│       ├── export_vectors.py        # -> golden vectors
│       └── formats.md               # vector file format spec
├── rtl/
│   ├── pkg/
│   │   └── cim_neurohdc_pkg.sv      # ALL parameters live here
│   ├── phase1_snn/
│   │   ├── addr_gen.sv
│   │   ├── count_mem.sv
│   │   ├── event_ctr.sv
│   │   ├── plane_seq.sv
│   │   ├── cim_weight_macro.sv
│   │   ├── shift_accum.sv
│   │   ├── if_neuron_array.sv
│   │   ├── spike_reg.sv
│   │   ├── snn_ctrl.sv
│   │   └── snn_top.sv
│   └── common/
│       ├── popcount.sv
│       └── sync_fifo.sv
├── tb/
│   ├── cocotb/
│   │   ├── test_addr_gen.py
│   │   ├── ...
│   │   └── test_snn_top.py
│   ├── common/
│   │   ├── golden.py                # loads Phase 0 vectors
│   │   └── drivers.py               # AER driver, waist monitor
│   └── vectors/                     # Git LFS
├── syn/    pnr/    neurosim/
├── artifacts/
│   ├── phase0/ phase1/ ...
│   └── logs/
└── scripts/
```

### P1.4.2 Module responsibilities

One module, one responsibility. Specifically: `addr_gen` does not count;
`count_mem` does not extract bit-planes on its own schedule (the sequencer
drives it); `cim_weight_macro` does not shift or sign-extend (that is
`shift_accum`); `if_neuron_array` does not know about timesteps (control tells
it when). Keeping the CIM macro boundary clean is what allows it to be replaced
by a NeuroSim model in Phase 5.

### P1.4.3 Naming conventions

| Element | Convention | Example |
|---|---|---|
| Module | `snake_case`, block-prefixed | `snn_if_neuron_array` |
| File | matches module name | `snn_if_neuron_array.sv` |
| Input port | `_i` suffix | `spike_valid_i` |
| Output port | `_o` suffix | `addr_o` |
| Bidirectional | `_io` | — |
| Clock / reset | `clk_i`, `rst_n_i` (active-low sync) | — |
| Parameter | `UPPER_SNAKE` | `N_NEURONS`, `W_V` |
| Localparam | `UPPER_SNAKE` | `ADDR_W` |
| Register | `_q` suffix | `v_mem_q` |
| Next-state | `_d` suffix | `v_mem_d` |
| Signed signal | `_s` suffix | `x_acc_s` |
| Handshake | `_valid` / `_ready` pairs | — |

### P1.4.4 Parameterization

**All parameters live in `cim_neurohdc_pkg.sv`.** No magic numbers in module
bodies. Minimum set:

```
N_NEURONS, N_TIMESTEPS, N_INPUTS, N_CLASSES
W_WEIGHT, W_COUNT, W_X, W_V, F_FRAC
BETA_SHIFT, SENSOR_W, SENSOR_H
N_PARALLEL_COLS, PING_PONG_EN, PLANE_SKIP_EN
DEBUG_EXPOSE_V
```

Runtime-configurable (registers, not parameters): `N_e`, `T`, `thresh_fx[j]`,
operating mode, `θ` (Phase 4). This mirrors NeuroHDC's register group `[S]` §V-A.

Every parameter carries a comment naming its source: paper equation, measured
statistic, or design choice.

### P1.4.5 Arithmetic conventions

1. **Two's complement throughout.** Declare signed signals `logic signed`; never
   rely on implicit conversion.
2. **Work in the integer weight domain.** `V` is an integer count of weight
   units. The per-channel scale `s_j` never appears in hardware — it is folded
   into `thresh_fx_j` in Phase 0.
3. **Fixed-point notation.** Document every signal as `Qm.f`. `V` is `Q(W_V−1).0`;
   `thresh_fx` is `Q(W_V−1).F`. The comparison left-shifts `V` by `F`.
4. **No saturation unless specified.** Widths are sized from Phase 0 measured
   maxima so overflow is impossible. If saturation is added anywhere, it breaks
   bit-exactness and must be justified and tested.
5. **Explicit width extension.** Always sign-extend explicitly before arithmetic.
6. **Rounding:** none anywhere in Phase 1. All operations are exact integer
   arithmetic. The only quantization is `thresh_fx`, decided once in Phase 0.

### P1.4.6 Interface conventions

- Valid/ready handshake on every inter-module data interface; `valid` must not
  depend combinationally on `ready`.
- Single synchronous active-low reset; all state resets to a defined value.
- Configuration via a simple register interface; config is stable during `RUN`.
- The binary waist (§P1.1.7) is specified in `docs/interface_spec.md` **before**
  Phase 2 starts.

### P1.4.7 Testbench structure

Every module gets: a cocotb test importing the Phase 0 reference; directed tests
for corner cases; randomized tests with a constrained generator; a scoreboard
comparing DUT output against the reference cycle by cycle.

**Reference-model methodology — the core of this plan.** The golden model is the
Phase 0 integer reference, imported directly into the cocotb testbench. It is
*not* reimplemented in SystemVerilog or in the testbench. That way:

- there is exactly one definition of correct behaviour;
- it is the same model already proven bit-exact against the verified float
  model on 240/240 test samples;
- a Phase 0 fix propagates to every testbench automatically.

### P1.4.8 Assertions and sanity checks

Minimum SVA set:

| Assertion | Module |
|---|---|
| `addr_o < N_INPUTS` on every valid event | `addr_gen` |
| count never exceeds `2^W_COUNT − 1` | `count_mem` |
| `Σ_addr c[addr] == N_e` at every timestep boundary | `count_mem` / `snn_ctrl` |
| `ev_cnt ≤ N_e` always | `event_ctr` |
| `timestep_idx < T` always | `timestep_ctr` |
| `spike_valid` asserted exactly once per timestep | `snn_top` |
| `V == 0` in the cycle after a spike | `if_neuron_array` |
| no `X` accumulator overflow | `shift_accum` |
| no event accepted while `ingest_en_i` is low | `snn_ctrl` |
| no event dropped during an MVM stall | `snn_ctrl` |

The third assertion is the strongest structural check available — it directly
encodes the event-count-binning invariant and will catch nearly any counting or
clearing bug.

### P1.4.9 Logging and results format

Every simulation emits JSON:

```
run metadata : git SHA, timestamp, tool versions, parameters, seed, config hash
per-timestep : timestep, events ingested, active addresses, planes skipped,
               MVM cycles, X[20], V[20], spike_vec, match/mismatch vs golden
per-sample   : sample id, label, prediction, raster hash, total cycles,
               total weight reads, total popcounts
summary      : samples run, exact matches, first mismatch location
```

The raster hash gives a one-line pass/fail across the whole test set; the
per-timestep detail is what you debug from when it fails.

---

## P1.5 Phase 1 verification plan

Five progressive levels. **Do not advance until the current level is clean.**

### Level 1 — Reference-model unit tests (Python, no RTL)

- Integer model reproduces the float model's raster exactly on the full test set
- Batching identity holds exactly (§P1.1.3)
- Bit-plane decomposition round-trips: `Σ_b 2^b · plane_b == c`
- `thresh_fx` quantization at the chosen `F` produces zero spike differences
- **Gate:** all pass on 240/240 DVS-Gesture and the N-MNIST test set.

### Level 2 — Module-level RTL verification

| Module | Directed tests | Randomized |
|---|---|---|
| `addr_gen` | corners of the sensor array, both polarities, every `β` | uniform (x,y,p) |
| `count_mem` | back-to-back same address, max count, clear | random address streams |
| `event_ctr` | `N_e` boundary, `N_e = 1`, short stream | random `N_e` |
| `plane_seq` | all planes empty, all full, single non-empty | random count vectors |
| `cim_weight_macro` | weights −128, −1, 0, +1, +127; plane all-0, all-1 | random weights × planes |
| `shift_accum` | **sign-bit handling (`k=7`)**; max positive, max negative | random partials |
| `if_neuron_array` | exactly-at-threshold, just-below, just-above, reset | random `X` sequences |

- **Gate:** every module matches the reference bit-for-bit on both directed and
  randomized stimulus; all module assertions pass.

### Level 3 — SNN-CIM integration

- `count_mem` + `plane_seq` + `cim_weight_macro` + `shift_accum` as one unit
- Synthetic count vectors including: empty, single address, all addresses, max
  count on one address, measured-realistic vectors sampled from Exp 3 data
- Compare `X_j` against the reference for every vector
- **Gate:** exact match on all vectors, including the realistic ones.

### Level 4 — Real event-stream testing

- Drive `snn_top` with actual DVS-Gesture event streams from the test set
- Randomize inter-event gaps to exercise the stall path
- Verify the spike raster per timestep, not only at the end
- Verify no events lost, and the `Σc == N_e` assertion holds every timestep
- **Gate:** exact raster match on at least 24 samples (one per class), with
  randomized timing.

### Level 5 — End-to-end comparison

- Full DVS-Gesture test set, 240 samples, all three seeds' weight images
- Compare the complete `20×100` raster, bit for bit
- Log access counts and compare against the architecture simulator's prediction
- **Gate:** see completion criteria.

### Phase 1 completion criteria

Phase 1 is complete when **all** hold:

1. **Bit-exactness.** 240/240 DVS-Gesture test samples produce a `20×100` raster
   identical to the Phase 0 reference, for all three seed weight images. Zero
   mismatches — not "a few near-threshold."
2. **N-MNIST.** Exact raster match on a documented subsample (≥1,000 samples),
   confirming the design is not overfitted to one dataset's statistics.
3. **Assertions.** Every assertion in §P1.4.8 passes across the full regression,
   with none disabled or waived.
4. **Lint.** Verible and `verilator --lint-only` clean, no warnings waived
   without a documented reason.
5. **Two simulators.** Verilator and Icarus agree on the full regression.
6. **Instrumentation.** Access counts (weight reads, popcounts, planes skipped,
   count-memory accesses, events ingested) logged per sample and within 1% of
   the architecture simulator's independent prediction.
7. **Synthesis smoke test.** Synthesizes with Yosys against SkyWater 130 nm with
   no inferred latches and no combinational loops. Full timing closure is a
   Phase 5 deliverable, not a Phase 1 gate.
8. **Measured results recorded.** `phase1_report.md` states: bit-plane skip rate,
   mean active addresses per timestep (should reproduce the measured 51.0%),
   mean MVM cycles per timestep, and total weight reads per sample (should
   reproduce ~26,112, 15.6× below event-serial).
9. **Reproducibility.** A single documented command reruns the full regression
   from a clean checkout and reproduces every number in the report.

---

## P1.6 Known risks for Phase 1

| Risk | Why it matters | Mitigation |
|---|---|---|
| Near-threshold mismatches between float and integer models | The most likely source of "almost bit-exact" | Phase 0 sweeps `F` until mismatches are exactly zero. If they cannot reach zero, stop and diagnose before writing RTL. |
| Sign handling at weight bit-plane `k = 7` | Silent, systematic, easy to miss | Dedicated directed tests at ±128, ±1, 0 |
| `count_mem` area | 512×12 register file ≈ 6,144 flops — a real cost | Measure in the Phase 1 synthesis smoke test; consider SRAM after Phase 5 numbers |
| Event loss during the MVM stall | Breaks the `Σc == N_e` invariant and corrupts everything downstream | Dedicated assertion; randomized inter-event timing at Level 4 |
| `W_V` sized by copying NeuroHDC's 22 b | Our scaling differs (raw input, per-channel scale, calibrated threshold) | Phase 0 measures the true range; never copy |
| Testbench reimplements the reference | Two definitions of correct behaviour | cocotb imports the Phase 0 model directly — never reimplement |
