"""C0: first-order lumped bound on bitline wire IR, before the mesh. Linear small-signal perturbation of the ideal levels.

Model: active rows at physical positions p_i (pitches from the sense node). Bitline segment current = sum of the currents of the cells at or beyond it.
Excess bitline voltage at row k:  V_k = r * sum_{s<=k} (p_s - p_{s-1}) * I_seg(s)   (p_{-1} = 0). First-order cell error: dI_i = -g_c * V_i with g_c the cell's
small-signal conductance, 1/(R_LRS + R_tx), for LRS cells (HRS cells are negligible). Per column pair: I_diff changes by
    d = -g_c * sum_{i in M} V+_i  +  g_c * sum_{i not in M} V-_i       (M = matching rows, LRS in the + column)
(a) BETWEEN groups: the whole group sits behind r*p_0 ohm of bitline. That is the same as a larger sense resistor for that group: a per-group ladder removes the
    level shift, but the compression it causes SHRINKS the step: Delta_far < Delta_near (exact via the 1A solver with R_s -> R_s + r*p_0).
(b) WITHIN a group: the range of d over activation patterns with the same (a, m). The ladder can only be set at the centre of that range, so half the range is the
    uncorrectable residual. For a given (a, m) the total group current is the same for every pattern, so (b) does not depend on p_0 (checked numerically below).
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from device.model import device_resistance
from margin.core import levels, params_for, worst_step


def pair_error(pos: np.ndarray, match: np.ndarray, i_l: float, g_c: float, r: float) -> float:
    """First-order I_diff error d for one column pair. pos (n,) ascending physical positions of the active rows; match (n,) bool."""
    n = len(pos)
    seg = np.diff(np.concatenate([[0.0], pos]))

    def column_v(lrs_mask):
        i = np.where(lrs_mask, i_l, 0.0)
        tail = np.cumsum(i[::-1])[::-1]               # current through the segment feeding row k = sum_{i >= k}
        return r * np.cumsum(seg * tail)              # excess voltage at each row

    vp, vm = column_v(match), column_v(~match)
    return float(-g_c * vp[match].sum() + g_c * vm[~match].sum())


def pattern_range(g: int, pos0: float, stride: float, i_l: float, g_c: float, r: float, m: int, n_rand: int = 400, seed: int = 1) -> tuple[float, float]:
    """(half-range of d, mean of d) over activation patterns with a = g rows and m matches. Rows at pos0 + k*stride. Includes the near-packed and far-packed extremes."""
    pos = pos0 + stride * np.arange(g)
    rng = np.random.default_rng(seed)
    vals = []
    base = np.zeros(g, bool)
    for pat in ("near", "far"):
        mm = base.copy(); idx = np.arange(m) if pat == "near" else np.arange(g - m, g); mm[idx] = True
        vals.append(pair_error(pos, mm, i_l, g_c, r))
    for _ in range(n_rand):
        mm = base.copy(); mm[rng.choice(g, m, replace=False)] = True
        vals.append(pair_error(pos, mm, i_l, g_c, r))
    v = np.array(vals)
    return 0.5 * float(v.max() - v.min()), float(v.mean())


def bound(g: int, area: int, r_s: float, r: float, layout: str = "contiguous", n_rows: int = C.ROWS_TOTAL) -> dict:
    p = params_for(area, r_s)
    from solver.newton import solve_column
    i_l = float(solve_column(np.array([[p.gap_lrs]]), np.ones((1, 1), bool), p, r_s=1e-9).i_col[0])
    g_c = 1.0 / (float(device_resistance(p.gap_lrs, p=p)) + p.r_tx)
    ng = n_rows // g
    stride = 1.0 if layout == "contiguous" else float(ng)
    far0 = (n_rows - g) + 1.0 if layout == "contiguous" else (ng - 1) + 1.0   # pos of the first row of the farthest group
    near0 = 1.0
    half_ranges = [pattern_range(g, far0, stride, i_l, g_c, r, m)[0] for m in range(1, g)] or [0.0]
    half_ranges_near = [pattern_range(g, near0, stride, i_l, g_c, r, m)[0] for m in range(1, g)] or [0.0]
    # (a) between groups: compression of the far group = a larger sense resistor, via the validated 1A solver
    d_near = worst_step(levels(g, g, params_for(area, r_s + r * near0))["i_diff"])[0]
    d_far = worst_step(levels(g, g, params_for(area, r_s + r * far0))["i_diff"])[0]
    d_ideal = worst_step(levels(g, g, p)["i_diff"])[0]
    return dict(g=g, area=area, r=r, layout=layout, i_lrs_a=i_l, g_cell_s=g_c, within_halfrange_far_a=max(half_ranges),
                within_halfrange_near_a=max(half_ranges_near), delta_ideal_a=d_ideal, delta_near_a=d_near, delta_far_a=d_far,
                far_series_ohm=r * far0, offset_level_shift_far_a=abs(levels(g, g, params_for(area, r_s + r * far0))["i_diff"][g] - levels(g, g, p)["i_diff"][g]))
