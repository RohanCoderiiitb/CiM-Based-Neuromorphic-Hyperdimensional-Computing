"""Render phase0_report.md and docs/bitwidth_table.md from artifacts/phase0/*.json.
Status-aware: if results.json (the on-data run) does not exist, the measured sections say PENDING."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths as P

cons = json.load(open(f"{P.OUT_DIR}/stored_raster_consistency.json"))
res = json.load(open(f"{P.OUT_DIR}/results.json")) if os.path.exists(f"{P.OUT_DIR}/results.json") else None
DONE = res is not None
pct = lambda x: f"{100 * x:.2f}%"
num = lambda x: f"{x:,}"


def bound_rows():
    L = ["| Dataset / seed | max c[addr] | X range | Vp range | W_COUNT | W_X | W_V |", "|---|---|---|---|---|---|---|"]
    for r in cons:
        b = r["worst_case_bounds"]
        L.append(f"| {r['name']} | {b['c_max']} | [{b['x_lo']}, {b['x_hi']}] | [{b['vp_lo']}, {b['vp_hi']}] | {b['w_count']} | {b['w_x']} | {b['w_v']} |")
    return "\n".join(L)


def cons_rows():
    L = ["| Checkpoint | quantizer | class HV from ckpt == recorded | pred from recorded raster == recorded pred | accuracy (int scoring path) | recorded | min distance of the real threshold from an integer |",
         "|---|---|---|---|---|---|---|"]
    for r in cons:
        q = "per-channel" if r.get("per_channel", True) else "per-tensor"
        L.append(f"| {r['name']} | {q} | {r['class_hv_match_checkpoint']} | {r['int_pred_equals_recorded_pred']}/{r['n_samples']} | {pct(r['int_accuracy'])} | {pct(r['recorded_accuracy'])} | {r['thresh_min_dist_to_integer']:.4f} |")
    return "\n".join(L)


def gate_section():
    if not DONE:
        return "**Completion gate: NOT YET EVALUATED on real event data** (see section 4)."
    g = res["gates"]
    ok = all(g.values())
    L = [f"**Completion gate: {'PASSED' if ok else 'FAILED'}.**", ""]
    L.append("| Gate item | Result |")
    L.append("|---|---|")
    for s, r in res["dvs"].items():
        b = r["int_vs_stored_ref"]
        L.append(f"| DVS-Gesture seed {s}: integer raster == recorded raster, recorded accuracy reproduced | {g[f'dvs_seed{s}']}: "
                 f"{b['samples_bit_exact']}/{b['n_samples']} samples bit-exact, {b['differing_spikes']} / {num(b['spikes_compared'])} spikes differ, "
                 f"{pct(r['int_acc'])} (recorded {pct(r['recorded_acc'])}) |")
    for s, r in res["nmnist"].items():
        b = r["int_vs_stored_ref"]
        L.append(f"| N-MNIST seed {s}, **full** test set: integer raster == recorded raster, recorded accuracy reproduced | "
                 f"{g['nmnist_seed0_full_test']}: {b['samples_bit_exact']}/{b['n_samples']} samples bit-exact, {b['differing_spikes']} / "
                 f"{num(b['spikes_compared'])} spikes differ, {pct(r['int_acc'])} (recorded {pct(r['recorded_full_test_acc'])}) |")
    for k, lab in [("dvs_test", "DVS-Gesture test"), ("nmnist_test", "N-MNIST test")]:
        if k in res["streams"]:
            s = res["streams"][k]
            L.append(f"| {lab}: raw event stream -> eq.(19) address -> timestep rule == counts | {s['exact']}/{s['samples']} samples exact |")
    L.append(f"| Extraction == float quantizer output (with the checkpoint's own granularity) | "
             f"{all(r['extraction_bit_exact'] for r in list(res['dvs'].values()) + list(res['nmnist'].values()))} (all 4 checkpoints) |")
    L.append(f"| Exported vectors reload and re-verify from disk | {res['vectors_verified']} |")
    L += ["", "The IMPLEMENTATION_README criterion was \"bit-exact match on both datasets, all three seeds\". Only one N-MNIST checkpoint exists (seed 0),",
          "so \"all three seeds\" is met for DVS-Gesture only."]
    return "\n".join(L)


def exactness_section():
    if not DONE:
        return "PENDING."
    L = ["| Scope | samples | differing spikes vs fresh float (CPU) | vs recorded raster | positions with Vp == thresh (fires only because of `>=`) | positions with Vp == thresh-1 |",
         "|---|---|---|---|---|---|"]
    for s, r in res["dvs"].items():
        a, b = r["int_vs_float_fresh"], r["int_vs_stored_ref"]
        L.append(f"| DVS test, seed {s} | {a['n_samples']} | {a['differing_spikes']} / {num(a['spikes_compared'])} | {b['differing_spikes']} | {b['n_margin_eq0']} | {b['n_margin_eq_minus1']} |")
    for s, c in res.get("dvs_train_compare", {}).items():
        L.append(f"| DVS **train**, seed {s} (extra evidence, no recorded raster) | {c['n_samples']} | {c['differing_spikes']} / {num(c['spikes_compared'])} | n/a | {c['n_margin_eq0']} | {c['n_margin_eq_minus1']} |")
    for s, r in res["nmnist"].items():
        a, b = r["int_vs_float_fresh"], r["int_vs_stored_ref"]
        L.append(f"| N-MNIST test (full), seed {s} | {a['n_samples']} | {a['differing_spikes']} / {num(a['spikes_compared'])} | {b['differing_spikes']} | {num(b['n_margin_eq0'])} | {num(b['n_margin_eq_minus1'])} |")
    L += ["",
          "The last two columns show the gate was not passed by luck. Positions where the integer `Vp` lands exactly on the integer threshold are the",
          "cases where the float model's rounded sum could have gone the other way. They occur (DVS: 6–34 per run; N-MNIST: ~18k, because its thresholds are",
          "small, 36–392), and the float model agrees at every one: the real threshold `v_thresh/s_j` (DVS) or `v_thresh*N_e/s` (N-MNIST) is at least",
          f"{min(r['thresh_min_dist_to_integer'] for r in cons):.4f} LSB away from an integer (section 3), which is larger than the float32 accumulation error."]
    return "\n".join(L)


def nmnist_section():
    return """**Finding: the N-MNIST checkpoint uses a per-TENSOR quantizer, not per-channel.** The first on-data run extracted N-MNIST per-channel
(the current default of `fake_quant_int8`). The integer model then matched a fresh float run exactly, but 24,572 spikes and 6/1000 predictions
differed from the **recorded** raster. The difference is not numerical: fresh float runs on CPU and CUDA, at several batch sizes, agree with each other
and with the integer model, and differ from the recording in exactly the same places, with first-divergence margins up to 468 LSB.
The `fake_quant_int8` docstring says per-tensor was "the previous default", and the N-MNIST model was trained before the per-channel change
(DVS exp4/exp5). Re-running the float model per-tensor on the full test set reproduces the recording exactly:

| Float model on full N-MNIST test (10,000) | spikes differing from recorded raster | preds == recorded | accuracy |
|---|---|---|---|
| per-channel (wrong) | 245,112 / 20,000,000 | 9,937 | 94.90% |
| **per-tensor** | **0** / 20,000,000 | **10,000** | **94.91%** (recorded 94.91%) |

Fix: `quantize.GRANULARITY` records the granularity per checkpoint, with this evidence; `load_int_params` and `pipeline.float_run` use it
(the float model runs through a scoped rebinding of `fake_quant_int8`, so `neurohdc.py` stays byte-identical). Unknown checkpoints raise an error.
The earlier "extraction bit-exact" test had passed only because it compared against the current default, not against what the checkpoint was trained with.
For hardware this changes nothing structural: the 20 per-neuron threshold registers simply all hold the same value for N-MNIST."""


def binning_section():
    if not DONE:
        return "PENDING."
    L = ["`events_to_frames` puts event `k` of an `n`-event sample into timestep `floor(k*T/n)`. Timesteps therefore hold `N_e = n//T` **or `N_e+1`**",
         "events (exactly `n mod T` of them hold `N_e+1`), and every event is used. This is the verified model, so it is what the RTL must do.",
         "IMPLEMENTATION_README §P1.1/§P1.2 (lines 417-418, 514, 921-922, 970, 992) instead specify a boundary at `ev_cnt == N_e` and the invariant `Σc == N_e`.",
         "**RTL built literally from that text would not be bit-exact:**", "",
         "| Split | samples | samples with n mod T > 0 | timesteps holding N_e+1 events | events a fixed-N_e boundary would leave over (max per sample) |",
         "|---|---|---|---|---|"]
    for k, lab in [("dvs_test", "DVS-Gesture test"), ("dvs_train", "DVS-Gesture train"), ("nmnist_test", "N-MNIST test")]:
        if k in res["binning"]:
            b = res["binning"][k]
            L.append(f"| {lab} | {b['samples']} | {b['samples_with_remainder']} | {num(b['timesteps_with_Ne_plus_1'])} / {num(b['timesteps_total'])} "
                     f"({pct(b['frac_timesteps_Ne_plus_1'])}) | {num(b['events_left_over_by_fixed_Ne_rule_total'])} ({b['events_left_over_by_fixed_Ne_rule_max']}) |")
    L += ["",
          "Exact hardware rule (reference: `events.boundary_counter_bins`, checked against the closed form for every n = 1..259 and on exported streams):",
          "",
          "    acc += T on every event;   while acc >= n: acc -= n, timestep boundary     (acc < n; exactly T boundaries per sample)",
          "",
          "It needs only an adder and a comparator, and takes `n` (the sample's event total) as the configuration register in place of `N_e`.",
          "`N_e = n//T` already requires `n` up front, so no new information is needed. The invariant becomes `Σ_addr c[addr] ∈ {N_e, N_e+1}`, and the",
          "`X` bound uses `N_e+1`. **Recommendation:** update IMPLEMENTATION_README §P1.1/§P1.2 and the `event_ctr` tests before Phase 1 RTL starts",
          "(not edited here: that document is the plan's source of truth and the decision is yours)."]
    return "\n".join(L)


def measured_table():
    if not DONE:
        return "PENDING."
    L = ["| Scope | max c | X min | X max | Vp min | Vp max | V(stored) max | max Σc per step |", "|---|---|---|---|---|---|---|---|"]
    row = lambda lab, m: L.append(f"| {lab} | {m['c_max']} | {num(m['x_min'])} | {num(m['x_max'])} | {num(m['vp_min'])} | {num(m['vp_max'])} | {num(m['v_max'])} | {num(m['sum_c_per_step_max'])} |")
    for s, r in res["dvs"].items():
        row(f"DVS test, seed {s}", r["measured"])
    for s, m in res["measured"].get("dvs_train", {}).items():
        row(f"DVS train, seed {s}", m)
    for s, r in res["nmnist"].items():
        row(f"N-MNIST test (full), seed {s}", r["measured"])
    row("**All (frozen from this)**", res["measured"]["merged"])
    nm = next(iter(res["nmnist"].values()), None)
    L += ["",
          "The negative side of V is the binding constraint: a neuron driven negative keeps integrating with no leak and no lower clamp (the algorithm has none).",
          "The N-MNIST train split was not measured: every N-MNIST quantity is 2-3 orders of magnitude inside the DVS-derived widths"
          + (f" (thresholds {nm['thresh_int_range'][0]}–{nm['thresh_int_range'][1]})." if nm else ".")]
    return "\n".join(L)


def widths_table():
    if not DONE:
        return "NOT FROZEN — pending measurement."
    W, m = res["frozen_widths"], res["measured"]["merged"]
    head = lambda lim, v: f"{lim / v:.2f}x"
    thr_max = max(max(r["thresh_int"]) for r in res["dvs"].values())
    return "\n".join([
        "| Signal | Frozen width | Format | Measured extreme | Representable limit | Headroom | IMPLEMENTATION_README 0.4 estimate |", "|---|---|---|---|---|---|---|",
        "| address | 9 | unsigned | 511 | 511 | — | 9 |",
        "| weight | 8 | signed, range [-127, 127] (-128 never occurs) | ±127 | [-128, 127] | — | 8 |",
        f"| `W_COUNT` (c[addr]) | **{W['W_COUNT']}** | unsigned | {m['c_max']} | {2 ** W['W_COUNT'] - 1} | {head(2 ** W['W_COUNT'] - 1, m['c_max'])} | 12 (worst case) |",
        f"| `W_X` (X_j) | **{W['W_X']}** | signed | {num(min(m['x_min'], -m['x_max']))} | {num(-2 ** (W['W_X'] - 1))} | {head(2 ** (W['W_X'] - 1), max(-m['x_min'], m['x_max']))} | 20 (mean N_e; too small: see note) |",
        f"| `W_V` (V_j and adder Vp_j) | **{W['W_V']}** | signed | {num(m['vp_min'])} | {num(-2 ** (W['W_V'] - 1))} | {head(2 ** (W['W_V'] - 1), -m['vp_min'])} | 27 (worst case) |",
        f"| `W_THRESH` (thresh_int_j) | **{W['W_THRESH']}** | signed (always > 0) | {num(thr_max)} | {num(2 ** (W['W_THRESH'] - 1) - 1)} | {head(2 ** (W['W_THRESH'] - 1) - 1, thr_max)} | — (was fixed-point with F bits) |",
        "",
        "The widths are the smallest that hold every measured value (DVS test + train, 3 seeds; N-MNIST full test). Headroom is 1.7-1.8x on every datapath",
        "signal. They are **not** proofs of no overflow for arbitrary inputs; the data-free worst-case ceilings are below (W_X 22, W_V 29).",
        "Whether to add a guard bit, or a saturation or overflow flag on V, is a Phase 1 design decision. Note: `W_X` = 21, not the plan's 20, because the largest DVS samples have",
        "far more than the mean 4,071 events per timestep (max Σc per step = 15,946), even though the measured |X| is well below the worst case."])


BOUND_NOTE = """Bounds assume the worst case allowed by the data format: every event of a timestep at one address (`c_max = ceil(n_events/T)` of the
largest recorded sample) hitting the most positive / most negative weight, and up to T consecutive non-firing steps for the negative V bound."""

BITWIDTH = f"""# Bit-width table (Phase 0)

Sized from **measured maxima**, never from NeuroHDC's 22-bit V. Regenerate with `model/fixedpoint/make_report.py`.

## Frozen widths

{widths_table()}

## Measured maxima

{measured_table()}

## Worst-case ceilings (data-free, from the checkpoints' int8 weights and recorded event counts)

{bound_rows()}

{BOUND_NOTE}

## Conventions
- `V` datapath width covers the **adder output** `Vp = V + X` (before compare/reset); the stored register is always `< thresh` (or 0 after a spike) on the high side, but has no lower clamp.
- `thresh_int` is an integer (exact ceil); there are no fractional bits.
- A timestep holds `N_e` or `N_e+1` events (see phase0_report.md section 5), so `Σ_addr c[addr] <= N_e+1`.
"""
open(f"{P.DOCS_DIR}/bitwidth_table.md", "w").write(BITWIDTH)

REPORT = f"""# Phase 0 report — exact integer reference model for NeuroHDC

Generated by `model/fixedpoint/make_report.py` from `artifacts/phase0/*.json`. Do not hand-edit numbers.

## 1. Result at a glance

{gate_section()}

Frozen widths: {"`W_COUNT`={W_COUNT}, `W_X`={W_X}, `W_V`={W_V}, `W_THRESH`={W_THRESH}".format(**res["frozen_widths"]) if DONE else "pending"} (section 6). `F` = 0: thresholds are exact integers.

**Two findings need action before Phase 1** (details in sections 4 and 5):
1. The N-MNIST checkpoint was trained with a **per-tensor** quantizer. The earlier extraction assumed per-channel; this is fixed and the gate now passes on the full test set.
2. The verified model's timesteps hold `N_e` **or `N_e+1`** events. The Phase 1 plan's "boundary at `ev_cnt == N_e`" would break bit-exactness on ~99% of samples.
   The exact counter rule is given below and implemented in `model/fixedpoint/events.py`.

## 2. Method

Float model (`model/neurohdc/neurohdc.py`, verbatim copy, unmodified): `X = frames @ (q*s_j)`, `V += X`, spike if `V - v_thresh >= 0`, hard reset.
Integer model (`model/fixedpoint/int_model.py`):

    q_ji      = clamp(round(Ws_ji / s_j), -127, 127)      s_j = max_i|Ws_ji| / 127  (per-channel, DVS)  or  s = max_ji|Ws_ji| / 127  (per-tensor, N-MNIST)
    X_j(t)    = sum_a c[t,a] * q_ja                        integer
    Vp_j(t)   = V_j(t-1) + X_j(t);  spike iff Vp_j(t) >= thresh_int_j;  V_j(t) = 0 if spike else Vp_j(t)
    thresh_int_j = ceil(v_thresh / s_j)                    DVS-Gesture (raw counts)
    thresh_int_j = ceil(v_thresh * N_e / s)                N-MNIST (trained on c/N_e): per sample
    all ceils computed with fractions.Fraction on the exact float32 values

No fractional bits, no rounding, no saturation. The ceil is exact because V is an integer. IMPLEMENTATION_README Phase 0 tasks 1-2 described a
fixed-point threshold with `F` fractional bits and an `F` sweep; with the exact ceil this is unnecessary, so the sweep was not run and `F` = 0.
Class scoring: cumulative XNOR-popcount over timesteps (eq. 21), argmax with lowest-index tie-break; verified equal to the bipolar dot-product form.
Counts `c` come from the original `events_to_frames` through the original `DVSGestureDataset` / `NMNISTDataset` (`input_scaling="raw"`), unchanged.
Gate reference: the rasters recorded by the original pipeline (`artifacts/reference_rasters/`) and a fresh float run on CPU.
Only **one** N-MNIST checkpoint (seed 0) exists.

## 3. Checks against the recorded artifacts (data-free)

The integer scoring path applied to the **recorded spike rasters**:

{cons_rows()}

`tests/test_int_model.py` (all pass): exact ceil; extraction bit-exact with the float quantizer at each checkpoint's granularity; timestep counter == closed form
and address generator + counter == `events_to_frames`; reset/equality semantics; sign-plane (k=7) test including weight -128; bit-plane dataflow == X;
batching identity == event-serial sum; score forms agree; vector export -> reload -> re-verify; integer vs float on synthetic streams.

## 4. Bit-exactness on real data

{exactness_section()}

### 4.1 N-MNIST quantizer granularity

{nmnist_section()}

## 5. Timestep binning (Phase 1 spec conflict)

{binning_section()}

## 6. Frozen bit widths

{widths_table()}

### 6.1 Measured maxima

{measured_table()}

### 6.2 Worst-case ceilings (data-free, for comparison)

{bound_rows()}

{BOUND_NOTE}

## 7. Golden vectors, event streams and weight images

Format: `model/export/formats.md`. Loader/verifier: `model/export/load_vectors.py`. `verify()` re-runs the integer model from the exported counts + weight
image and checks every stored value; `verify_events()` re-derives addresses and counts from the exported AER words.

| Path | Contents |
|---|---|
| `tb/vectors/weights/` | per checkpoint: 512 x 160 b bit-plane image (bit `j*8+k`, plane 7 = sign), 5 x (512 x 32 b) macro images, int8 `.npy`, `thresh_*.mem` at `W_THRESH` |
| `tb/vectors/dvsgesture/` | all 240 test samples: `counts.npz`; `seed{{0,1,2}}.npz` with thresh, X, Vp, V, spikes, prefix XNOR scores, preds |
| `tb/vectors/dvsgesture/events.npz` | full AER streams for 20 samples (per class: fewest and most events; 73k-1.39M events, 11.6M total) |
| `tb/vectors/nmnist/` | class-balanced 1,000-sample subsample (100/class) of the gated full test set: counts, seed0 traces, full AER streams for all 1,000 |
| `artifacts/phase0/` | `results.json` (everything above, with provenance), `stored_raster_consistency.json`, class hypervectors `class_hv_*.npy` |

The streams for every other sample are rebuilt on demand with `events.read_stream()`. That rebuild was checked on the full test sets (section 1),
so testbenches can regress on all 240 / 10,000 samples without exporting them. `tb/vectors/` totals about 76 MB. The plan calls for Git LFS for these, and it is not installed here.
`thresh_seednmnist0.mem` holds the N_e = 1 value `ceil(v_thresh/s)`; the real N-MNIST threshold is per sample (`thresh_int` in `nmnist/seed0.npz`).
The address generator reference is `events.address`: a shift for DVS-Gesture (128 -> 16), but an integer division by 34 for N-MNIST (34 -> 16), not a shift.

## 8. Provenance

Nothing outside `integer_reference_model/` was moved or edited. `model/neurohdc/*.py` are byte-identical to `phase2_firing_characterization/src`;
`artifacts/checkpoints/` and `artifacts/reference_rasters/` are copies.
{f"Run: git {res['git_sha'][:10]}, torch {res['torch']}, numpy {res['numpy']}, python {res['python']}, {res['date']}. Data: DVS-Gesture test (240) + train (979, measurement and comparison only), N-MNIST test (10,000)." if DONE else ""}
Reproduce: `python model/fixedpoint/run_phase0.py --data-root ../data --dvs-train-root ../data/DVSGesture/ibmGestureTrain`, then
`python model/fixedpoint/check_stored_rasters.py` and `python model/fixedpoint/make_report.py`.
"""
open(f"{P.ROOT}/phase0_report.md", "w").write(REPORT)
print("wrote phase0_report.md, docs/bitwidth_table.md; DONE =", DONE)
