"""Re-close the 1B margin budget at the 1C operating point with the terms 1C measures.

Uses the 1B machinery unchanged (drift.strategies.evaluate -> solver.budget.close_budget): the far group (worst step, behind r*(512-g+1) ohm of bitline) and the near group
are both evaluated at the recommended point (20 F^2, R_s = 1 ohm, sigma_lnG = 0.10, r = 0.72 ohm/pitch, drift 'moderate', strategy S1, g = 8) and the least margin is returned.
Inputs that 1C re-measures: the row-line gain and the data-dependent row-line spread of the TRUE macro (64 bitlines), plus extra terms (supply/ground rail, crosstalk, ladder
quantisation, antisymmetric storage) in absolute uA. 'random' terms are combined in quadrature at 5 sigma by the caller (the value passed is already 5 sigma); 'deterministic'
terms add linearly.
"""
from __future__ import annotations

import json

import device.constants as C
import paths as RP
from drift.strategies import evaluate
from solver.budget import DETERMINISTIC, RANDOM

_TERMS = None


def wire_terms(g: int = C.G_1C, area: int = C.AREA_1C, r_s: float = C.RS_1C, r: float = 0.72) -> dict:
    global _TERMS
    if _TERMS is None:
        _TERMS = {(t["g"], t["area"], t["r_s"], t["r"]): t for t in json.loads(RP.WIRE_TERMS_JSON.read_text())}
    return _TERMS[(g, area, r_s, r)]


def close_1c(row: dict, extra_terms: dict | None = None, *, g: int = C.G_1C, area: int = C.AREA_1C, r_s: float = C.RS_1C, sigma: float = 0.10, r: float = 0.72,
             scenario: str = "moderate", n: int = 500, comp_sigma: float = C.COMP_SIGMA_I_A) -> dict:
    """row = {'far': {'gain', 'row_std_a'}, 'near': {...}} measured at the macro in question; extra_terms = {'far': [(name, kind, value_a)], 'near': [...]} or None.
    Returns the budget at the worst of the two groups."""
    nu, kappa = C.DRIFT_SCENARIOS[scenario]
    t = wire_terms(g, area, r_s, r)
    out = {}
    for which in ("far", "near"):
        r_eff = r_s + (r * (C.ROWS_TOTAL - g + 1.0) if which == "far" else r * 1.0)
        ex = dict(wire_within_a=t[f"within_{which}_a"], row5_a=C.N_SIGMA * row[which]["row_std_a"], gain=row[which]["gain"])
        if extra_terms and extra_terms.get(which):
            ex["extra_terms"] = tuple(extra_terms[which])
        ev = evaluate(g, area, r_eff, sigma, nu, kappa, 10.0, "S1", extras=ex, n=n, n_ages=3, comp_sigma=comp_sigma)
        w = min(ev["ages"], key=lambda a: a["margin_left_frac"])
        out[which] = dict(margin_frac=w["margin_left_frac"], margin_left_a=w["limit_a"] - w["total_a"], limit_a=w["limit_a"], total_a=w["total_a"], delta_a=w["delta_a"],
                          binding=w["binding"], closes=bool(ev["ok"]), breakdown=w["breakdown"], r_eff=r_eff)
    worst = min(out, key=lambda k: out[k]["margin_frac"])
    return dict(worst_group=worst, margin_frac=out[worst]["margin_frac"], margin_left_a=out[worst]["margin_left_a"], limit_a=out[worst]["limit_a"], total_a=out[worst]["total_a"],
                closes=all(o["closes"] for o in out.values()), groups=out)
