"""C2 / C3: split wire-IR error into BETWEEN-group (correctable constant per group) and WITHIN-group (activation dependent), contiguous vs interleaved,
with the correction fitted on half the activation patterns and tested on the other half.

One task = (layout, g, r) at the recommended cell (20 F^2, R_s 5), nominal gaps (spread is a separate term), a single 2T2R pair (K = 2: pure bitline effect;
row-line effects are measured separately in wire/rowside.py), row driver R_DRV default.
For each probed group G, each a in {g, g/2} and each match count m: patterns = N random (S, w) with |S| = a and sum(w over S) = m, split into FIT / HELD-OUT halves,
plus the two extremal patterns (matches packed at the near end / far end of the group).

Corrections compared (all on the pair's I_diff, relative to the no-wire ideal level L0(a, m) of 1A):
  none          residual = I_mesh - L0                      (total wire error)
  group table   residual = I_mesh - mean_FIT(G, a, m)       per-group, per-(a, m) ladder offset (the contiguity scheme)
  minimax       residual = I_mesh - (min+max)/2 over FIT+extremes   the best constant for the worst case
  group gain    residual = I_mesh - alpha_G * L0           one scalar per group, fit by least squares on FIT (the related work's per-column scalar)
Usage: python -m wire.decompose [--workers N]
"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import device.constants as C
from margin.core import levels, params_for, worst_step
from wire.mesh import solve_mesh

ROOT = Path(__file__).resolve().parents[1]
OUTD = RP.WIRE_DECOMP
AREA, RS = 20, 5.0
GS = (4, 8, 16, 32, 64)
RS_WIRE = C.BL_R_PER_PITCH_SWEEP
LAYOUTS = ("contiguous", "interleaved")


def group_rows(layout: str, g: int, G: int, n_rows: int = C.ROWS_TOTAL) -> np.ndarray:
    ng = n_rows // g
    return (G * g + np.arange(g)) if layout == "contiguous" else (G + ng * np.arange(g))


def pair_idiff(p, rows: np.ndarray, w: np.ndarray, r: float, rdrv: float, r_wl: float | None = None) -> float:
    """Mesh I_diff of one 2T2R pair for active physical rows `rows` (ascending) with stored bits w (True = LRS in the + column)."""
    gaps = np.where(np.stack([w, ~w], axis=1), p.gap_lrs, p.gap_hrs)
    m = solve_mesh(gaps, rows + 1.0, p, r_bl=r, r_wl=r if r_wl is None else r_wl, r_drv=rdrv)
    return float(m.i_col[0] - m.i_col[1])


def probe_groups(layout: str, g: int) -> list[int]:
    ng = C.ROWS_TOTAL // g
    return sorted({0, ng // 4, ng // 2, (3 * ng) // 4, ng - 1})


def run_task(task: tuple) -> dict:
    layout, g, r = task
    p = params_for(AREA, RS)
    rng = np.random.default_rng([C.WIRE_SEED, g, int(r * 100), 0 if layout == "contiguous" else 1])
    n_pat = C.WIRE_PATTERNS_PER_CELL
    half = n_pat // 2
    out = dict(layout=layout, g=g, r=r, groups=[], area=AREA, r_s=RS, r_drv=C.R_DRV_DEFAULT)
    resid_all = {"none": [], "table_fit": [], "table_held": [], "minimax_fit": [], "minimax_held": [], "extreme": [], "gain_fit": [], "gain_held": []}
    for G in probe_groups(layout, g):
        rows = group_rows(layout, g, G)
        gd = dict(G=G, rows_span=[int(rows[0]), int(rows[-1])], cells=[])
        fit_x, fit_y, held_x, held_y = [], [], [], []      # for the per-group scalar gain
        for a in sorted({g, max(g // 2, 1)}):
            L0 = levels(g, a, p)["i_diff"]
            # the active subset: the first `a` rows of the group (a == g -> all rows); for a < g also random subsets below
            for m in range(0, a + 1):
                vals_f, vals_h, ext = [], [], []
                subsets = [np.arange(g)] if a == g else None
                for k in range(n_pat):
                    if a == g:
                        S = np.arange(g)
                    else:
                        S = np.sort(rng.choice(g, a, replace=False))
                    w = np.zeros(a, bool); w[rng.choice(a, m, replace=False)] = True
                    v = pair_idiff(p, rows[S], w, r, C.R_DRV_DEFAULT)
                    (vals_f if k < half else vals_h).append(v)
                for mode in ("near", "far"):                 # extremal match placement within the (full or random-a) active set
                    S = np.arange(g) if a == g else np.sort(rng.choice(g, a, replace=False))
                    w = np.zeros(a, bool); w[:m] = True
                    if mode == "far":
                        w = w[::-1].copy()
                    ext.append(pair_idiff(p, rows[S], w, r, C.R_DRV_DEFAULT))
                vf, vh, ve = np.array(vals_f), np.array(vals_h), np.array(ext)
                mean_f = vf.mean()
                lo, hi = min(vf.min(), ve.min()), max(vf.max(), ve.max())
                c = 0.5 * (lo + hi)
                cell = dict(a=a, m=m, L0=float(L0[m]), mean_fit=float(mean_f), mean_held=float(vh.mean()), range_fit=float(vf.max() - vf.min()),
                            minimax_halfrange=float(0.5 * (hi - lo)),
                            held_vs_table_max=float(np.abs(vh - mean_f).max()), fit_vs_table_max=float(np.abs(vf - mean_f).max()),
                            held_vs_minimax_max=float(np.abs(vh - c).max()), ext_vs_table_max=float(np.abs(ve - mean_f).max()),
                            ext_vs_minimax_max=float(np.abs(ve - c).max()), raw_shift=float(mean_f - L0[m]),
                            held_std=float(vh.std(ddof=1)), fit_std=float(vf.std(ddof=1)))
                gd["cells"].append(cell)
                fit_x += [L0[m]] * len(vf); fit_y += list(vf); held_x += [L0[m]] * len(vh); held_y += list(vh)
                resid_all["none"] += list(np.abs(np.concatenate([vf, vh]) - L0[m]))
                resid_all["table_fit"] += list(np.abs(vf - mean_f)); resid_all["table_held"] += list(np.abs(vh - mean_f))
                resid_all["minimax_fit"] += list(np.abs(vf - c)); resid_all["minimax_held"] += list(np.abs(vh - c)); resid_all["extreme"] += list(np.abs(ve - c))
        fx, fy, hx, hy = map(np.array, (fit_x, fit_y, held_x, held_y))
        alpha = float((fx * fy).sum() / (fx * fx).sum())          # per-group scalar gain, least squares on the FIT patterns
        gd["alpha"] = alpha
        gd["gain_fit_rms"] = float(np.sqrt(np.mean((fy - alpha * fx) ** 2))); gd["gain_held_rms"] = float(np.sqrt(np.mean((hy - alpha * hx) ** 2)))
        gd["none_rms"] = float(np.sqrt(np.mean((hy - hx) ** 2)))
        gd["gain_held_max"] = float(np.abs(hy - alpha * hx).max()); gd["none_max"] = float(np.abs(hy - hx).max())
        resid_all["gain_fit"] += list(np.abs(fy - alpha * fx)); resid_all["gain_held"] += list(np.abs(hy - alpha * hx))
        # between-group: group-mean levels (a = g) -> step Delta_G
        full = [c_ for c_ in gd["cells"] if c_["a"] == g]
        means = np.array([c_["mean_fit"] for c_ in sorted(full, key=lambda c_: c_["m"])])
        gd["delta_group_a"] = float(np.min(np.abs(np.diff(means)))) if len(means) > 1 else None
        out["groups"].append(gd)
    out["summary"] = {k: dict(max=float(np.max(v)), rms=float(np.sqrt(np.mean(np.square(v)))), p99=float(np.percentile(v, 99))) for k, v in resid_all.items() if v}
    cells = [c_ for gd in out["groups"] for c_ in gd["cells"]]
    out["within_budget_term_a"] = float(max(max(c_["held_vs_minimax_max"], c_["minimax_halfrange"], c_["ext_vs_minimax_max"]) for c_ in cells))
    out["within_budget_term_a_a_eq_g"] = float(max(max(c_["held_vs_minimax_max"], c_["minimax_halfrange"], c_["ext_vs_minimax_max"]) for c_ in cells if c_["a"] == g))
    out["max_raw_shift_a"] = float(max(abs(c_["raw_shift"]) for c_ in cells))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--g", type=int, nargs="+", default=list(GS))
    args = ap.parse_args()
    OUTD.mkdir(parents=True, exist_ok=True)
    tasks = [(lo, g, r) for g in args.g for lo in LAYOUTS for r in RS_WIRE if not RP.decomposition_json(lo, g, r).exists()]
    tasks.sort(key=lambda t: -t[1])
    with ProcessPoolExecutor(args.workers) as ex:
        for t, res in zip(tasks, ex.map(run_task, tasks)):
            RP.decomposition_json(t[0], t[1], t[2]).write_text(json.dumps(res))
            s = res["summary"]
            print(t, "within term %.2f uA" % (res["within_budget_term_a"] * 1e6), "none max %.1f table_held max %.2f" % (s["none"]["max"] * 1e6, s["table_held"]["max"] * 1e6), flush=True)


if __name__ == "__main__":
    main()
