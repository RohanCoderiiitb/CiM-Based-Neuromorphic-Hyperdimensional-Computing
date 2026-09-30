"""
Experiment 2: similarity-margin early exit, replayed on the ALREADY-CAPTURED
frozen-model rasters (no retraining, no model re-run).

Correctness check first (required by the task): verify the bipolar
prefix-score form and the unipolar "2*(h.C) - ||C||_1" equivalent form agree
on argmax at EVERY prefix length t, for 100% of samples, before trusting
either for the exit-threshold sweep.

Score forms (both give the same argmax by construction -- see the derivation
in README.md section 9.2/G3, "Score_i = n.T - sum_t k_t - ||C_i||_1 + 2(h.C_i)",
which differs from "2*(h_u.C_u_i) - ||C_u_i||_1" only by an additive term
that does not depend on class i, hence does not change argmax):

  bipolar:  partial_i(t)  = sum_{t'<=t} sum_j h_b(t',j) * C_b_i(t',j)     h_b,C_b in {-1,+1}
  unipolar: partial'_i(t) = 2 * sum_{t'<=t} sum_j S(t',j)*C_u_i(t',j) - ||C_u_i(<=t)||_1
"""
import sys
import os
import json
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P1_ART = os.path.join(os.path.dirname(ROOT), "phase1_firing_characterization", "artifacts")
ART = os.path.join(ROOT, "artifacts")

# DVS-Gesture confusion pairs flagged in the paper's Fig. 4 (README.md section 5.2 /
# NeuroHDC paper): Air Guitar (label 9 in the paper's 0-indexed 11-class scheme,
# label 9 here since "Other"=10 is excluded and labels 0-9 preserved) <-> Hand
# Clapping (label 0); Right-Arm-CCW <-> Left-Hand-Wave. The exact label indices
# for our 0-9 (no "Other") scheme, per the standard DVS128Gesture class order:
# 0 Hand Clapping, 1 Right Hand Wave, 2 Left Hand Wave, 3 Right Arm CW,
# 4 Right Arm CCW, 5 Left Arm CW, 6 Left Arm CCW, 7 Arm Roll, 8 Air Drums, 9 Air Guitar.
CONFUSION_PAIRS = [(9, 0, "Air Guitar <-> Hand Clapping"), (4, 2, "Right-Arm-CCW <-> Left-Hand-Wave")]


def compute_prefix_scores(raster, class_hv):
    """
    raster:   [M, T, n] uint8, 0/1
    class_hv: [N, T, n] uint8, 0/1 (unipolar; matches what capture_dvs_frozen.py stores)
    Returns bipolar_prefix [M,T,N], unipolar_prefix [M,T,N] (both cumulative over t).
    """
    M, T, n = raster.shape
    N = class_hv.shape[0]
    S = raster.astype(np.float32)             # [M,T,n]
    Cu = class_hv.astype(np.float32)           # [N,T,n]
    Hb = 2 * S - 1                             # [M,T,n]
    Cb = 2 * Cu - 1                            # [N,T,n]

    # per-timestep per-class contribution, then cumulative sum over t
    # bipolar: sum_j Hb[m,t,j]*Cb[i,t,j]
    bip_t = np.einsum("mtj,itj->mti", Hb, Cb)       # [M,T,N]
    bip_prefix = np.cumsum(bip_t, axis=1)           # [M,T,N]

    # unipolar equivalent: 2*sum_j S[m,t,j]*Cu[i,t,j], minus cumulative ||C_i(<=t)||_1
    uni_t = 2 * np.einsum("mtj,itj->mti", S, Cu)    # [M,T,N]
    Cu_l1_t = Cu.sum(axis=2)                        # [N,T]  ||C_i(t)||_1 per timestep
    Cu_l1_prefix = np.cumsum(Cu_l1_t, axis=1)        # [N,T]
    uni_prefix = np.cumsum(uni_t, axis=1) - Cu_l1_prefix.T[None, :, :]  # [M,T,N] - [1,T,N]

    return bip_prefix, uni_prefix


def verify_identity(bip_prefix, uni_prefix):
    """Argmax agreement between the two score forms at every (sample, t)."""
    am_bip = bip_prefix.argmax(axis=2)  # [M,T]
    am_uni = uni_prefix.argmax(axis=2)  # [M,T]
    agree = (am_bip == am_uni)
    return float(agree.mean()), int((~agree).sum()), agree.size


def margin_curve(prefix_scores):
    """prefix_scores: [M,T,N]. Returns margin[M,T] = top1-top2 at each t."""
    sorted_scores = np.sort(prefix_scores, axis=2)  # ascending
    top1 = sorted_scores[:, :, -1]
    top2 = sorted_scores[:, :, -2]
    return top1 - top2


def exit_sweep(prefix_scores, labels, thetas, T):
    margins = margin_curve(prefix_scores)  # [M,T]
    preds_over_t = prefix_scores.argmax(axis=2)  # [M,T]
    M = prefix_scores.shape[0]
    full_acc = float((preds_over_t[:, -1] == labels).mean())

    rows = []
    for theta in thetas:
        exit_t = np.full(M, T - 1, dtype=int)  # 0-indexed; default = last timestep (ran to T)
        reached = np.zeros(M, dtype=bool)
        hit = margins >= theta  # [M,T]
        for m in range(M):
            idx = np.argmax(hit[m]) if hit[m].any() else (T - 1)
            if hit[m].any():
                exit_t[m] = idx
                reached[m] = True
        pred_at_exit = preds_over_t[np.arange(M), exit_t]
        acc_at_exit = float((pred_at_exit == labels).mean())
        events_saved_frac = float(((T - (exit_t + 1)) / T).mean())
        rows.append(dict(
            theta=float(theta),
            mean_exit_timestep=float((exit_t + 1).mean()),
            p90_exit_timestep=float(np.percentile(exit_t + 1, 90)),
            frac_reached_threshold=float(reached.mean()),
            n_ran_to_T=int((~reached).sum()),
            accuracy_at_exit=acc_at_exit,
            accuracy_at_full_T=full_acc,
            accuracy_delta=acc_at_exit - full_acc,
            mean_events_not_ingested_fraction=events_saved_frac,
        ))
    return rows, margins, preds_over_t, full_acc


def per_class_exit_stats(exit_t_at_best_theta, labels, class_names=None):
    N = int(labels.max()) + 1
    out = []
    for c in range(N):
        mask = labels == c
        if mask.sum() == 0:
            continue
        out.append(dict(class_idx=int(c),
                         n=int(mask.sum()),
                         mean_exit_timestep=float((exit_t_at_best_theta[mask] + 1).mean())))
    return out


def run_for_capture(name, npz_path, thetas, T=100):
    npz = np.load(npz_path)
    raster = npz["raster"]           # [M,T,n]
    labels = npz["labels"].astype(int)
    pred_recorded = npz["pred"].astype(int)
    class_hv = npz["class_hv"]       # [N,T,n]

    bip_prefix, uni_prefix = compute_prefix_scores(raster, class_hv)
    agree_frac, n_disagree, n_total = verify_identity(bip_prefix, uni_prefix)
    print(f"[{name}] identity check: {agree_frac*100:.4f}% argmax agreement "
          f"({n_disagree} disagreements / {n_total})")

    # sanity: full-T bipolar argmax must equal the recorded model predictions
    full_pred_bip = bip_prefix[:, -1, :].argmax(axis=1)
    match_recorded = float((full_pred_bip == pred_recorded).mean())
    print(f"[{name}] full-T bipolar argmax vs. recorded model pred: {match_recorded*100:.4f}% match")

    rows, margins, preds_over_t, full_acc = exit_sweep(bip_prefix, labels, thetas, T)

    # pick the theta whose accuracy_delta is closest to 0 (best accuracy/latency tradeoff
    # among tested thetas) for the per-class breakdown, purely descriptive
    best = min(rows, key=lambda r: abs(r["accuracy_delta"]))
    theta_star = best["theta"]
    margins_ge = margins >= theta_star
    M = raster.shape[0]
    exit_t = np.full(M, T - 1, dtype=int)
    for m in range(M):
        if margins_ge[m].any():
            exit_t[m] = np.argmax(margins_ge[m])
    per_class = per_class_exit_stats(exit_t, labels)

    return dict(
        dataset=name, n_samples=M, T=T,
        identity_check=dict(argmax_agreement_frac=agree_frac, n_disagreements=n_disagree,
                             n_total_comparisons=n_total,
                             full_T_matches_recorded_model_pred=match_recorded),
        full_T_accuracy=full_acc,
        theta_sweep=rows,
        theta_star_for_per_class_breakdown=theta_star,
        per_class_exit_at_theta_star=per_class,
    ), margins, preds_over_t, labels


def main():
    thetas = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1000]
    results = {}

    for seed in [0, 1, 2]:
        path = f"{P1_ART}/rasters/dvsgesture_frozen_n20_T100_seed{seed}.npz"
        r, margins, preds_over_t, labels = run_for_capture(f"dvsgesture_seed{seed}", path, thetas)
        results[f"dvsgesture_seed{seed}"] = r
        if seed == 0:
            # confusion-pair specific exit behavior, seed 0 (primary model)
            confusion_rows = []
            for a, b, label in CONFUSION_PAIRS:
                for c in (a, b):
                    mask = labels == c
                    if mask.sum() == 0:
                        continue
                    # at theta_star, does class c tend to exit into the confused class?
                    theta_star = r["theta_star_for_per_class_breakdown"]
                    m = margins[mask] >= theta_star
                    exit_t = np.array([np.argmax(mm) if mm.any() else 99 for mm in m])
                    pred_at_exit = preds_over_t[mask, exit_t]
                    acc_c = float((pred_at_exit == c).mean())
                    confused_into_other = float((pred_at_exit == (b if c == a else a)).mean())
                    confusion_rows.append(dict(
                        pair=label, class_idx=int(c), n=int(mask.sum()),
                        mean_exit_timestep=float((exit_t + 1).mean()),
                        accuracy_at_exit=acc_c,
                        fraction_exiting_into_confused_partner=confused_into_other,
                    ))
            results["confusion_pair_exit_behavior_seed0"] = confusion_rows

    path = f"{P1_ART}/rasters/nmnist_n20_T100_seed0.npz"
    r, margins, preds_over_t, labels = run_for_capture("nmnist_seed0", path, thetas)
    results["nmnist_seed0"] = r

    os.makedirs(f"{ART}/tables", exist_ok=True)
    with open(f"{ART}/tables/exp2_early_exit.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {ART}/tables/exp2_early_exit.json")


if __name__ == "__main__":
    main()
