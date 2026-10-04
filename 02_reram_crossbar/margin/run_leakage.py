"""1B-i step 4: HRS leakage vs on/off ratio, correctable fraction, residual and crossover. Writes results/margin_budget/hrs_leakage_vs_ratio.json.

Reference R_s for the ratio sweeps is R_REF (leakage is nearly insensitive to R_s; spot check included).
"""
from __future__ import annotations

import paths as RP

import json
from pathlib import Path

import device.constants as C
from margin import leakage as LK
from margin.core import gap_hrs_for_ratio, levels, params_for

OUT = RP.HRS_LEAKAGE_JSON
R_REF = 10.0                     # ohm [CHOICE] mid of the R_s sweep, for the ratio sweeps
DESIGN_RATIOS = (403.4, 270.4, 181.3)   # [CHOICE] ladder design ratios: ceiling, mid, realistic (1A section 4 mapping)
GS = (4, 8, 16, 32, 64, 128)


def main() -> None:
    out = {"r_ref": R_REF, "counts": [], "rs_check": [], "windows": [], "absorb": []}
    for area in C.AREA_SWEEP_F2:
        for g in GS:
            for r in C.RATIO_SWEEP:
                out["counts"].append(dict(area=area, g=g, ratio=r, counts=LK.leak_counts(g, r, area, R_REF),
                                          rule_of_thumb=g / r))
    for rs in C.R_S_SWEEP:
        out["rs_check"].append(dict(r_s=rs, counts=LK.leak_counts(32, C.RATIO_CEILING, 40, rs)))
    for area in C.AREA_SWEEP_F2:
        for g in GS:
            for rd in DESIGN_RATIOS:
                lo, hi = LK.window(g, area, R_REF, rd)
                d, lim = LK.usable_budget(g, area, R_REF, rd)
                out["windows"].append(dict(area=area, g=g, ratio_design=rd, r_lo=lo, r_hi=hi, delta_a=d, limit_a=lim,
                                           share_a=C.LEAK_BUDGET_SHARE * lim))
    # correctable fraction: an uncorrected ladder (designed on levels WITHOUT leakage) vs a ladder designed at the actual design ratio, tol applied
    for area in C.AREA_SWEEP_F2:
        for g in GS:
            p = params_for(area, R_REF)
            ideal = levels(g, g, p, gap_hrs=C.GAP_NO_HRS)["i_diff"]
            d_lvl = LK.usable_budget(g, area, R_REF, C.RATIO_CEILING)[0]
            for rd in DESIGN_RATIOS:
                ld = levels(g, g, p, gap_hrs=gap_hrs_for_ratio(rd, p))["i_diff"]
                raw = float(abs(ld - ideal).max())
                resid = max(LK.level_shift(g, area, R_REF, max(rd * (1 - C.RATIO_TOL), 20.0), rd),
                            LK.level_shift(g, area, R_REF, min(rd * (1 + C.RATIO_TOL), C.RATIO_CEILING), rd))
                out["absorb"].append(dict(area=area, g=g, ratio_design=rd, raw_shift_a=raw, raw_over_delta=raw / d_lvl,
                                          residual_a=resid, residual_over_delta=resid / d_lvl,
                                          absorbed_fraction=1 - resid / raw if raw > 0 else 1.0))
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
