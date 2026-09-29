# NeuroHDC Implementation Audit — Core Algorithm vs. Paper

**Purpose:** verify, before touching any training hyperparameter, that the
existing implementation (`phase1_firing_characterization/src/neurohdc.py`,
`train_and_capture.py`) implements the *NeuroHDC algorithm itself* — the
encoding, the SNN, the query — faithfully. Per the task instructions, the
algorithm/dataflow is **not** to be redesigned; only genuinely-unspecified
training-procedure parameters are candidates for change in Phase 2.

**Classification used below:**
- **[PAPER-SPECIFIED]** — a number, formula, or named procedure is directly stated in the paper.
- **[DERIVABLE]** — not numerically stated, but uniquely fixed by other information the paper gives (an equation, a cited standard technique, or the dataset's one universally-used canonical protocol).
- **[OUR CHOICE]** — the paper does not provide enough information to determine a unique value; this implementation picked a specific value or technique.

Evidence is from a full-text search of the paper PDF (`pypdf` extraction,
all 12 pages) plus the equations already reconstructed in `README.md` §2–5.

---

## Part A — Core algorithm/dataflow checklist (must match; not up for revision)

| # | Item | Paper | Implementation | Verdict |
|---|---|---|---|---|
| 1 | DVS-Gesture dataset/class selection | 11 classes; 11th "Other" excluded, "following previous studies [7]" (§IV-A) | `DVSGestureDataset`: `if label == 10: continue` | **[PAPER-SPECIFIED] — MATCHES** |
| 2 | Event representation | Quadruple `(t′,p,x,y)` (§III-B) | `[x,y,p,t]` per event, sorted by `t` | **[PAPER-SPECIFIED] — MATCHES** |
| 3 | Equal-event-count timestep partitioning | "we divide them uniformly, ensuring an equal number of events in each" (§III-B, eq. 8) — **not** wall-clock time | `bin_idx = (k*T)//n_events`, vectorized, off by ≤1 event/bin | **[PAPER-SPECIFIED] — MATCHES** |
| 4 | SumPool / spatial resizing | Address generation, eq. (19): `addr = p·256 + ⌊y/β⌋·16 + ⌊x/β⌋`; pooled frame never materialized in hardware (§V-B) | `events_to_frames()`: `addr = p*256 + floor(y*16/H)*16 + floor(x*16/W)`, computed per-event via `np.bincount`, no spatial frame ever built | **[PAPER-SPECIFIED] — MATCHES.** For DVS-Gesture, `H=W=128` gives an exact integer `β=8` (`128/16=8`), so this is also independently [DERIVABLE] with no rounding ambiguity |
| 5 | 512 input neurons | `2×16×16 = 512`, "maintaining consistency with Spiking-HDC" (§IV-A) | `n_input=512` | **[PAPER-SPECIFIED] — MATCHES** |
| 6 | IF neuron model | `V_p(t)=V(t−1)+X(t)` (eq. 2), chosen over LIF for hardware simplicity | `Vp = V + X`, no leak term | **[PAPER-SPECIFIED] — MATCHES** |
| 7 | `V_reset` | `0`, "usually set to 0 by default" (§II-A) | `V = Vp*(1-S)` (reduces to `Vp*(1-S)+0*S`) | **[PAPER-SPECIFIED] — MATCHES** |
| 8 | `n` (spiking neurons) | 20, default (§IV-B1, Table II) | `n=20` | **[PAPER-SPECIFIED] — MATCHES** |
| 9 | `T` (timesteps) | 100, default (§IV-A, Table I) | `T=100` | **[PAPER-SPECIFIED] — MATCHES** |
| 10 | `D_hv = n×T` | 2000 (§IV-A; eq. 7) | `D_hv = n*T = 2000`, asserted | **[PAPER-SPECIFIED] — MATCHES** |
| 11 | Direct concatenation encoding | `h_t=[S_1(t)...S_n(t)]`, `h^u=[h_1...h_T]`, `h=h^u×2−1` (eq. 7) — **nothing else** between spikes and the flattened hypervector | `raster.reshape(B, T*n)` then `2*h_u-1`; no pooling/binding/permutation anywhere | **[PAPER-SPECIFIED] — MATCHES** |
| 12 | Joint SNN + class-HV training | Mode 1: both trained together via one backward pass through the shared cross-entropy loss (§III-C, §IV-E) | Single `loss.backward()` over `scores = h_b @ sign(Wc)^T` updates `Ws`, `Wc`, `v_thresh` together in one optimizer step | **[PAPER-SPECIFIED] — MATCHES** |
| 13 | Class-HV binarization | `C = Sign(W_c)`, STE for the backward pass, "consistent with previous work [10]" (eq. 10, §III-C) | `sign_ste()`: forward `sign(w)`, backward identity | **[PAPER-SPECIFIED (technique)] / [DERIVABLE (exact STE formula)] — MATCHES** |
| 14 | Similarity / query | `Score_i = Σ_m h(m)·C_i(m)` (eq. 9), bipolar inner product; hardware form is per-timestep XNOR+popcount (eq. 21), algebraically identical | `scores = h_b @ C.t()` (bipolar dot product), scaled by a constant `1/√(D_hv)` for CE-loss stability only (monotonic, does not change `argmax`) | **[PAPER-SPECIFIED] — MATCHES** (temperature scale is [OUR CHOICE], but provably decision-invariant, see row 14b) |
| 14b | Score temperature (`1/√D_hv`) | Not mentioned (no loss-scale detail given anywhere) | Added, monotonic rescale only | **[OUR CHOICE]** — does not change `argmax(scores)`, so eq. (9)'s decision rule is preserved exactly; needed only because `D_hv=2000`-wide bipolar dot products otherwise saturate cross-entropy |
| 15 | 8-bit signed SNN weights / QAT | "we quantize the floating-point weight `W_s` to... 8-bit signed integer" via QAT, applied "concurrently during the training process" (p.6, ref [36]) | Straight-through per-tensor fake-quantizer, `scale=max(|Ws|)/127`, applied every forward pass | **[PAPER-SPECIFIED (that int8 QAT is used)] / [DERIVABLE (exact scale formula, standard instantiation of a cited technique)] — MATCHES in spirit; exact scale scheme is a reasonable, standard choice** |
| 16 | Temporal/spatial gradient flow | Explicit BPTT-style recursion, eq. (12)–(16): `∂L/∂Vp(t)` depends on `∂L/∂Vp(t+1)` (temporal term) plus `∂L/∂S(t)·∂S(t)/∂Vp(t)` (spatial term via surrogate gradient); final timestep has no temporal term (eq. 15); `∂L/∂Ws` accumulates over all `t` (eq. 16) | PyTorch `autograd` through the explicit Python `for t in range(T)` loop — this is exactly backpropagation-through-time, mathematically identical to eq. (12)–(16); the surrogate gradient (`ATanSpike.backward`) supplies `∂S(t)/∂Vp(t)` | **[PAPER-SPECIFIED] — MATCHES.** Autodiff through an explicit recurrence *is* eq. (12)–(16); no manual re-derivation needed, and none was skipped (verified by inspecting that `V` and `raster` are updated inside the loop with no `.detach()` breaking the graph) |

**Part A conclusion: the core NeuroHDC algorithm/dataflow is faithful to the
paper on every checked axis.** No architectural or algorithmic discrepancy
was found. The 58–60% DVS-Gesture accuracy is therefore not evidence of an
algorithm bug — it points at the *training procedure* (Part B), which the
paper leaves almost entirely unspecified for exactly the parameters governing
optimization and generalization.

---

## Part B — Training-procedure parameters (candidates for Phase 2 changes)

| # | Parameter | Paper | Previous implementation | Classification |
|---|---|---|---|---|
| 1 | `V_thresh` value/procedure | Named in eq. (1) and as a hardware "configuration register" (§V-A); **no value, and no statement of whether it is fixed or learned, given anywhere** (confirmed: full-text search for "Vthresh"/"threshold" — 5 hits, none with a value or calibration method) | Trainable scalar, fixed init | **[OUR CHOICE]** |
| 2 | Surrogate gradient function/width | "a surrogate gradient" used, citing a survey [35] with no single formula (§III-C) | ATan, α=2.0 | **[OUR CHOICE]** (technique-use is [PAPER-SPECIFIED], the specific function is not) |
| 3 | `W_s` initialization | Not mentioned (full-text search: no init keyword tied to `W_s`) | `N(0, 1/n_input)` | **[OUR CHOICE]** |
| 4 | `W_c` initialization | Not mentioned | `N(0, 0.01²)` | **[OUR CHOICE]** |
| 5 | Optimizer | Adam, explicitly (§IV-A) | Adam | **[PAPER-SPECIFIED] — MATCHES** |
| 6 | Learning rate | Not given (full-text search: "learning rate" appears once, for the unrelated transfer-learning rate `α` in eq. 18) | `1e-3` | **[OUR CHOICE]** |
| 7 | Batch size | Not mentioned (zero hits for "batch") | 32 (DVS-Gesture) | **[OUR CHOICE]** |
| 8 | Number of epochs | Not mentioned (zero hits for "epoch") | 200–250 | **[OUR CHOICE]** |
| 9 | LR schedule | Not mentioned | None (constant LR) | **[OUR CHOICE]** |
| 10 | Quantization scale granularity | Not detailed beyond "8-bit signed integer" + QAT | Per-tensor symmetric | **[OUR CHOICE]** (standard instantiation) |
| 11 | Regularization (weight decay) | Not mentioned (zero hits for "regulariz"/"weight decay") | `0` or `1e-4` (inconsistent between prior runs) | **[OUR CHOICE]** |
| 12 | Data augmentation | Not mentioned (zero hits for "dropout"/"augment") | Event-dropout `p=0.15` used in one prior run only | **[OUR CHOICE]** |
| 13 | Input scaling / normalization | **Eq. (16): `X(t) = W_s·D_flat(t)ᵀ`, applied directly to the raw (unnormalized) SumPooled count tensor** — no scaling/clipping/normalization operation appears anywhere in the equation or its derivation | `frames / N_e` ("per-sample normalization" — divides every timestep's frame by that sample's own mean events/timestep) applied in all prior DVS-Gesture runs | **[OUR CHOICE], and specifically one that departs from what eq. (16) shows.** This is the single highest-priority suspect for the accuracy gap (see Phase 2) |
| 14 | Model-selection procedure | Not discussed at all | **Previous implementation selected the best checkpoint by re-evaluating on the TEST set every 5 epochs** | **[OUR CHOICE] — and a methodological error independent of the paper**: this leaks test-set information into checkpoint selection and must be fixed by carving a validation split from the training data, per the task's explicit rule |
| 15 | Random seed | Not mentioned | `0`, single seed | **[OUR CHOICE]** |
| 16 | Train/test split | Not restated numerically for DVS-Gesture (unlike DVS-ASL's explicit 80/20); DVS-Gesture has one universally-used canonical split | `ibmGestureTrain` = users 1–23, `ibmGestureTest` = users 24–29 (confirmed by directory listing) | **[DERIVABLE]** — the dataset's one standard, cross-subject, publicly-distributed split; not a free choice |

---

## Priority ranking for Phase 2 (most to least likely to explain the gap)

1. **Row B-13, input normalization.** This is not merely an unfilled gap — it
   actively replaces eq. (16)'s raw `D_flat(t)` with a rescaled version whose
   every timestep sums to ≈1 regardless of how much real motion occurred in
   that bin (a mechanical consequence of dividing by `N_e`, since
   equal-event-count binning already forces every timestep to contain ≈`N_e`
   events by construction — see `README.md` §3.2). For a gesture-recognition
   task where classes plausibly differ in absolute motion intensity as well
   as spatial pattern, this discards a real class-discriminative signal.
   N-MNIST's classes (digit shape under a fixed saccade dynamic) are far less
   dependent on that signal, which is consistent with N-MNIST reaching 94.9%
   under the same normalization while DVS-Gesture reached only 55-60%.
2. **Row B-14, test-set model selection.** Independent of the paper
   entirely; a bug that must be fixed regardless of whether it explains the
   gap. (Fixing it, if anything, would be expected to *lower* the reported
   number relative to the 58–60% previously reported, since that number was
   itself optimistically test-set-selected — closing this gap is now a
   separate task from finding the true bottleneck.)
3. **Row B-11/B-12, regularization/augmentation.** Both training curves
   (v1: 96.25% train / 55.0% test; v2 with WD+dropout: ~95% train / 58.75–
   60.4% val-free test) show severe overfitting persisting even after adding
   these — suggesting they are not sufficient on their own and something more
   fundamental (row B-13) needs fixing first, though they may still help once
   combined with a fix to B-13.
4. **Rows B-1/B-2/B-3/B-4/B-6, threshold/surrogate/init/LR.** Lower priority:
   these are shared code paths with N-MNIST, which reached a reasonable
   accuracy match (94.9% vs. 97.28%) under the same choices — arguing against
   them being the dominant DVS-Gesture-specific driver, though `V_thresh`'s
   *initial value* is worth revisiting once raw (unnormalized) inputs are
   restored, since raw DVS-Gesture drive magnitude is ~100× larger than
   N-MNIST's (mean ~4,070 vs. ~42 events/timestep), and a fixed threshold
   init tuned implicitly for the normalized regime may be badly mismatched
   for raw DVS-Gesture inputs specifically.

Phase 2 addresses these in this priority order, changing one thing at a time
and recording the result of each change before moving to the next, per the
task's "make changes systematically" instruction.

---

## Addendum — what Phase 2 actually found (added after the experiment series)

The priority ranking above was directionally right but incomplete. In order
of actual experimental impact (full detail and every run's numbers in
`dvs_accuracy_report.md`):

1. **Row B-13 (input normalization) + calibrated threshold init** confirmed
   as the single largest fix: removing the unsupported `per_sample_norm` and
   using raw `D_flat(t)` per eq. (16), plus a label-free threshold
   calibration at init, took best validation accuracy from the previous
   58–60% (test-set-selected, so not even a clean comparison) to a cleanly
   validation-selected **68.6%** in the very first corrected run.
2. **Regularization tuning (weight decay, event dropout, label smoothing,
   head dropout) — row B-11/B-12 — had only small and inconsistent effects**
   (68.6% → 74–75% at best; label smoothing and head dropout actively hurt
   in isolation). This part of the original priority ranking was correct in
   direction but modest in magnitude, and is not what closed most of the
   remaining gap.
3. **The decisive fix was not identified in the original Part B list at
   all: gradient clipping.** This architecture is an explicit 100-step
   unrolled recurrence (BPTT through a hard-reset nonlinearity every
   timestep, eq. 12–16), trained with no gradient-norm clipping anywhere in
   any prior run. Adding standard `clip_grad_norm_` took validation accuracy
   from ~75% to **84.3%** (clip norm 1.0) and then **86.2%** (clip norm 0.5)
   — by far the largest single change in the whole series, and one this
   audit's Part A/B tables did not surface because gradient clipping is an
   optimizer-level detail, not a NeuroHDC algorithm/dataflow parameter, so
   it fell outside the original per-parameter audit scope entirely. It is
   recorded here for completeness: **[OUR CHOICE]**, a standard technique
   for training deep unrolled recurrences, not mentioned by the paper
   (confirmed: zero hits for "clip"/"gradient norm" in the full-text search),
   and not specific to NeuroHDC.
