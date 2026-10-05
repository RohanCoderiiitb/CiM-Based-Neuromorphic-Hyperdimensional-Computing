"""C4: sense-node placement variants (end, centre-tap, segmented) evaluated on the validated mesh and re-run through the 1B budget.

A variant maps every physical row r (0..511) to its distance from the sense node that reads it, in cell pitches, and fixes the farthest group. 'end': node below row 0
(distance r + 1). 'centre': node between rows 255 and 256 (distance |r - 255.5| + 0.5). 'segN_end' / 'segN_mid': the column is cut into N equal segments with a node at the
end / middle of each (distance within the segment). For every group size g the far group's terms are measured on the mesh at its true positions (within-group wire error,
row-line gain and spread of the 64-bitline macro with both-end drive) and the 1B budget (S1, drift 'moderate', 20 F^2, R_s 1 ohm) is evaluated at the far group and at the near group.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from drift.strategies import evaluate
from margin.core import params_for
from scaleup.droop import macro_stats
from wire.mesh import solve_mesh


def dist_fn(variant: str):
    if variant == "end":
        return lambda r: np.asarray(r, float) + 1.0
    if variant == "centre":
        return lambda r: np.abs(np.asarray(r, float) - 255.5) + 0.5
    kind, side = variant.split("_")                       # seg2_end, seg4_mid ...
    n = int(kind[3:]); L = C.ROWS_TOTAL // n
    def f(r):
        r = np.asarray(r, float); k = np.floor(r / L); off = r - k * L
        return off + 1.0 if side == "end" else np.abs(off - (L / 2 - 0.5)) + 0.5
    return f


def far_group_rows(variant: str, g: int, near: bool = False) -> np.ndarray:
    """The aligned group (rows G*g .. G*g+g-1, contiguous) farthest from (near=False) or closest to (near=True) its sense node, by the distance of its nearest row."""
    f = dist_fn(variant)
    best, rows_best = (1e9 if near else -1.0), None
    for G in range(C.ROWS_TOTAL // g):
        rows = np.arange(G * g, (G + 1) * g)
        d = float(f(rows).min())
        if (d < best) if near else (d > best):
            best, rows_best = d, rows
    return rows_best


def _idiff(p, pos, w, r):
    gaps = np.where(np.stack([w, ~w], axis=1), p.gap_lrs, p.gap_hrs)
    m = solve_mesh(gaps, pos, p, r_bl=r, r_wl=r, r_drv=C.R_DRV_DEFAULT)
    return float(m.i_col[0] - m.i_col[1])


def within_pos(g: int, pos: np.ndarray, r: float, area: int = C.AREA_1C, r_s: float = C.RS_1C, n_pat: int = 40, seed: int = C.WIRE_SEED) -> dict:
    """Uncorrectable within-group bitline error (1B wire/terms.within logic) for a group at explicit positions pos (ascending), and its group-mean worst step."""
    p = params_for(area, r_s); pos = np.sort(np.asarray(pos, float))
    rng = np.random.default_rng([seed, g, int(pos[0]), int(r * 100)])
    half = n_pat // 2; worst = 0.0; means = []
    for m in range(g + 1):
        vf, vh, ext = [], [], []
        for k in range(n_pat):
            w = np.zeros(g, bool); w[rng.choice(g, m, replace=False)] = True
            (vf if k < half else vh).append(_idiff(p, pos, w, r))
        for mode in ("near", "far"):
            w = np.zeros(g, bool); w[:m] = True
            ext.append(_idiff(p, pos, w[::-1].copy() if mode == "far" else w, r))
        vf, vh, ve = map(np.array, (vf, vh, ext))
        lo, hi = min(vf.min(), ve.min()), max(vf.max(), ve.max()); c = 0.5 * (lo + hi)
        worst = max(worst, 0.5 * (hi - lo), float(np.abs(vh - c).max()), float(np.abs(ve - c).max()))
        means.append(float(vf.mean()))
    return dict(within_a=worst, delta_a=float(np.min(np.abs(np.diff(means)))) if g > 0 else None)


def group_terms(variant: str, g: int, which: str, r: float = 0.72) -> dict:
    f = dist_fn(variant)
    rows = far_group_rows(variant, g, near=(which == "near"))
    pos = np.sort(f(rows))
    w = within_pos(g, pos, r)
    G = int(rows[0] // g)
    ms = [macro_stats(G, g, v, n_cells=32, n_own=6, n_other=20, r_drv=10.0, r_wl=0.72, drive_both_ends=True, pos_of_rows=f, g=g) for v in (0, 15, 31)]
    return dict(pos0=float(pos[0]), within_a=w["within_a"], delta_mesh_a=w["delta_a"], gain=min(m["gain_row"] for m in ms), row_std_a=max(m["row_std_a"] for m in ms))


def evaluate_variant(variant: str, g: int, sigma: float, r: float = 0.72, area: int = C.AREA_1C, r_s: float = C.RS_1C, scenario: str = "moderate", terms: dict | None = None,
                     n: int = 400) -> dict:
    nu, kappa = C.DRIFT_SCENARIOS[scenario]
    out = {}
    for which in ("far", "near"):
        t = terms[which] if terms else group_terms(variant, g, which, r)
        r_eff = r_s + r * t["pos0"]
        ex = dict(wire_within_a=t["within_a"], row5_a=C.N_SIGMA * t["row_std_a"], gain=t["gain"])
        ev = evaluate(g, area, r_eff, sigma, nu, kappa, 10.0, "S1", extras=ex, n=n, n_ages=3)
        w = min(ev["ages"], key=lambda a: a["margin_left_frac"])
        out[which] = dict(margin_frac=w["margin_left_frac"], margin_left_a=w["limit_a"] - w["total_a"], binding=w["binding"], closes=bool(ev["ok"]), cmrr_ok=bool(ev["cmrr_ok"]))
    ok = all(o["closes"] and o["cmrr_ok"] for o in out.values())
    worst = min(out, key=lambda k: out[k]["margin_frac"])
    return dict(variant=variant, g=g, sigma=sigma, r=r, ok=ok, worst=worst, margin_frac=out[worst]["margin_frac"], margin_left_a=out[worst]["margin_left_a"], binding=out[worst]["binding"])
