"""C2(a)/C3(b), the dynamic half of the supply model: the read pulse through a supply network with series resistance, package inductance and on-chip decoupling.

Source (regulator, ideal DC at V_read) -> R_pad (0.5 ohm) -> L_pad (100 pH) -> rail pad -> the vertical rail (0.0072 ohm/pitch, second pad at the far end) -> row drivers, with C_dec distributed over the
active rows' supply taps, PRE-CHARGED to V_read; the pulse is the row drivers closing in 20 ps (the current step the decoupling must absorb). R_pad, L_pad and C_dec are [ASSUM] (1B/1C have no PDN data); the point is the trend: how much decoupling the read pulse needs, what an under-decoupled supply
does to the settling time, and whether it makes the settled error data-dependent. One macro (64 bitlines, both-end row drive), a = 8, groups 0 and 63, 4 random weight patterns.
Metrics: minimum rail voltage at the active rows, I_diff error at the sampling times relative to its final value, its spread over the patterns, and the settling time to 0.1 uA.
Usage: python -m scaleup.run_supply_dynamics"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.transient import TranConfig, build_tran_deck, currents, energy_to, run_tran

K = C.MACRO_BITLINES
T_S = np.array([100, 150, 200, 300, 500, 1000, 1500]) * 1e-12
CDEC_TOTAL_F = (0.0, 10e-12, 100e-12, 1e-9)


def job(cfg):
    G, cdec, pat = cfg
    p = params_for(C.AREA_1C, C.RS_1C)
    rng = np.random.default_rng([C.WIRE_SEED, G, pat, 55])
    rows = np.arange(8 * G, 8 * G + 8)
    W = rng.random((8, K // 2)) < 0.5
    W[:, 15] = np.random.default_rng([C.WIRE_SEED, G, 999]).random(8) < 0.5
    gaps = np.where(np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1), p.gap_lrs, p.gap_hrs)
    c = TranConfig(t_stop=1.6e-9, r_rail=C.RAIL_R_DEFAULT, rail_length=C.ROWS_TOTAL + 1.0, c_dec=cdec / 8, r_pad=0.5, l_pad=100e-12, switched_driver=True)
    res = run_tran(build_tran_deck(gaps, rows + 1.0, p, c, C.RS_1C), K)
    i = currents(res, np.ones(K)); d = i[:, 30] - i[:, 31]; dall = i[:, 0::2] - i[:, 1::2]
    err_all = np.abs(dall - dall[-1][None, :]).max(axis=1)
    idx = np.flatnonzero(err_all > 0.1e-6)
    return dict(G=G, cdec_total_F=cdec, pat=pat, v_rail_min_V=float(res["v_rail"][res["t"] > 30e-12].min()), v_rail_final_V=float(res["v_rail"][-1].mean()),
                v_rail_peak_V=float(res["v_rail"].max()), err_a=(np.interp(T_S, res["t"], d) - d[-1]).tolist(), settle_s=float(res["t"][idx[-1]]) if len(idx) else 0.0, i_final_A=float(res["i_sup"][-1]))


def main() -> None:
    cfgs = list(product((0, 63), CDEC_TOTAL_F, range(4)))
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, cfgs, chunksize=1))
    (RP.TRANSIENT / "supply_dynamics_raw.json").write_text(json.dumps(dict(t_s=T_S.tolist(), runs=res)))
    for G, cd in product((0, 63), CDEC_TOTAL_F):
        rr = [r for r in res if r["G"] == G and r["cdec_total_F"] == cd]
        e = np.array([r["err_a"] for r in rr])
        print(f"G={G} C_dec={cd*1e12:6.0f} pF: rail min {min(r['v_rail_min_V'] for r in rr)*1e3:.1f} mV (final {np.mean([r['v_rail_final_V'] for r in rr])*1e3:.1f}), settle {max(r['settle_s'] for r in rr)*1e12:.0f} ps, "
              f"|err| at {', '.join(str(int(t*1e12)) for t in T_S)} ps: " + " ".join(f"{v*1e6:.2f}" for v in np.abs(e).max(0)) + " | spread: " + " ".join(f"{v*1e6:.3f}" for v in np.abs(e - e.mean(0)).max(0)), flush=True)


if __name__ == "__main__":
    main()
