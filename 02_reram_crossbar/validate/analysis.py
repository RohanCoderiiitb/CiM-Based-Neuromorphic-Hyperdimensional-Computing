"""Supporting 1A measurements (all via the Newton solver; the solver is validated separately)."""
from __future__ import annotations

import numpy as np

from device.constants import DEFAULT, GAP_HRS, GAP_LRS, SIGMA_LNG, Params
from device.model import device_resistance, on_off_ratio
from device.spread import resistance_cv, sample_gaps
from solver.newton import solve_column, solve_differential

RS_ZERO = 1e-9   # ohm; "no compression" reference (R_s -> 0)


def ratio_vs_gap(p: Params = DEFAULT):
    """On/off ratio at V_read for degraded programming; returns rows (label, gap_lrs, gap_hrs, ratio)."""
    rows = []
    for gh in (1.7, 1.65, 1.6, 1.55, 1.5, 1.45, 1.4, 1.35, 1.3):
        rows.append(("HRS short", GAP_LRS, gh, float(on_off_ratio(GAP_LRS, gh, p=p))))
    for gl in (0.2, 0.225, 0.25, 0.275, 0.3, 0.325, 0.35, 0.4):
        rows.append(("LRS long", gl, GAP_HRS, float(on_off_ratio(gl, GAP_HRS, p=p))))
    for gl, gh in ((0.25, 1.6), (0.3, 1.5), (0.3, 1.45), (0.35, 1.4), (0.4, 1.4)):
        rows.append(("both", gl, gh, float(on_off_ratio(gl, gh, p=p))))
    return rows


def gap_for_ratio(target: float, p: Params = DEFAULT) -> float:
    """HRS gap (LRS at minGap) that yields a given device on/off ratio at V_read. Closed form via bisection."""
    lo, hi = GAP_LRS, GAP_HRS
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if on_off_ratio(GAP_LRS, mid, p=p) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def single_cell_margin(p: Params = DEFAULT, n_sigma: float = 5.0, sigma_lng: float = SIGMA_LNG):
    """Stored-1 vs stored-0 I_diff for one active row. Margin = I_diff(1) - I_diff(0) = 2*I_diff(1) by symmetry.

    n-sigma worst corner under log-normal spread: LRS conductance prefactor low by exp(-n*s), HRS high by exp(+n*s),
    i.e. gap shifts of +/- g0*n*s. No clipping, so the corner is exactly n sigma.
    """
    one = lambda gp, gm: solve_differential(np.array([[gp]]), np.array([[gm]]), np.ones((1, 1), bool), p)
    nom = one(p.gap_lrs, p.gap_hrs)
    shift = p.g0 * n_sigma * sigma_lng
    gl, gh = p.gap_lrs + shift, p.gap_hrs - shift
    worst = one(gl, gh)
    i_lrs = float(solve_column(np.array([[p.gap_lrs]]), np.ones((1, 1), bool), p).i_col[0])
    return dict(sigma_lng=sigma_lng, i_plus=float(nom.i_plus[0]), i_minus=float(nom.i_minus[0]),
                i_diff_one=float(nom.i_diff[0]), margin_nom=2 * float(nom.i_diff[0]),
                i_diff_one_5s=float(worst.i_diff[0]), margin_5s=2 * float(worst.i_diff[0]),
                gap_lrs_5s=gl, gap_hrs_5s=gh, i_lrs_single=i_lrs)


def hrs_leakage_counts(g: int, gap_hrs: float, p: Params = DEFAULT, r_tx=None) -> float:
    """Current of a column with all g active branches at HRS (the m=0 '+' column), in units of one LRS-branch current."""
    act = np.ones((1, g), bool)
    leak = solve_column(np.full((1, g), gap_hrs), act, p, r_tx=r_tx).i_col[0]
    unit = solve_column(np.array([[p.gap_lrs]]), np.ones((1, 1), bool), p, r_tx=r_tx).i_col[0]
    return float(leak / unit)


def linear_gap_continuous(g: int, r_s: float, r_eff: float) -> float:
    return 1.0 / (1.0 + r_s * g / r_eff) ** 2


def linear_gap_discrete(g: int, r_s: float, r_eff: float) -> float:
    """Exact step I(g)-I(g-1) of I(m)=V*m*G/(1+Rs*m*G), normalised to the uncompressed step V*G."""
    G = 1.0 / r_eff
    f = lambda m: m * G / (1.0 + r_s * m * G)
    return (f(g) - f(g - 1)) / G


def level_gap_single_column(g: int, p: Params = DEFAULT, r_s=None, r_tx=None, gap_hrs=None):
    """Simulated step between adjacent levels of ONE column (a=g active, m LRS branches), normalised to the R_s->0
    step. Returns gap array for m=1..g. Includes HRS leakage branches."""
    gh = p.gap_hrs if gap_hrs is None else gap_hrs
    m = np.arange(g + 1)
    stored = np.arange(g)[None, :] < m[:, None]
    gaps = np.where(stored, p.gap_lrs, gh)
    act = np.ones_like(stored)
    i = solve_column(gaps, act, p, r_s=r_s, r_tx=r_tx).i_col
    i0 = solve_column(gaps, act, p, r_s=RS_ZERO, r_tx=r_tx).i_col
    return np.diff(i) / np.diff(i0)


def level_gap_differential(g: int, p: Params = DEFAULT, r_s=None, r_tx=None):
    m = np.arange(g + 1)
    stored = np.arange(g)[None, :] < m[:, None]
    gp = np.where(stored, p.gap_lrs, p.gap_hrs)
    gm = np.where(stored, p.gap_hrs, p.gap_lrs)
    act = np.ones_like(stored)
    i = solve_differential(gp, gm, act, p, r_s, r_tx).i_diff
    i0 = solve_differential(gp, gm, act, p, RS_ZERO, r_tx).i_diff
    return np.diff(i) / np.diff(i0)


def r_eff_lrs(p: Params = DEFAULT, r_tx=None) -> float:
    """Linear-theory LRS resistance including R_tx at V_read (secant, no sinh correction)."""
    return float(device_resistance(p.gap_lrs, p=p) + (p.r_tx if r_tx is None else r_tx))


def spread_numbers(sigma_lng: float = SIGMA_LNG, n: int = 400000, seed: int = 5):
    """Requested vs achieved spread for log-normal conductance, and the fraction of draws outside [minGap, maxGap]
    (informational only: there is no clipping, so nothing is moved)."""
    from device.constants import MAX_GAP, MIN_GAP
    rng = np.random.default_rng(seed)
    out = {}
    for name, nom in (("LRS", GAP_LRS), ("HRS", GAP_HRS)):
        gaps = sample_gaps(rng, np.full(n, nom), sigma_lng)
        a_amp = np.exp(-gaps / DEFAULT.g0)
        r = device_resistance(gaps)
        out[name] = dict(gap_nom=nom, sigma_lng_req=sigma_lng, sigma_lng_ach=float(np.std(np.log(a_amp))),
                         sigma_gap_req=DEFAULT.g0 * sigma_lng, sigma_gap_ach=float(np.std(gaps)),
                         cv_R_analytic=resistance_cv(sigma_lng), cv_R_ach=float(r.std() / r.mean()),
                         mean_R=float(r.mean()), frac_exactly_on_limit=float(np.mean((gaps == MIN_GAP) | (gaps == MAX_GAP))),
                         frac_beyond_gap_limits=float(np.mean((gaps < MIN_GAP) | (gaps > MAX_GAP))))
    return out


def level_curves(g: int, p: Params = DEFAULT, r_tx=None):
    """Nominal single-column and differential level curves at a = g, m = 0..g, sinh device, R_tx linear.

    Returns dict with currents, absolute steps (A) and steps normalised to the R_s -> 0 step (the 'gap')."""
    m = np.arange(g + 1)
    stored = np.arange(g)[None, :] < m[:, None]
    gp = np.where(stored, p.gap_lrs, p.gap_hrs)
    gm = np.where(stored, p.gap_hrs, p.gap_lrs)
    act = np.ones_like(stored)
    s = solve_differential(gp, gm, act, p, r_tx=r_tx)
    z = solve_differential(gp, gm, act, p, r_s=RS_ZERO, r_tx=r_tx)
    return dict(m=m, i_plus=s.i_plus, i_minus=s.i_minus, i_diff=s.i_diff,
                step_single=np.diff(s.i_plus), step_diff=np.diff(s.i_diff),
                gap_single=np.diff(s.i_plus) / np.diff(z.i_plus), gap_diff=np.diff(s.i_diff) / np.diff(z.i_diff))


def worst_gaps(g: int, p: Params = DEFAULT, r_tx=None) -> dict:
    c = level_curves(g, p, r_tx)
    ks, kd = int(np.argmin(c["gap_single"])), int(np.argmin(c["gap_diff"]))
    mid = g // 2
    return dict(g=g, worst_single=float(c["gap_single"][ks]), worst_single_at_m=ks + 1,
                worst_diff=float(c["gap_diff"][kd]), worst_diff_at_m=kd + 1,
                diff_at_m_eq_g=float(c["gap_diff"][-1]), diff_at_m_eq_1=float(c["gap_diff"][0]),
                ratio=float(c["gap_diff"][kd] / c["gap_single"][ks]),
                min_step_diff_a=float(c["step_diff"][kd]),
                i_plus_mid_a=float(c["i_plus"][mid]), i_minus_mid_a=float(c["i_minus"][mid]),
                i_diff_mid_a=float(c["i_diff"][mid]),
                cm_over_step=float(0.5 * (c["i_plus"][mid] + c["i_minus"][mid]) / c["step_diff"][kd]))
