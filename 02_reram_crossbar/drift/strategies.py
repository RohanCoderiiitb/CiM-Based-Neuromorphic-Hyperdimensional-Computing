"""Drift strategies evaluated against the budget framework (1B Part D).

At each checked age t the data levels are the Monte-Carlo population means of cells that have drifted; the READOUT's ladder depends on the strategy:
  S1 headroom : ladder fixed at manufacture, designed at the geometric-mean age of [t0, horizon]. Mean drift becomes a DETERMINISTIC level shift
                max_m |mean_m(t) - ladder_m|; the drift spread (sigma_nu ln(t/t0)) grows the random spread term.
  S2 refresh  : the same fixed-ladder logic but every cell is reprogrammed every T_r, so the age only runs over [t0, T_r] (fresh spread each time).
  S3 reference: n_ref reference cells (known pattern) estimate the log conductance scale; the ladder is re-derived from that estimate. This cancels the common-mode
                drift but the estimate has its own error:  eps ~ N(0, s_ref^2 / n_ref),  s_ref^2 = sigma_lnG^2 + (sigma_nu ln tau)^2  ('abs': references compared with the
                spec value, so they bring their own t0 spread)  or  (sigma_nu ln tau)^2  ('ratio': each reference cell's t0 reading is stored, an extra calibration step).
                eps moves EVERY threshold of the group together: a RANDOM term 5 sigma_eps max_m |dL_m/d ln scale| that is ADDED to the budget.
All other terms are those of 1B-i (spread at 5 sigma, comparator, HRS-leak residual) plus optional wire / row terms passed in by the caller.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from drift.model import ages, draw_z4, mc_levels_drift
from margin.core import RS_ZERO, gap_hrs_for_ratio, params_for, worst_step
from margin.point import leakage_residual
from solver.budget import DETERMINISTIC, RANDOM, Term, close_budget

_DLN = 0.03   # finite-difference step in ln(scale) for dL/dln(scale)


def _budget_at_age(g, p, sigma, nu, kappa, ln_tau, z4, strategy, ln_design, n_ref, ref_mode, extras, gh, leak_resid, cache, comp_sigma=C.COMP_SIGMA_I_A):
    sn = kappa * nu
    data = mc_levels_drift(g, g, p, sigma, nu, sn, ln_tau, z4, gap_hrs=gh)
    gain = extras.get("gain", 1.0)
    delta, loc = worst_step(data["mean_diff"])
    delta *= gain
    terms = [Term("device spread", RANDOM, C.N_SIGMA * float(data["std_diff"].max()) * gain),
             Term("absolute signal (comparator noise)", RANDOM, C.N_SIGMA * comp_sigma),
             Term("ReRAM HRS leakage residual", DETERMINISTIC, leak_resid * gain)]
    if extras.get("wire_within_a", 0.0) > 0:
        terms.append(Term("wire IR (within group)", DETERMINISTIC, extras["wire_within_a"]))
    if extras.get("row5_a", 0.0) > 0:
        terms.append(Term("row-driver IR", RANDOM, extras["row5_a"]))
    for name, kind, val in extras.get("extra_terms", ()):          # 1C: terms measured after 1B (droop, crosstalk, quantisation ...), absolute uA, not scaled by the row gain
        if val > 0:
            terms.append(Term(name, kind, val))
    ref_term = 0.0
    if strategy in ("S1", "S2"):
        key = ("ladder", ln_design)
        if key not in cache:
            cache[key] = mc_levels_drift(g, g, p, sigma, nu, sn, ln_design, z4, gap_hrs=gh)["mean_diff"]
        shift = float(np.max(np.abs(data["mean_diff"] - cache[key]))) * gain
    elif strategy == "S3":
        # ladder at the TRUE common-mode scale but with no knowledge of the exponent spread (uniform-scale model)
        l0 = mc_levels_drift(g, g, p, sigma, nu, 0.0, ln_tau, z4, gap_hrs=gh)
        lp = mc_levels_drift(g, g, p, sigma, nu, 0.0, ln_tau, z4, gap_hrs=gh, ln_scale=+_DLN)["mean_diff"]
        lm = mc_levels_drift(g, g, p, sigma, nu, 0.0, ln_tau, z4, gap_hrs=gh, ln_scale=-_DLN)["mean_diff"]
        slope = float(np.max(np.abs(lp - lm) / (2 * _DLN)))                 # max_m |dL_m / d ln scale|  (A)
        shift = float(np.max(np.abs(data["mean_diff"] - l0["mean_diff"]))) * gain
        s_ref2 = (sigma ** 2 if ref_mode == "abs" else 0.0) + (sn * ln_tau) ** 2
        eps = np.sqrt(s_ref2 / n_ref)
        ref_term = C.N_SIGMA * eps * slope * gain
        terms.append(Term("reference-cell spread", RANDOM, ref_term))
    else:
        raise ValueError(strategy)
    if shift > 0:
        terms.append(Term("drift", DETERMINISTIC, shift))
    b = close_budget(delta, terms, C.HEADROOM)
    i_cm = 0.5 * float(0.5 * (data["mean_plus"][loc] + data["mean_minus"][loc] + data["mean_plus"][loc - 1] + data["mean_minus"][loc - 1]))
    cmrr = 20 * np.log10(i_cm * gain / (C.CM_ERR_FRACTION * delta))
    return dict(ln_tau=float(ln_tau), delta_a=delta, closes=b.closes, margin_left_frac=b.margin_left_frac_of_limit, total_a=b.total_error_a, limit_a=b.limit_a,
                drift_shift_a=shift, ref_a=ref_term, spread5_a=terms[0].value_a, binding=b.binding, cmrr_db=float(cmrr), breakdown={k: v["value_a"] for k, v in b.breakdown.items()})


def evaluate(g: int, area: int, r_s: float, sigma: float, nu: float, kappa: float, life_years: float, strategy: str, *, n_ref: int = 0, ref_mode: str = "abs",
             refresh_days: float | None = None, ratio: float = C.RATIO_CEILING, extras: dict | None = None, n: int = 600, n_ages: int = 5,
             comp_sigma: float = C.COMP_SIGMA_I_A) -> dict:
    """Worst-over-age budget for one operating point and strategy. Returns ok (closes at EVERY checked age) plus the per-age records."""
    extras = extras or {}
    p = params_for(area, r_s)
    gh = gap_hrs_for_ratio(ratio, p)
    z4 = draw_z4(g, n)
    horizon_years = life_years if strategy != "S2" else refresh_days * 86400.0 / C.SECONDS_PER_YEAR
    lns = ages(horizon_years, n_ages)
    ln_design = float(lns[-1] / 2.0)              # geometric-mean age of [t0, horizon]
    leak, _ = leakage_residual(g, p, ratio, C.RATIO_TOL)
    cache: dict = {}
    recs = [_budget_at_age(g, p, sigma, nu, kappa, float(l), z4, strategy, ln_design, max(n_ref, 1), ref_mode, extras, gh, leak, cache, comp_sigma) for l in lns]
    worst = min(recs, key=lambda r: r["margin_left_frac"])
    return dict(g=g, area=area, r_s=r_s, sigma=sigma, nu=nu, kappa=kappa, life_years=life_years, strategy=strategy, n_ref=n_ref, ref_mode=ref_mode,
                refresh_days=refresh_days, ok=all(r["closes"] for r in recs), worst_margin_frac=worst["margin_left_frac"], worst_age_ln=worst["ln_tau"],
                worst_binding=worst["binding"], cmrr_ok=all(r["cmrr_db"] <= C.CMRR_ACHIEVABLE_DB for r in recs), ages=recs)
