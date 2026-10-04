"""Conductance drift (1B Part D):  G_i(t) = G_i(t0) * (t/t0)^(-nu_i),  nu_i ~ N(nu_mean, sigma_nu^2) per cell, independent.

In gap terms (A = I0 exp(-gap/g0)):  gap_i(t) = gap_i(t0) + g0 * nu_i * ln(t/t0).  sigma_lnG is the spread at t0 (post program-verify).
LRS and HRS cells drift with the same law (assumption). Everything reuses the validated 1A Newton solver.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from device.constants import Params
from solver.newton import solve_differential


def draw_z4(g: int, n: int, seed: int = C.MC_SEED + 1):
    """Common random numbers: spread (+,-) and exponent (+,-) draws, each (n, g)."""
    rng = np.random.default_rng([seed, g])
    return tuple(rng.standard_normal((n, g)) for _ in range(4))


def mc_levels_drift(g: int, a: int, p: Params, sigma_lng: float, nu_mean: float, sigma_nu: float, ln_tau: float, z4, gap_hrs=None,
                    ln_scale: float = 0.0, max_elems: int = 3_000_000) -> dict:
    """Per-count mean/std of I_diff, mean I_plus/I_minus at age ln_tau = ln(t/t0). ln_scale: extra GLOBAL log-conductance factor (the ladder's estimate of the
    drift scale in strategy 3; 0 otherwise); applied as gap shift -g0*ln_scale."""
    zp, zm, np_, nm_ = (z[:, :a] for z in z4)
    n = zp.shape[0]
    gh = p.gap_hrs if gap_hrs is None else gap_hrs
    m_all = np.arange(a + 1)
    chunk = max(1, max_elems // (n * max(a, 1)))
    out = {k: np.empty(a + 1) for k in ("mean_diff", "std_diff", "mean_plus", "mean_minus")}
    for lo in range(0, a + 1, chunk):
        ms = m_all[lo:lo + chunk]
        stored = np.arange(a)[None, None, :] < ms[:, None, None]
        sh_p = p.g0 * (nu_mean + sigma_nu * np_) * ln_tau - p.g0 * ln_scale
        sh_m = p.g0 * (nu_mean + sigma_nu * nm_) * ln_tau - p.g0 * ln_scale
        gp = np.where(stored, p.gap_lrs, gh) - p.g0 * sigma_lng * zp[None] + sh_p[None]
        gm = np.where(stored, gh, p.gap_lrs) - p.g0 * sigma_lng * zm[None] + sh_m[None]
        s = solve_differential(gp, gm, np.ones(gp.shape, dtype=bool), p)
        out["mean_diff"][lo:lo + chunk] = s.i_diff.mean(axis=1)
        out["std_diff"][lo:lo + chunk] = s.i_diff.std(axis=1, ddof=1)
        out["mean_plus"][lo:lo + chunk] = s.i_plus.mean(axis=1)
        out["mean_minus"][lo:lo + chunk] = s.i_minus.mean(axis=1)
    return out


def ages(life_years: float, n: int = C.DRIFT_AGES) -> np.ndarray:
    """ln(t/t0) for n log-spaced ages from t0 to the horizon (inclusive)."""
    return np.linspace(0.0, np.log(life_years * C.SECONDS_PER_YEAR / C.DRIFT_T0_S), n)
