"""F6: the 1C margin budget re-closed with the terms 1F measured (replacing the ASSUMED 1 uA comparator noise) and the g surface.

Machinery unchanged (drift.strategies.evaluate via scaleup.budget1c.close_1c, S1, drift 'moderate', 20 F^2, R_s 1 ohm, 5 sigma on random terms, 20% headroom). Inputs:
  rows        : at g = 8 exactly the 1C baseline (scaleup.c2_budget.design_budget: row-line gain and spread of the true macro with rails, both-end drivers, R_DRV 10) and its 1C extra terms
                (rail, settling, ladder quantisation, antisymmetric half table, rank-3 gain residual); at other g the row-line gain/spread/wire terms of the end-sensed variant (scaleup/variants.group_terms,
                ideal rails) and the SAME 1C extra terms (they are small, 0.4 uA at the far group; not re-derived per g) [MODEL]
  1F terms    : the comparator-noise slot is zero and replaced by explicit terms:
                  'front-end noise' (random)       sqrt(thermal^2 + comparator^2) from sense.pareto [SIM + latch ASSUM], referred to the ideal array current
                  'calibration residual' (random)  per column, worst level of the far / near group, measured on the real read transient [SIM]
                  'calibration drift' (random)     0.05 uA/K x dT between calibration and read [SIM slope, dT is a parameter]
                  'threshold generation' (random)  sigma_rel x |threshold| per group [ASSUM sigma_rel]
  droop       : mean rail droop during the pulse scales the read bias: gain x (1 - droop/V_READ).
Usage: python -m sense.budget_1f"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

import device.constants as C
import paths as RP
from scaleup import c2_budget as B
from scaleup.budget1c import close_1c
from solver.budget import DETERMINISTIC, RANDOM

DRIFT_UA_PER_K = 0.05          # [SIM] sense.run_drift_sources: worst-point sigma 1.0 uA at +20 K, 1.9 uA at +40 K (static two-parameter calibration at 27 C)
THR_SIGMA_REL = 0.0015         # [ASSUM] relative accuracy (1 sigma) of a threshold generated per column after calibration, referred to the array current
THR_MAG_A = {"far": 115e-6, "near": 300e-6}      # [MODEL] largest threshold magnitude per group = half the level span of 1C's group tables (far 351/2 ~ 175 uA at a = 8 incl. common-level; thresholds at the extreme levels)
N_SIG = C.N_SIGMA


@lru_cache(maxsize=None)
def base8() -> tuple:
    """1C baseline at g = 8: rows (gain, row_std per group) and the extra terms per group, exactly as c2_budget.design_budget builds them."""
    from scaleup.droop import macro_stats
    ts = json.loads((RP.FULL_COLUMN / "ladder_table_size.json").read_text())["0.72"]
    rows, extra = {}, {}
    for which, G in (("far", 63), ("near", 0)):
        ms = [macro_stats(G, 8, v, n_cells=32, n_own=8, n_other=40, r_drv=10.0, r_wl=0.72, drive_both_ends=True, r_rail=C.RAIL_R_DEFAULT, r_gnd=C.RAIL_R_DEFAULT, feed_both=True) for v in (0, 15, 31)]
        rows[which] = dict(gain=min(m["gain_total"] for m in ms), row_std_a=max(m["row_std_a"] for m in ms))
        t = [("supply/ground rail (data dependent)", DETERMINISTIC, max(m["rail_inc_maxdev_a"] for m in ms)), ("settling + crosstalk at sampling time", DETERMINISTIC, B._dyn(G, C.CC_FRACTION_DEFAULT, 200.0)),
             ("ladder threshold quantisation", DETERMINISTIC, B.Q_LSB_A / 2), ("antisymmetric (half) table storage", DETERMINISTIC, 0.5e-6 * (ts["antisym_dev_far_uA"] if which == "far" else ts["antisym_dev_near_uA"])),
             (f"row-gain correction residual (rank {B.GAIN_RANK})", DETERMINISTIC, B.gain_residual_a(which, True))]
        extra[which] = t
    return rows, extra


@lru_cache(maxsize=None)
def rows_other(g: int) -> dict:
    t = json.loads((RP.READOUT_VARIANTS / "group_terms.json").read_text())
    return {w: dict(gain=t[f"end|{g}|{w}|0.72"]["gain"], row_std_a=t[f"end|{g}|{w}|0.72"]["row_std_a"]) for w in ("far", "near")}


def fe_terms(sig_noise_a: dict, sig_cal_a: dict, d_t_k: float = 5.0, thr_rel: float = THR_SIGMA_REL, sig_extra_a: dict | None = None) -> dict:
    """1F terms per group as budget lines (absolute amps, random terms already at N_SIGMA sigma)."""
    out = {}
    for w in ("far", "near"):
        t = [("front-end noise (thermal + comparator + reset)", RANDOM, N_SIG * sig_noise_a[w]), ("per-column calibration residual", RANDOM, N_SIG * sig_cal_a[w]),
             ("calibration drift with temperature", RANDOM, N_SIG * DRIFT_UA_PER_K * 1e-6 * d_t_k), ("threshold generation (per column)", RANDOM, N_SIG * thr_rel * THR_MAG_A[w])]
        if sig_extra_a and sig_extra_a.get(w):
            t.append(("other front-end random", RANDOM, N_SIG * sig_extra_a[w]))
        out[w] = t
    return out


def closure(g: int, sigma_lng: float, terms_1f: dict | None, gain_factor: float = 1.0, comp_sigma_a: float = 0.0, n: int = 400) -> dict:
    """Budget at the far and near group. terms_1f = fe_terms(...) or None (with comp_sigma_a the 1C assumed noise)."""
    rows8, extra8 = base8()
    rows = rows8 if g == 8 else rows_other(g)
    rows = {w: dict(gain=rows[w]["gain"] * gain_factor, row_std_a=rows[w]["row_std_a"]) for w in rows}
    extra = {w: list(extra8[w]) + (list(terms_1f[w]) if terms_1f else []) for w in ("far", "near")}
    return close_1c(rows, extra, g=g, sigma=sigma_lng, comp_sigma=comp_sigma_a, n=n)


def closure_variant(variant: str, g: int, sigma_lng: float, terms_1f: dict | None, gain_factor: float = 1.0, n: int = 1000, r: float = 0.72) -> dict:
    """Same budget for a C4 readout variant (centre-tapped / segmented column): far and near group terms from scaleup/variants.group_terms (mesh-measured at the true positions), the 1C extra terms of the
    g = 8 baseline and the 1F terms added; r_eff = R_s + r x (distance of the nearest row of the group from its sense node)."""
    from drift.strategies import evaluate
    t = json.loads((RP.READOUT_VARIANTS / "group_terms.json").read_text())
    nu, kappa = C.DRIFT_SCENARIOS["moderate"]
    _, extra8 = base8()
    out = {}
    for w in ("far", "near"):
        tt = t[f"{variant}|{g}|{w}|{r}"]
        ex = dict(wire_within_a=tt["within_a"], row5_a=N_SIG * tt["row_std_a"], gain=tt["gain"] * gain_factor, extra_terms=tuple(list(extra8[w]) + (list(terms_1f[w]) if terms_1f else [])))
        ev = evaluate(g, C.AREA_1C, C.RS_1C + r * tt["pos0"], sigma_lng, nu, kappa, 10.0, "S1", extras=ex, n=n, n_ages=3, comp_sigma=0.0)
        wst = min(ev["ages"], key=lambda a: a["margin_left_frac"])
        out[w] = dict(margin_left_a=wst["limit_a"] - wst["total_a"], closes=bool(ev["ok"]), cmrr_ok=bool(ev["cmrr_ok"]), limit_a=wst["limit_a"], total_a=wst["total_a"], breakdown=wst["breakdown"])
    worst = min(out, key=lambda k: out[k]["margin_left_a"])
    return dict(worst_group=worst, margin_left_a=out[worst]["margin_left_a"], closes=all(o["closes"] for o in out.values()), groups=out)


def allowed_sigma(g: int, sigma_lng: float, extra_fixed: dict | None = None, gain_factor: float = 1.0) -> float:
    """Largest single front-end 1-sigma (uA) the budget tolerates at the FAR group (everything else at 1C values): bisection on the comparator-noise slot."""
    lo, hi = 0.0, 10.0
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        b = closure(g, sigma_lng, extra_fixed, gain_factor, comp_sigma_a=mid * 1e-6, n=200)
        ok = b["groups"]["far"]["margin_left_a"] > 0 and b["groups"]["near"]["margin_left_a"] > 0 and b["groups"]["far"]["closes"] and b["groups"]["near"]["closes"]
        lo, hi = (mid, hi) if ok else (lo, mid)
    return lo


def required_cmrr(n: int = 300) -> dict:
    """The common-mode rejection the 1B budget requires (common-mode error held to 10% of a step; drift.strategies cmrr_db) per group size and group, uA-level inputs from the 1C group terms."""
    from drift.strategies import evaluate
    t = json.loads((RP.READOUT_VARIANTS / "group_terms.json").read_text())
    nu, kappa = C.DRIFT_SCENARIOS["moderate"]
    out = {}
    for g in (4, 8, 16):
        for w in ("far", "near"):
            tt = t[f"end|{g}|{w}|0.72"]
            ex = dict(wire_within_a=tt["within_a"], row5_a=N_SIG * tt["row_std_a"], gain=tt["gain"])
            ev = evaluate(g, C.AREA_1C, C.RS_1C + 0.72 * tt["pos0"], 0.10, nu, kappa, 10.0, "S1", extras=ex, n=n, n_ages=3, comp_sigma=1e-6)
            out[f"{g}|{w}"] = float(max(a["cmrr_db"] for a in ev["ages"]))
    return out


def main() -> None:
    out = {}
    # check: reproduces 1C baseline with its assumed 1 uA
    b = closure(8, 0.10, None, comp_sigma_a=1e-6, n=500)
    out["check_1c_baseline"] = dict(margin_left_a=b["margin_left_a"], limit_a=b["limit_a"], total_a=b["total_a"], worst=b["worst_group"])
    print("1C baseline reproduced: margin %.3f uA (1C report 0.48), limit %.2f total %.2f, worst %s" % (b["margin_left_a"] * 1e6, b["limit_a"] * 1e6, b["total_a"] * 1e6, b["worst_group"]))
    out["required_cmrr_db"] = required_cmrr()
    print("required CMRR (dB):", out["required_cmrr_db"])
    out["allowed_sigma_uA"] = {}
    for g in (4, 8, 16):
        for s in (0.03, 0.05, 0.07, 0.10, 0.15):
            a = allowed_sigma(g, s)
            out["allowed_sigma_uA"][f"{g}|{s}"] = a
            print(f"g={g} sigma_lnG={s}: allowed single front-end sigma (far or near, all else at 1C) = {a:.2f} uA", flush=True)
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "budget_allowed_sigma.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
