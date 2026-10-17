"""Mesh-measured wire terms over the (g, cell area, R_s, wire r) grid, for the final budget (1B Part E). Writes results/wire_resistance/wire_terms_per_point.json.

Both extreme contiguous groups are evaluated (NEAR = rows 0..g-1, FAR = the last g rows): the within-group error grows with the group's current (largest NEAR), while
the step Delta shrinks with distance (smallest FAR); both are monotone in distance (checked on 5 probed groups in decompose.py), so these two bound every group.
Per point and group, a = g, nominal gaps (spread is a separate term), one 2T2R pair, R_DRV default:
  within_a       uncorrectable WITHIN-group bitline error: max over m of max(held-out residual, fit half-range, extremal-pattern residual) about the minimax per-(a,m) level
  delta_far_a    the far group's worst step from its group-mean levels (between-group compression: a per-group ladder fixes the LEVEL shift, not this)
Per point, K = 32 macro, pair at the far end of the row (worst), driver R_DRV:
  row_gain       per-column-position gain of the row line (correctable by a per-column ladder scale; multiplies Delta)
  row_std_a      spread of the pair's I_diff across the other columns' weights (uncorrectable, random-like; 1 sigma, worst over own patterns)
Usage: python -m wire.terms [--workers N]
"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import device.constants as C
from margin.core import levels, params_for
from wire.decompose import group_rows, pair_idiff
from wire.mesh import solve_mesh

OUT = RP.WIRE_TERMS_JSON
G_W = (1, 2, 4, 8, 16, 32, 64)


def within(g: int, area: int, r_s: float, r: float, which: str = "far", rdrv: float = C.R_DRV_DEFAULT, n_pat: int = C.WIRE_PATTERNS_PER_CELL) -> dict:
    p = params_for(area, r_s)
    rows = group_rows("contiguous", g, C.ROWS_TOTAL // g - 1 if which == "far" else 0)
    rng = np.random.default_rng([C.WIRE_SEED, g, area, int(r_s * 10), int(r * 100), 0 if which == "far" else 1])
    half = n_pat // 2
    worst, means = 0.0, []
    for m in range(g + 1):
        vf, vh, ext = [], [], []
        for k in range(n_pat):
            w = np.zeros(g, bool); w[rng.choice(g, m, replace=False)] = True
            (vf if k < half else vh).append(pair_idiff(p, rows, w, r, rdrv))
        for mode in ("near", "far"):
            w = np.zeros(g, bool); w[:m] = True
            ext.append(pair_idiff(p, rows, w[::-1].copy() if mode == "far" else w, r, rdrv))
        vf, vh, ve = map(np.array, (vf, vh, ext))
        lo, hi = min(vf.min(), ve.min()), max(vf.max(), ve.max())
        c = 0.5 * (lo + hi)
        worst = max(worst, 0.5 * (hi - lo), float(np.abs(vh - c).max()), float(np.abs(ve - c).max()))
        means.append(float(vf.mean()))
    return dict(within_a=worst, delta_far_a=float(np.min(np.abs(np.diff(means)))) if g > 0 else None)


def row_side(g: int, area: int, r_s: float, r: float, which: str = "far", K: int = C.MACRO_COLS, rdrv: float = C.R_DRV_DEFAULT, n_own: int = 8, n_other: int = 10) -> dict:
    p = params_for(area, r_s)
    rows = group_rows("contiguous", g, C.ROWS_TOTAL // g - 1 if which == "far" else 0)
    pairs = K // 2; pi = pairs - 1
    rng = np.random.default_rng([C.WIRE_SEED, g, area, K, int(r * 100), 0 if which == "far" else 1])
    stds, mns, als = [], [], []
    for _ in range(n_own):
        w_own = rng.integers(0, 2, g).astype(bool)
        vals = []
        for _ in range(n_other):
            W = rng.integers(0, 2, (g, pairs)).astype(bool); W[:, pi] = w_own
            st = np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)
            f = solve_mesh(np.where(st, p.gap_lrs, p.gap_hrs), rows + 1.0, p, r_bl=r, r_wl=r, r_drv=rdrv)
            vals.append(f.i_col[2 * pi] - f.i_col[2 * pi + 1])
        al = solve_mesh(np.where(np.stack([w_own, ~w_own], 1), p.gap_lrs, p.gap_hrs), rows + 1.0, p, r_bl=r, r_wl=r, r_drv=rdrv)
        als.append(al.i_col[0] - al.i_col[1]); v = np.array(vals); mns.append(v.mean()); stds.append(v.std(ddof=1))
    als, mns = np.array(als), np.array(mns)
    gain = float((als * mns).sum() / (als * als).sum()) if np.abs(als).sum() > 0 else 1.0
    return dict(row_gain=gain, row_std_a=float(np.max(stds)))


def task(cfg):
    g, area, r_s, r = cfg
    d = dict(g=g, area=area, r_s=r_s, r=r)
    for which in ("far", "near"):
        w = within(g, area, r_s, r, which) if g > 1 else dict(within_a=0.0, delta_far_a=None)
        rw = row_side(g, area, r_s, r, which) if g > 1 else dict(row_gain=None, row_std_a=0.0)
        d[f"within_{which}_a"] = w["within_a"]; d[f"delta_{which}_a"] = w["delta_far_a"]
        d[f"row_gain_{which}"] = rw["row_gain"]; d[f"row_std_{which}_a"] = rw["row_std_a"]
    return d


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=8); args = ap.parse_args()
    # g = 64: R_s only at 5 ohm (the group wire term is dominated by the 60-250 ohm of bitline, so R_s hardly matters; final.py falls back to R_s = 5)
    cfgs = [(g, a, rs, r) for g in G_W for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP for r in C.BL_R_PER_PITCH_SWEEP if not (g == 64 and rs != 5.0)]
    cfgs.sort(key=lambda c: -c[0])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(task, cfgs, chunksize=2))
    OUT.write_text(json.dumps(res))
    print("wrote", OUT, len(res))


if __name__ == "__main__":
    main()
