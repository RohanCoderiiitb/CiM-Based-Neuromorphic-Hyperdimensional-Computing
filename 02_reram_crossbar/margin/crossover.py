"""1B Part A: where does device spread overtake the HRS-leakage residual (and compression) as the binding term?

Writes results/margin_budget/spread_leakage_crossover.json. Uses the refined sigma grid (0, 0.01, 0.02, 0.03, 0.05, ...).
Two views:
  (1) per sigma, at the recommended cell: g*, the limiter of the next g, and the budget shares at g* (spread / comparator / HRS residual).
  (2) per g, the sigma at which 5-sigma spread equals the HRS-leakage residual (analytic: spread5 is linear in sigma, residual is independent of it),
      sigma_x(g) = sigma_ref * leak_resid / spread5(sigma_ref); with the linearity of spread5/sigma checked against the fine grid.
"""
from __future__ import annotations

import paths as RP

import json
from pathlib import Path

import device.constants as C
from margin import surface as S

OUT = RP.CROSSOVER_JSON
REC_AREA, REC_RS = 20, 5.0


def main() -> None:
    rows = S.load(); idx = S.index(rows)
    sigmas = sorted({r["sigma"] for r in rows})
    out = {"sigmas": sigmas, "per_sigma": [], "per_g": [], "linearity": [], "all_cells": []}
    for sg in sigmas:
        by = idx[(REC_AREA, REC_RS, sg)]
        gs, lim, mono = S.g_star(by)
        r = by[max(gs, 1)]
        out["per_sigma"].append(dict(sigma=sg, g_star=gs, limiter=lim, delta_a=r["delta_a"], spread5_a=r["spread5_a"], comp5_a=r["comp5_a"],
                                     leak_resid_a=r["leak_resid_a"], limit_a=r["limit_a"], total_err_a=r["total_err_a"]))
    for g in C.G_SWEEP:
        ref = idx[(REC_AREA, REC_RS, 0.05)][g]
        sx = ref["leak_resid_a"] / ref["spread5_a"] * 0.05
        # linearity: spread5/sigma at the fine sigmas vs 0.05
        ratios = {sg: idx[(REC_AREA, REC_RS, sg)][g]["spread5_a"] / sg for sg in sigmas if sg > 0}
        out["per_g"].append(dict(g=g, sigma_x=sx, leak_resid_a=ref["leak_resid_a"], spread5_over_sigma={str(k): v for k, v in ratios.items()}))
    # per (area, R_s): smallest sigma at which the limiter of the next g is 'device spread'
    for area in C.AREA_SWEEP_F2:
        for rs in C.R_S_SWEEP:
            first = None
            for sg in sigmas:
                gs, lim, _ = S.g_star(idx[(area, rs, sg)])
                if lim == "device spread":
                    first = (sg, gs); break
            out["all_cells"].append(dict(area=area, r_s=rs, first_spread_limited_sigma=None if first is None else first[0],
                                         g_star_there=None if first is None else first[1]))
    OUT.write_text(json.dumps(out, indent=1))
    for p in out["per_sigma"]:
        print(p["sigma"], p["g_star"], p["limiter"], round(p["spread5_a"] * 1e6, 2), round(p["leak_resid_a"] * 1e6, 2), round(p["limit_a"] * 1e6, 1))


if __name__ == "__main__":
    main()
