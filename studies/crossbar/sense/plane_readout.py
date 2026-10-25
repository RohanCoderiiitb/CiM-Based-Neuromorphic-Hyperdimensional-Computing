"""Optimisation item 9: bit-significance readout. The 160 columns are 20 neurons x 8 weight bit-planes; an error of +-1 in the match count of weight plane k shifts X by +-2^(b+k) (b = the count
bit-plane of the read): plane 7 by 128 x 2^b, plane 0 by 1 x 2^b. Yet every column gets the same bias, pulse and margin. Here:
  (1) the error rate each weight plane can tolerate is derived from the Phase 0 reference: the deployed model (r1, seed 0, 240 DVS-Gesture samples, early exit theta = 50) is run with count errors
      injected PER READ in the columns of ONE plane (+-1 with probability p/2 each, independent per read, column and read), SNN + HDC + exit decision recomputed from the perturbed X;
      the tolerated p of a plane is the largest tested for which the final prediction differs from the error-free run in <= 1 % of the samples and the accuracy loses <= 0.5 % (one sample in 240 is 0.4 %);
  (2) the tolerated p is turned into the noise the plane's front-end may have (p = 2 Q(0.5 / sigma_rel), sigma_rel = sigma / half step) relative to the design noise (5 sigma at p ~ 6e-7);
  (3) with all planes at their relaxed p together the accuracy is re-measured.   Usage: python -m sense.plane_readout [--trials 5]"""
from __future__ import annotations

import paths as RP

import argparse
import json
import sys
from math import erfc, sqrt
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "design" / "rtl"))
from tb.common import golden as G  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402

HQ = H.HQ
THETA = 50
GROUP = 4


def prep(mdl):
    """Per sample: n_reads[t, b] (non-empty groups of count bit-plane b), true plane sums."""
    W = mdl["W"].astype(np.int16) & 0xFF
    wk = np.stack([(W >> k) & 1 for k in range(8)]).astype(np.int64)             # [8, 20, 512]
    return wk


def reads_per_plane(c):          # c [T,512] ints -> [T,11] number of groups of 4 rows with a bit set in plane b
    out = np.zeros((c.shape[0], 11), np.int64)
    for b in range(11):
        bits = ((c >> b) & 1).reshape(c.shape[0], 512 // GROUP, GROUP).any(axis=2)
        out[:, b] = bits.sum(axis=1)
    return out


def noisy_run(mdl, row, p_planes, rng, nrd):
    c = mdl["counts"][row].astype(np.int64)
    X = c @ mdl["W"].astype(np.int64).T
    if np.any(p_planes > 0):
        dX = np.zeros_like(X)
        for k in range(8):
            if p_planes[k] <= 0:
                continue
            sgn = -(1 << 7) if k == 7 else (1 << k)
            for b in range(11):
                n = nrd[:, b]                                                         # [T]
                plus = rng.binomial(n[:, None].repeat(20, 1), p_planes[k] / 2)         # [T,20]
                minus = rng.binomial(n[:, None].repeat(20, 1), p_planes[k] / 2)
                dX += sgn * (1 << b) * (plus - minus)
        X = X + dX
    thr = np.asarray(mdl["thresh_int"][row], np.int64)
    T = X.shape[0]
    S = np.zeros((T, 20), np.uint8)
    v = np.zeros(20, np.int64)
    for t in range(T):
        vp = v + X[t]
        s = vp >= thr
        v = np.where(s, 0, vp)
        S[t] = s
    prefix = HQ.prefix_scores(HQ.agree_unfactorized(S, mdl["class_hv"]))
    t_exit, pred, _ = HQ.exit_point(prefix, THETA)
    return S, t_exit, pred


def evaluate(mdl, p_planes, trials, seed, nrds, rows):
    rng = np.random.default_rng(seed)
    acc, texit, spk_diff, flips = [], [], [], 0
    ref = {}
    for row in rows:
        S0, t0, p0 = noisy_run(mdl, row, np.zeros(8), rng, nrds[row])
        ref[row] = (S0, t0, p0)
    for tr in range(trials):
        ok = 0
        for row in rows:
            S, t, p = noisy_run(mdl, row, np.asarray(p_planes, float), rng, nrds[row])
            S0, t0, p0 = ref[row]
            ok += int(p == mdl["labels"][row])
            texit.append(t - t0)
            n = min(len(S), len(S0))
            spk_diff.append(float((S[:t0 + 1] != S0[:t0 + 1]).mean()))
            flips += int(p != p0)
        acc.append(ok / len(rows))
    base = np.mean([int(ref[r][2] == mdl["labels"][r]) for r in rows])
    return dict(accuracy=float(np.mean(acc)), accuracy_std=float(np.std(acc)), baseline_accuracy=float(base), pred_changed_frac=flips / (trials * len(rows)), mean_exit_shift=float(np.mean(texit)), spike_flip_frac=float(np.mean(spk_diff)))


def q_inv(p_half: float) -> float:
    lo, hi = 0.0, 12.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if 0.5 * erfc(mid / sqrt(2)) > p_half:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=4)
    ap.add_argument("--rows", type=int, default=240)
    a = ap.parse_args()
    mdl = H.load_model("r1", 0)
    rows = list(range(min(a.rows, len(mdl["labels"]))))
    nrds = {r: reads_per_plane(mdl["counts"][r].astype(np.int64)) for r in rows}
    ps = (1e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1, 3e-1)
    res = {"per_plane": {}}
    for k in range(8):
        res["per_plane"][str(k)] = {}
        for p in ps:
            pp = np.zeros(8); pp[k] = p
            r = evaluate(mdl, pp, a.trials, 1000 + k, nrds, rows)
            res["per_plane"][str(k)][str(p)] = r
            print(f"plane {k} p {p:g}: acc {r['accuracy']:.4f} (base {r['baseline_accuracy']:.4f}) pred changed {r['pred_changed_frac']:.4f} exit shift {r['mean_exit_shift']:+.2f} spike flips {r['spike_flip_frac']:.5f}", flush=True)
    # tolerated p per plane: largest p whose prediction-change fraction is <= 0.5 % and accuracy loss <= 0.3 %
    tol = {}
    for k in range(8):
        best = 0.0
        for p in ps:
            r = res["per_plane"][str(k)][str(p)]
            if r["pred_changed_frac"] <= 0.01 and r["baseline_accuracy"] - r["accuracy"] <= 0.005:
                best = p
        tol[k] = best
    res["tolerated_p"] = tol
    # noise relative to the design's (5 sigma <-> p = 5.7e-7): relaxation factor of the noise VARIANCE
    sig0 = q_inv(5.7e-7 / 2)
    res["variance_relaxation"] = {k: ((sig0 / q_inv(tol[k] / 2)) ** 2 if tol[k] > 0 else 1.0) for k in range(8)}
    print("tolerated p:", tol)
    print("variance relaxation:", {k: round(v, 2) for k, v in res["variance_relaxation"].items()})
    allr = evaluate(mdl, [tol[k] for k in range(8)], a.trials, 7, nrds, rows)
    res["all_planes_at_tolerated_p"] = allr
    print("all planes together:", allr)
    (RP.SENSE / "plane_readout.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
