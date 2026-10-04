"""Building blocks for the 1B-i margin sweeps: operating-point parameters, level curves, spread Monte Carlo.

Everything runs on the validated 1A Newton solver with the linear R_tx (1A section 4: good to 0.07%).
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from device.constants import DEFAULT, Params
from device.model import on_off_ratio
from solver.newton import solve_differential

RS_ZERO = 1e-9   # ohm, [MODEL] "no sense resistor": the uncompressed reference step


def params_for(area_f2: int, r_s: float) -> Params:
    """Operating-point parameters: R_tx from the 1A simulation for this cell area (R_tx*W ~ const), W from the 1A rule."""
    w = C.TX_FILL * area_f2 * C.FEATURE_NM * 1e-3     # [MODEL] 1A width rule
    return DEFAULT.with_(r_tx=C.RTX_BY_AREA[area_f2], tx_w_um=w, r_s=r_s)


def gap_hrs_for_ratio(ratio: float, p: Params = DEFAULT) -> float:
    """[MODEL] HRS gap that gives a device on/off ratio at V_read with LRS at its programmed gap (monotone, bisection)."""
    if ratio >= C.RATIO_CEILING - 1e-9:
        return p.gap_hrs
    lo, hi = p.gap_lrs, p.gap_hrs
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if on_off_ratio(p.gap_lrs, mid, p=p) < ratio:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def levels(g: int, a: int, p: Params, sigma_lng: float = 0.0, gap_hrs: float | None = None, r_s=None) -> dict:
    """Level curve for `a` active rows (a <= g; inactive rows carry no branch), m = 0..a matches, population-mean gaps.

    Returns i_plus, i_minus, i_diff over m = 0..a."""
    gh = (p.gap_hrs if gap_hrs is None else gap_hrs)
    sh = 0.0   # nominal levels. For sigma > 0 the ladder uses the Monte-Carlo POPULATION-MEAN levels (mc_levels): a mean-conductance
               # shift of the gaps is NOT enough - Jensen's inequality on the compressive column moves the mean level by up to 0.11 Delta at sigma 0.2.
    if sigma_lng != 0.0:
        raise ValueError("levels() is nominal-only; use mc_levels() for population-mean levels at sigma > 0")
    m = np.arange(a + 1)
    stored = np.arange(a)[None, :] < m[:, None]
    gp = np.where(stored, p.gap_lrs, gh) + sh
    gm = np.where(stored, gh, p.gap_lrs) + sh
    s = solve_differential(gp, gm, np.ones_like(stored), p, r_s=r_s)
    return dict(m=m, i_plus=s.i_plus, i_minus=s.i_minus, i_diff=s.i_diff)


def worst_step(i_diff: np.ndarray) -> tuple[float, int]:
    """Smallest |I_diff(m) - I_diff(m-1)| and its location (the m it steps INTO; ties -> first)."""
    st = np.abs(np.diff(i_diff))
    k = int(np.argmin(st))
    return float(st[k]), k + 1


def draw_z(g: int, n: int, seed: int = C.MC_SEED) -> tuple[np.ndarray, np.ndarray]:
    """Common random numbers for the + and - devices, shape (n, g). Shared across sigma, R_s and cell area, so sweeps differ only by physics."""
    rng = np.random.default_rng([seed, g])
    return rng.standard_normal((n, g)), rng.standard_normal((n, g))


def mc_levels(g: int, a: int, p: Params, sigma_lng: float, z: tuple[np.ndarray, np.ndarray], gap_hrs: float | None = None,
              max_elems: int = 3_000_000) -> dict:
    """Spread Monte Carlo at (g, a): per-m mean and std of I_diff, I_plus, I_minus over len(z) draws.

    gap = gap_nom - g0*sigma*z  (log-normal conductance, 1A). Uses the first `a` columns of z. Chunked over m to bound memory."""
    zp, zm = z[0][:, :a], z[1][:, :a]
    n = zp.shape[0]
    gh = p.gap_hrs if gap_hrs is None else gap_hrs
    m_all = np.arange(a + 1)
    chunk = max(1, max_elems // (n * max(a, 1)))
    out = {k: np.empty(a + 1) for k in ("mean_diff", "std_diff", "mean_plus", "mean_minus", "std_plus", "std_minus", "skew_diff")}
    for lo in range(0, a + 1, chunk):
        ms = m_all[lo:lo + chunk]
        stored = np.arange(a)[None, None, :] < ms[:, None, None]                 # (mc, 1, a)
        gp = np.where(stored, p.gap_lrs, gh) - p.g0 * sigma_lng * zp[None]        # (mc, n, a)
        gm = np.where(stored, gh, p.gap_lrs) - p.g0 * sigma_lng * zm[None]
        s = solve_differential(gp, gm, np.ones(gp.shape, dtype=bool), p)
        out["mean_diff"][lo:lo + chunk] = s.i_diff.mean(axis=1)
        out["std_diff"][lo:lo + chunk] = s.i_diff.std(axis=1, ddof=1)
        out["mean_plus"][lo:lo + chunk] = s.i_plus.mean(axis=1)
        out["mean_minus"][lo:lo + chunk] = s.i_minus.mean(axis=1)
        dd = s.i_diff - s.i_diff.mean(axis=1, keepdims=True)
        sd = dd.std(axis=1)
        out["skew_diff"][lo:lo + chunk] = np.where(sd > 0, (dd ** 3).mean(axis=1) / np.where(sd > 0, sd, 1.0) ** 3, 0.0)
        out["std_plus"][lo:lo + chunk] = s.i_plus.std(axis=1, ddof=1)
        out["std_minus"][lo:lo + chunk] = s.i_minus.std(axis=1, ddof=1)
    return out
