"""Fix 1(e): bound the cost of treating R_tx as a linear resistor. Writes results/device_characterization/linear_vs_bsim4_bound.json.

BOTH sides are ngspice, same nominal gaps, same circuit; the only difference is the access device (linear R_tx vs the
real PTM BSIM4 NMOS). This is a MODELLING difference, kept separate from the Newton-vs-ngspice numerical validation.
Then a best-fit constant R_tx is searched (Newton solver vs BSIM ngspice) to show the floor of the linear approximation.

Usage: python -m validate.linear_vs_bsim
"""
from __future__ import annotations

import paths as RP

import json
from pathlib import Path

import numpy as np

import device.constants as C
from device.constants import DEFAULT
from solver.newton import solve_differential
from spice.runner import run_differential

ROOT = Path(__file__).resolve().parents[1]
GS = (8, 16, 32)


def cases(g: int):
    gp, gm, act, am = [], [], [], []
    for a in range(1, g + 1):
        for m in range(a + 1):
            s = np.arange(g) < m
            gp.append(np.where(s, C.GAP_LRS, C.GAP_HRS)); gm.append(np.where(s, C.GAP_HRS, C.GAP_LRS))
            act.append(np.arange(g) < a); am.append((a, m))
    return np.array(gp), np.array(gm), np.array(act), np.array(am)


def steps_a_eq_g(i, am, g):
    """Per-step increments of a current vector over m at a = g."""
    sel = am[:, 0] == g
    return np.diff(i[sel])


def main() -> None:
    p = DEFAULT
    out = {"r_tx_linear": p.r_tx, "per_g": {}}
    for g in GS:
        gp, gm, act, am = cases(g)
        lp, lm, ld = run_differential(gp, gm, act, p, tx="linear")
        bp, bm, bd = run_differential(gp, gm, act, p, tx="bsim")
        scale = np.maximum(np.abs(bp), np.abs(bm))
        # single-column steps (+ column) and differential steps, a = g
        d_single_l, d_single_b = steps_a_eq_g(lp, am, g), steps_a_eq_g(bp, am, g)
        d_diff_l, d_diff_b = steps_a_eq_g(ld, am, g), steps_a_eq_g(bd, am, g)
        # best constant R_tx: minimise worst |step_newton/step_bsim - 1| over both gap types (Newton, linear model)
        best = None
        for rt in np.arange(300.0, 700.0, 2.0):
            nw = solve_differential(gp, gm, act, p, r_tx=rt)
            ss = steps_a_eq_g(nw.i_plus, am, g); sd = steps_a_eq_g(nw.i_diff, am, g)
            err = max(np.max(np.abs(ss / d_single_b - 1)), np.max(np.abs(sd / d_diff_b - 1)))
            if best is None or err < best[1]:
                best = (float(rt), float(err))
        out["per_g"][g] = dict(
            n_cases=len(am),
            worst_rel_single_step=float(np.max(np.abs(d_single_l / d_single_b - 1))),
            worst_rel_diff_step=float(np.max(np.abs(d_diff_l / d_diff_b - 1))),
            worst_rel_idiff_scale=float(np.max(np.abs(ld - bd) / scale)),
            worst_rel_iplus=float(np.max(np.abs(lp / bp - 1))),
            worst_rel_iminus=float(np.max(np.abs(lm / bm - 1))),
            # bsim vs linear step difference at the single-column worst point m = g
            single_step_at_m_eq_g_lin=float(d_single_l[-1]), single_step_at_m_eq_g_bsim=float(d_single_b[-1]),
            best_const_rtx=best[0], best_const_rtx_worst_step_err=best[1])
        print(g, {k: (round(v, 5) if isinstance(v, float) else v) for k, v in out["per_g"][g].items()})
    RP.LINEAR_VS_BSIM_JSON.write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
