"""C1: one complete 512-row column read group by group, with a per-group ladder table.

A group read activates the (up to g) contiguous rows of one group; the 2T2R column pair is solved on the validated 2-D mesh (wire.mesh.solve_mesh, K = 2: pure bitline effect;
row-line and rail effects are C2/C3) at the group's physical position, and the differential current I_diff is compared with that group's thresholds, indexed by the active count a
(known digitally: the popcount of the input bits in the group) to give the match count m. The group counts add up to the 512-row match count.

Table entries (the stored state): for every group G, active count a = 1..g and match count m = 0..a, the level C_G(a, m) at the centre of the pattern-dependent scatter
(minimax over the fit patterns and the two extremal match placements, as in 1B wire/decompose.py); thresholds sit half way between adjacent levels.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from device.constants import Params
from margin.core import params_for
from wire.mesh import solve_mesh

R_WIRE_DEFAULT = 0.72     # ohm per pitch (bitline and row line), the 1B recommended-point value [ASSUM]
R_DRV = C.R_DRV_DEFAULT


def group_rows(g: int, G: int, n_rows: int = C.ROWS_TOTAL) -> np.ndarray:
    """Physical rows (0-based, row 0 nearest the sense node) of group G; the last group of a non-dividing g is ragged (shorter)."""
    return np.arange(G * g, min((G + 1) * g, n_rows))


def n_groups(g: int, n_rows: int = C.ROWS_TOTAL) -> int:
    return -(-n_rows // g)


def pair_idiff(p: Params, rows: np.ndarray, w: np.ndarray, r: float, gaps_noise: np.ndarray | None = None, r_drv: float = R_DRV) -> float:
    """I_diff of one 2T2R pair for ACTIVE physical rows `rows` (ascending) with stored bits w (True = LRS in the + device). gaps_noise (len(rows), 2): optional extra gap offsets (nm)."""
    gaps = np.where(np.stack([w, ~w], axis=1), p.gap_lrs, p.gap_hrs)
    if gaps_noise is not None:
        gaps = gaps + gaps_noise
    m = solve_mesh(gaps, rows + 1.0, p, r_bl=r, r_wl=r, r_drv=r_drv)
    return float(m.i_col[0] - m.i_col[1])


def _patterns(rng, g_rows: int, a: int, m: int, n: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """n random (active-subset S, weights w over S with exactly m ones)."""
    out = []
    for _ in range(n):
        S = np.arange(g_rows) if a == g_rows else np.sort(rng.choice(g_rows, a, replace=False))
        w = np.zeros(a, bool); w[rng.choice(a, m, replace=False)] = True
        out.append((S, w))
    return out


def build_group_table(g: int, G: int, r: float = R_WIRE_DEFAULT, area: int = C.AREA_1C, r_s: float = C.RS_1C, n_fit: int = 24, n_held: int = 24, seed: int = C.WIRE_SEED) -> dict:
    """Levels, scatter and thresholds of one group for a = 1..g (g_eff = rows in the group)."""
    p = params_for(area, r_s)
    rows = group_rows(g, G)
    ge = len(rows)
    rng = np.random.default_rng([seed, g, G, int(r * 100)])
    cells = []
    for a in range(1, ge + 1):
        for m in range(a + 1):
            fit = [pair_idiff(p, rows[S], w, r) for S, w in _patterns(rng, ge, a, m, n_fit)]
            held = [pair_idiff(p, rows[S], w, r) for S, w in _patterns(rng, ge, a, m, n_held)]
            ext = []
            for mode in ("near", "far"):                   # matches packed at the near / far end of a random active subset of the group
                S = np.arange(ge) if a == ge else np.sort(rng.choice(ge, a, replace=False))
                w = np.zeros(a, bool); w[:m] = True
                ext.append(pair_idiff(p, rows[S], w[::-1].copy() if mode == "far" else w, r))
            lo, hi = min(min(fit), min(ext)), max(max(fit), max(ext))
            cen = 0.5 * (lo + hi)
            cells.append(dict(a=a, m=m, center=cen, half_range=0.5 * (hi - lo), mean=float(np.mean(fit)), held_dev=float(max(abs(v - cen) for v in held)),
                              ext_dev=float(max(abs(v - cen) for v in ext))))
    # tables as arrays: level[a][m], thresholds[a][k] between m=k and k+1
    level = {a: np.array([c_["center"] for c_ in cells if c_["a"] == a]) for a in range(1, ge + 1)}
    thr = {a: 0.5 * (level[a][:-1] + level[a][1:]) for a in level}
    steps = {a: np.diff(level[a]) for a in level}
    hr = {a: np.array([c_["half_range"] for c_ in cells if c_["a"] == a]) for a in level}
    held_dev = max(c_["held_dev"] for c_ in cells)
    top = ge
    return dict(G=G, g=g, rows=[int(rows[0]), int(rows[-1])], pos0=int(rows[0]) + 1, r=r, area=area, r_s=r_s, n_rows=ge,
                level={str(a): level[a].tolist() for a in level}, thr={str(a): thr[a].tolist() for a in thr},
                half_range={str(a): hr[a].tolist() for a in hr},
                span=float(level[top][-1] - level[top][0]), worst_step=float(min(np.min(steps[a]) for a in steps)), worst_step_full=float(np.min(steps[top])),
                within_a=float(max(c_["half_range"] for c_ in cells)), held_dev_a=float(held_dev), ext_dev_a=float(max(c_["ext_dev"] for c_ in cells)),
                antisym_dev=float(max(np.max(np.abs(level[a] + level[a][::-1])) for a in level)))


def decide(table: dict, a: int, i_diff: float) -> int:
    """Match count from the measured I_diff: number of thresholds of row a below it."""
    if a == 0:
        return 0
    return int(np.searchsorted(np.asarray(table["thr"][str(a)]), i_diff))
