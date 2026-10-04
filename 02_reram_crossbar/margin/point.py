"""Evaluate one operating point (g, cell area, R_s, sigma_lnG, HRS ratio) against the budget framework."""
from __future__ import annotations

import numpy as np

import device.constants as C
from margin import ladder as LD
from margin.core import RS_ZERO, draw_z, gap_hrs_for_ratio, levels, mc_levels, params_for, worst_step
from solver.budget import DETERMINISTIC, RANDOM, Term, close_budget


BUDGET_TERMS = ("device spread", "absolute signal (comparator noise)", "ReRAM HRS leakage residual")   # compression deliberately absent


def leakage_residual(a: int, p, ratio: float, tol: float) -> tuple[float, float]:
    """Uncorrectable part of ReRAM HRS leakage (term 3).

    The ladder is designed on the levels at the DESIGN ratio, so leakage itself (deterministic in (a, m)) is absorbed. What is left is the
    shift if the array's achieved ratio differs from the design ratio by +/- tol (program-verify window / die-to-die), max over m.
    Returns (residual_a, raw_shift_a) where raw_shift is the leakage shift an UNcorrected (no-leakage-aware) ladder would suffer."""
    gh_d = gap_hrs_for_ratio(ratio, p)
    ld = levels(a, a, p, gap_hrs=gh_d)["i_diff"]
    res = 0.0
    for r in (ratio * (1 - tol), min(ratio * (1 + tol), C.RATIO_CEILING)):
        if tol == 0.0 or abs(r - ratio) < 1e-12:
            continue
        res = max(res, float(np.max(np.abs(levels(a, a, p, gap_hrs=gap_hrs_for_ratio(r, p))["i_diff"] - ld))))
    ideal = levels(a, a, p, gap_hrs=C.GAP_NO_HRS)["i_diff"]
    return res, float(np.max(np.abs(ld - ideal)))


def evaluate_point(g: int, area: int, r_s: float, sigma: float, *, a: int | None = None, ratio: float = C.RATIO_CEILING, n: int = C.MC_DRAWS, z=None,
                   comp_sigma: float = C.COMP_SIGMA_I_A, n_sigma: float = C.N_SIGMA, headroom: float = C.HEADROOM,
                   ratio_tol: float = C.RATIO_TOL, cmrr_db: float = C.CMRR_ACHIEVABLE_DB) -> dict:
    a = g if a is None else a          # active rows; the sweep uses a = g (worst case), tests/report verify a < g
    p = params_for(area, r_s)
    gh = gap_hrs_for_ratio(ratio, p)
    if sigma > 0:
        z = draw_z(g, n) if z is None else z
        mc = mc_levels(g, a, p, sigma, z, gap_hrs=gh)
        lv, std, ip, im, skew = mc["mean_diff"], mc["std_diff"], mc["mean_plus"], mc["mean_minus"], mc["skew_diff"]
    else:
        nl = levels(g, a, p, gap_hrs=gh)
        lv, ip, im = nl["i_diff"], nl["i_plus"], nl["i_minus"]
        std = np.zeros_like(lv); skew = np.zeros_like(lv)
    delta, loc = worst_step(lv)
    # uncompressed reference step at the same location (R_s -> 0), nominal levels
    unc = levels(g, a, p, gap_hrs=gh, r_s=RS_ZERO)["i_diff"]
    delta_unc = float(abs(unc[loc] - unc[loc - 1]))
    resid, raw_leak = leakage_residual(a, p, ratio, ratio_tol)
    spread_max = float(std.max()); spread_loc = int(std.argmax())
    i_cm = 0.5 * float(0.5 * (ip[loc] + im[loc] + ip[loc - 1] + im[loc - 1]))
    cmrr_req = 20.0 * np.log10(i_cm / (C.CM_ERR_FRACTION * delta))
    terms = [Term(BUDGET_TERMS[0], RANDOM, n_sigma * spread_max),
             Term(BUDGET_TERMS[1], RANDOM, n_sigma * comp_sigma),
             Term(BUDGET_TERMS[2], DETERMINISTIC, resid)]
    b = close_budget(delta, terms, headroom)
    sig_tot = np.sqrt(std ** 2 + comp_sigma ** 2)
    mu_nu = LD.margin_factor(lv, LD.weighted_thresholds(lv, sig_tot), sig_tot, n_sigma, headroom, resid)
    mu_un = LD.margin_factor(lv, LD.uniform_thresholds(lv), sig_tot, n_sigma, headroom, resid)
    return dict(g=g, a=a, area=area, r_s=r_s, sigma=sigma, ratio=ratio, r_tx=p.r_tx,
                delta_a=delta, delta_loc=loc, delta_norm=delta / delta_unc, delta_unc_a=delta_unc, v_step=delta * r_s,
                i_cm_a=i_cm, cmrr_req_db=float(cmrr_req), cmrr_ok=bool(cmrr_req <= cmrr_db),
                spread_std_max_a=spread_max, spread_std_loc=spread_loc, max_abs_skew=float(np.abs(skew).max()),
                spread5_a=terms[0].value_a, comp5_a=terms[1].value_a, leak_resid_a=resid, leak_raw_shift_a=raw_leak,
                total_err_a=b.total_error_a, limit_a=b.limit_a, margin_left_a=b.margin_left_a,
                margin_left_frac=b.margin_left_frac_of_limit, budget_closes=b.closes, binding_term=b.binding,
                ok=bool(b.closes and cmrr_req <= cmrr_db),
                mu_nonuniform_min=float(mu_nu.min()), mu_uniform_min=float(mu_un.min()),
                mu_nonuniform_argmin=int(mu_nu.argmin()))
