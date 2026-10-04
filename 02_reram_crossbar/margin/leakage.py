"""Term 3: ReRAM HRS leakage (the HRS cells inside the column; distinct from the transistor off-leakage that 1A closed)."""
from __future__ import annotations

import numpy as np

import device.constants as C
from margin.core import gap_hrs_for_ratio, levels, params_for, worst_step
from solver.newton import solve_column


def leak_counts(g: int, ratio: float, area: int, r_s: float) -> float:
    """Current of a column with all g active branches at HRS, in units of one LRS branch's current (1A definition). R_tx dilutes the ratio."""
    p = params_for(area, r_s)
    gh = gap_hrs_for_ratio(ratio, p)
    act = np.ones((1, g), bool)
    leak = solve_column(np.full((1, g), gh), act, p).i_col[0]
    unit = solve_column(np.array([[p.gap_lrs]]), np.ones((1, 1), bool), p).i_col[0]
    return float(leak / unit)


def level_shift(g: int, area: int, r_s: float, ratio_actual: float, ratio_design: float) -> float:
    """max over m of |I_diff(ratio_actual) - I_diff(ratio_design)| at a = g, in amps: what a ladder designed at `ratio_design` sees."""
    p = params_for(area, r_s)
    la = levels(g, g, p, gap_hrs=gap_hrs_for_ratio(ratio_actual, p))["i_diff"]
    ld = levels(g, g, p, gap_hrs=gap_hrs_for_ratio(ratio_design, p))["i_diff"]
    return float(np.max(np.abs(la - ld)))


def usable_budget(g: int, area: int, r_s: float, ratio_design: float) -> tuple[float, float]:
    """(Delta, limit = Delta/2*(1-headroom)) at the design ratio, nominal levels."""
    p = params_for(area, r_s)
    d, _ = worst_step(levels(g, g, p, gap_hrs=gap_hrs_for_ratio(ratio_design, p))["i_diff"])
    return d, 0.5 * d * (1.0 - C.HEADROOM)


def window(g: int, area: int, r_s: float, ratio_design: float, share: float = C.LEAK_BUDGET_SHARE) -> tuple[float, float]:
    """Achieved-ratio window [r_lo, r_hi] over which a ladder designed at ratio_design keeps the leakage residual <= share of the usable margin.

    Returns (r_lo, r_hi); r_lo = 0 if the residual never exceeds the share down to ratio 20; r_hi capped at the model ceiling."""
    _, limit = usable_budget(g, area, r_s, ratio_design)
    target = share * limit

    def edge(lo, hi):          # lo is within the window, hi is outside (or the cap); find the boundary
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if level_shift(g, area, r_s, mid, ratio_design) <= target:
                lo = mid
            else:
                hi = mid
        return lo

    r_floor = 20.0
    r_lo = r_floor if level_shift(g, area, r_s, r_floor, ratio_design) <= target else edge(ratio_design, r_floor)
    r_lo = 0.0 if r_lo == r_floor else r_lo
    r_hi = C.RATIO_CEILING
    if ratio_design < C.RATIO_CEILING and level_shift(g, area, r_s, C.RATIO_CEILING, ratio_design) > target:
        r_hi = edge(ratio_design, C.RATIO_CEILING)
    return float(r_lo), float(r_hi)
