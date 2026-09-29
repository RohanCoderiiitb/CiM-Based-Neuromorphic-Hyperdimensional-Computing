"""Render phase0_report.md and docs/bitwidth_table.md from artifacts/phase0/*.json.
Status-aware: if results.json (the on-data run) does not exist, the measured sections say PENDING."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths as P

cons = json.load(open(f"{P.OUT_DIR}/stored_raster_consistency.json"))
res = json.load(open(f"{P.OUT_DIR}/results.json")) if os.path.exists(f"{P.OUT_DIR}/results.json") else None
DONE = res is not None
pct = lambda x: f"{100 * x:.2f}%"


def bound_rows():
    L = ["| Dataset / seed | max c[addr] | X range | Vp range | W_COUNT | W_X | W_V |", "|---|---|---|---|---|---|---|"]
    for r in cons:
        b = r["worst_case_bounds"]
        L.append(f"| {r['name']} | {b['c_max']} | [{b['x_lo']}, {b['x_hi']}] | [{b['vp_lo']}, {b['vp_hi']}] | {b['w_count']} | {b['w_x']} | {b['w_v']} |")
    return "\n".join(L)


def cons_rows():
    L = ["| Checkpoint | class HV from ckpt == recorded | pred from recorded raster == recorded pred | accuracy (int scoring path) | recorded | min distance of v_thresh/s_j from an integer |", "|---|---|---|---|---|---|"]
    for r in cons:
        L.append(f"| {r['name']} | {r['class_hv_match_checkpoint']} | {r['int_pred_equals_recorded_pred']}/{r['n_samples']} | {pct(r['int_accuracy'])} | {pct(r['recorded_accuracy'])} | {r['thresh_min_dist_to_integer']:.4f} |")
    return "\n".join(L)


def measured_section():
    if not DONE:
        return ("> **STATUS: PENDING.** The raw DVS-Gesture / N-MNIST event files are not on the machine this phase was "
                "implemented on (the original runs were on a GPU box; `data/` is git-ignored). Nothing below was measured. "
                "Run `python model/fixedpoint/run_phase0.py --data-root <data>` then `python model/fixedpoint/make_report.py`; "
                "this section fills itself in.\n")
    L = ["### 4.1 Bit-exactness (integer raster vs float raster, 20x100 per sample)\n",
         "| Dataset / seed | int acc | recorded acc | samples bit-exact vs fresh float | differing spikes vs fresh float | vs stored (GPU) raster | max abs margin at first divergence |", "|---|---|---|---|---|---|---|"]
    for s, r in res["dvs"].items():
        a, b = r["int_vs_float_fresh"], r["int_vs_stored_ref"]
        L.append(f"| DVS seed {s} | {pct(r['int_acc'])} | {pct(r['recorded_acc'])} | {a['samples_bit_exact']}/{a['n_samples']} | {a['differing_spikes']} / {a['spikes_compared']} | {b['differing_spikes']} | {a['max_abs_first_margin']} |")
    for s, r in res["nmnist"].items():
        a, b = r["int_vs_float_fresh"], r["int_vs_stored_ref"]
        L.append(f"| N-MNIST seed {s} (n={r['n_samples']}) | {pct(r['int_acc_subsample'])} | {pct(r['stored_ref_acc_subsample'])} (stored, same subsample) | {a['samples_bit_exact']}/{a['n_samples']} | {a['differing_spikes']} / {a['spikes_compared']} | {b['differing_spikes']} | {a['max_abs_first_margin']} |")
    L.append("\nFirst-divergence details (each is one (sample, neuron) trajectory; `margin` = Vp_int - thresh_int, exact):\n")
    for s, r in res["dvs"].items():
        for f in r["int_vs_float_fresh"]["first_divergences"]:
            L.append(f"- DVS seed {s}: sample {f['sample']} t={f['t']} neuron {f['neuron']}: int spike={f['int_spike']}, float spike={f['ref_spike']}, margin={f['margin_int']}")
    L.append("\n### 4.2 Measured maxima (true values over the measured data)\n")
    L += ["| Scope | max c | X min | X max | Vp min | Vp max | V(stored) min | V(stored) max |", "|---|---|---|---|---|---|---|---|"]
    for s, r in res["dvs"].items():
        m = r["measured"]; L.append(f"| DVS test, seed {s} | {m['c_max']} | {m['x_min']} | {m['x_max']} | {m['vp_min']} | {m['vp_max']} | {m['v_min']} | {m['v_max']} |")
    for s, r in res["nmnist"].items():
        m = r["measured"]; L.append(f"| N-MNIST subsample, seed {s} | {m['c_max']} | {m['x_min']} | {m['x_max']} | {m['vp_min']} | {m['vp_max']} | {m['v_min']} | {m['v_max']} |")
    for s, m in res["measured"].get("dvs_train", {}).items():
        L.append(f"| DVS train (measure only), seed {s} | {m['c_max']} | {m['x_min']} | {m['x_max']} | {m['vp_min']} | {m['vp_max']} | {m['v_min']} | {m['v_max']} |")
    return "\n".join(L)


def gate_section():
    if not DONE:
        return "**Completion gate: NOT YET EVALUATED on real event data** (see section 4). What has been verified without event data is in section 3."
    ok_acc = all(res["gates"].values())
    exact = all(r["int_vs_float_fresh"]["samples_bit_exact"] == r["int_vs_float_fresh"]["n_samples"] for r in res["dvs"].values())
    return (f"**Extraction reproduces recorded accuracy for all seeds: {ok_acc}. DVS-Gesture 240/240 bit-exact for all seeds: {exact}.** "
            "If False, every differing spike is listed above with its exact integer margin.")


def widths_table():
    if not DONE:
        return "NOT FROZEN — pending measurement. Worst-case bounds (upper limits, not the frozen values) are in the previous section."
    W = res["frozen_widths"]
    return "\n".join(["| Signal | Frozen width | Format |", "|---|---|---|",
                      f"| address | 9 | unsigned |", f"| weight | 8 | signed, range [-127, 127] |",
                      f"| `W_COUNT` (c[addr]) | **{W['W_COUNT']}** | unsigned |", f"| `W_X` (X_j) | **{W['W_X']}** | signed |",
                      f"| `W_V` (V_j and adder Vp_j) | **{W['W_V']}** | signed |", f"| `W_THRESH` (thresh_int_j) | **{W['W_THRESH']}** | signed |"])


BOUND_NOTE = """Bounds assume the worst case allowed by the data format: every event of a timestep at one address (`c_max = ceil(n_events/T)` of the
largest recorded sample) hitting the most positive / most negative weight, and up to T consecutive non-firing steps for the negative V bound.
They are ceilings, not the frozen widths. Note the largest DVS-Gesture sample has 1.39 M events, so the worst-case chunk is 13,860, far above the
mean N_e = 4,071 used for the sizing estimate in IMPLEMENTATION_README 0.4 (which gave W_X = 20)."""

BITWIDTH = f"""# Bit-width table (Phase 0)

Sized from **measured maxima**, never from NeuroHDC's 22-bit V. Regenerate with `model/fixedpoint/make_report.py`.

## Frozen widths

{widths_table()}

## Worst-case ceilings (data-free, from the checkpoints' int8 weights and recorded event counts)

{bound_rows()}

{BOUND_NOTE}

## Conventions
- `V` datapath width covers the **adder output** `Vp = V + X` (before compare/reset); the stored register is always `< thresh` (or 0 after a spike) on the high side, but has no lower clamp.
- No saturation anywhere: widths must make overflow impossible for inputs like those measured. Measured on the *test* splits (and train split if `--dvs-train-root` was given) — see report for scope.
- `thresh_int` is an integer (ceil, exact); there are no fractional bits.
"""
open(f"{P.DOCS_DIR}/bitwidth_table.md", "w").write(BITWIDTH)

REPORT = f"""# Phase 0 report — exact integer reference model for NeuroHDC

Generated by `model/fixedpoint/make_report.py` from `artifacts/phase0/*.json`. Do not hand-edit numbers.

## 1. Result at a glance

{gate_section()}

Deliverables: `model/fixedpoint/` (integer model, extraction, run/compare/measure), `model/export/` (weight image, golden vectors, loader, `formats.md`),
`docs/bitwidth_table.md`, `tb/vectors/` (populated by the on-data run), `tests/test_int_model.py`, copies of the source/checkpoints/reference rasters (section 7).

## 2. Method

Float model (`model/neurohdc/neurohdc.py`, verbatim copy, unmodified): `X = frames @ (q*s_j)`, `V += X`, spike if `V - v_thresh >= 0`, hard reset.
Integer model (`model/fixedpoint/int_model.py`):

    q_ji      = clamp(round(Ws_ji / s_j), -127, 127)      s_j = max_i|Ws_ji| / 127        (same torch ops as the float model's quantizer)
    X_j(t)    = sum_a c[t,a] * q_ja                        integer
    Vp_j(t)   = V_j(t-1) + X_j(t);  spike iff Vp_j(t) >= thresh_int_j;  V_j(t) = 0 if spike else Vp_j(t)
    thresh_int_j = ceil(v_thresh / s_j)    computed with fractions.Fraction on the exact float32 values

No fractional bits, no rounding, no saturation. The ceil is exact because V is an integer. (IMPLEMENTATION_README Phase 0 task 1-2 described a
fixed-point threshold with `F` fractional bits and an `F` sweep; per the Phase 0 task statement this is unnecessary and is not used. `F` = 0.)
Class scoring: cumulative XNOR-popcount over timesteps (eq. 21), argmax with lowest-index tie-break; verified equal to the bipolar dot product form.
Counts `c` are taken from the original `events_to_frames` output through the original `DVSGestureDataset` / `NMNISTDataset` (`input_scaling="raw"`), unchanged.

**N-MNIST caveat (departs from the DVS case).** The N-MNIST checkpoint was trained with `per_sample_norm` (frames / N_e), so the float model sees `c/N_e`.
The exact integer equivalent is `Vp_int >= ceil(v_thresh * N_e / s_j)`, i.e. the threshold is **per sample** (N_e is already a Phase-1 configuration input).
Only **one** N-MNIST checkpoint (seed 0) exists; "all 3 seeds" applies to DVS-Gesture only. N-MNIST is compared on a class-balanced subsample.

## 3. Verified without event data (real artifacts)

Applying the integer scoring path to the **recorded spike rasters** of the verified float pipeline:

{cons_rows()}

- Seed 0 reproduces the recorded 84.58% (203/240) exactly through the integer scoring path, and all class hypervectors re-derived from the checkpoints equal the recorded ones.
  This validates checkpoint <-> raster pairing and the scoring half of the integer model. It does **not** validate the SNN half on real events (section 4).
- Every `v_thresh / s_j` is at least 0.016 away from an integer, so no DVS-Gesture threshold is ambiguous at the ceil (the Fraction guard is still used).
- `tests/test_int_model.py` (all pass): exact-ceil, extraction bit-exact with the float quantizer (all 4 checkpoints, |q| <= 127, each row reaches 127),
  reset/equality semantics, sign-plane (k=7) directed test incl. weight -128, bit-plane dataflow == X, batching identity == event-serial sum,
  score forms agree, vector export -> reload -> re-verify round trip, and integer-vs-float rasters on **synthetic** event streams through the real weights
  (3 DVS seeds x 30 samples: 0 / 180,000 differing spikes; N-MNIST normalised path, 40 samples: 0 / 80,000). Synthetic firing rates (0.45-0.49 DVS, 0.17 N-MNIST)
  are near the real ones, but synthetic data is **not** the gate.

## 4. Measured on real data

{measured_section()}

## 5. Frozen bit widths

{widths_table()}

Worst-case ceilings for comparison:

{bound_rows()}

{BOUND_NOTE}

## 6. Golden vectors and weight image

Format: `model/export/formats.md` (version 1.0). Weight image: 512 addresses x 160 b (bit `j*8+k`, plane 7 = sign), plus 5 x (512 x 32 b) macro images;
`thresh_seed<k>.mem`. Vectors: per-timestep `c[]` (seed independent), `X`, `Vp`, `V`, spikes, prefix XNOR scores, predictions.
Loader/verifier: `model/export/load_vectors.py` (`verify()` re-runs the integer model from counts + weight image and compares every stored value).
{"Populated in `tb/vectors/` by the on-data run." if DONE else "`tb/vectors/` is EMPTY until the on-data run (needs event files)."}
Not exported: raw AER event streams (would require re-deriving the binning outside `events_to_frames`); Phase 1 addr_gen tests need those — flagged as a follow-up.

## 7. Provenance / copies

Nothing was moved. Copies: `model/neurohdc/{{neurohdc,capture_dvs_frozen,train_and_capture}}.py` (byte-identical to `phase2_firing_characterization/src`),
`artifacts/checkpoints/` (frozen_seed{{0,1,2}}.pt/.json, nmnist_seed0.pt/.json), `artifacts/reference_rasters/` (recorded rasters), `reference_docs/`.
{f"Run: git {res['git_sha'][:10]}, torch {res['torch']}, numpy {res['numpy']}, python {res['python']}, {res['date']}." if DONE else ""}
"""
open(f"{P.ROOT}/phase0_report.md", "w").write(REPORT)
print("wrote phase0_report.md, docs/bitwidth_table.md; DONE =", DONE)
