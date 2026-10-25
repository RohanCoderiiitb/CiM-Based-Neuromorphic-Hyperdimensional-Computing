"""Optimisation item 10: THE OPERATING POINT. The analog macro (0.583 mm^2 = 1.46x NeuroHDC's whole chip) is fixed by the 128 F select transistor that a 541.8 ohm LRS needs. At a higher LRS (1D: 38-70 kohm
is writable) the select transistor shrinks to the minimum cell (NeuroSim accepts 20 F^2 at Ron = 40 kohm), the read current falls ~25x, the supply decoupling collapses with it - but the signal falls with it.
Evaluated, not assumed: for each LRS the existing machinery gives
   device:     gap for the LRS, branch resistances (20 F^2 access transistor 1016 ohm), nominal level spacing at g = 4, population-mean levels and spread (margin.core.mc_levels) -> the largest
               sigma_lnG at which 5 sigma of the spread stays inside half a level spacing (spread only; the other budget terms come on top);
   mesh:       the row-line gain spread of the macro (scaleup.droop.macro_stats, g = 4, driver 10 ohm, 0.72 ohm/pitch) -> does a threshold correction survive at all;
   front-end:  the 1F conveyor front-end (sense.mc, ngspice) with this array behind it: input-referred noise vs integration window T up to 64 ns, collected step ratio;
   energy:     the 1F energy model with the window T that makes 5 sigma of the front-end noise <= 1/4 of the (collected) step, bias vb chosen for least energy; no threshold correction when the gain is flat;
   area/PDN:   NeuroSim 20 F^2 macro + 1F parts, decoupling scaled with the supply current at equal droop.
Usage: python -m scaleup.op_point [--ron 541.8 5000 40000 70000]"""
from __future__ import annotations

import paths as RP

import argparse
import json
from math import sqrt

import numpy as np

import device.constants as C
import device.model as DM
from margin import core as MC
from scaleup import droop as DR
from sense import energy_1f as E1
from sense import mc, port as P
from sense.cal import DESIGN
from sense.enable import power_up

R_TX = C.RTX_BY_AREA[20]
GAP_HRS = 1.55          # nm, 1D's design-adjacent HRS (120 kohm); 1.7 nm (218.6 kohm) is the model's clamp
V = 1.1


def gap_for(r_lrs: float) -> float:
    lo, hi = 0.2, 1.7
    for _ in range(80):
        mid = (lo + hi) / 2
        if float(DM.device_resistance(mid)) < r_lrs:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def params(r_lrs: float, gap_hrs: float):
    return MC.params_for(20, 1.0).with_(gap_lrs=gap_for(r_lrs), gap_hrs=gap_hrs)


def spread(r_lrs: float, gap_hrs: float, g: int = 4, n: int = 400) -> dict:
    p = params(r_lrs, gap_hrs)
    lv = MC.levels(g, g, p)
    step = float(np.min(np.abs(np.diff(lv["i_diff"]))))
    z = MC.draw_z(g, n)
    out = dict(gap_lrs_nm=p.gap_lrs, r_lrs_ohm=float(DM.device_resistance(p.gap_lrs)), step_uA=step * 1e6, i_lrs_branch_uA=C.V_READ / (R_TX + float(DM.device_resistance(p.gap_lrs))) * 1e6, closes_at={})
    for sg in (0.03, 0.05, 0.10, 0.15):
        mcl = MC.mc_levels(g, g, p, sg, z, gap_hrs=gap_hrs)
        mean, sd = mcl["mean_diff"], mcl["std_diff"]
        sp = np.abs(np.diff(mean))
        marg = sp / 2 - 5 * np.maximum(sd[1:], sd[:-1])
        out["closes_at"][str(sg)] = dict(min_margin_uA=float(marg.min() * 1e6), ok=bool(marg.min() > 0), spread_5sigma_over_half_step=float((5 * np.maximum(sd[1:], sd[:-1]) / (sp / 2)).max()))
    return out


def gain_flatness(r_lrs: float, gap_hrs: float, g: int = 4) -> dict:
    p = params(r_lrs, gap_hrs)
    DR.params_for = lambda area, r_s: p                                  # the mesh solver reads its device from here
    gains = []
    for G in (0, 40, 80, 127):
        for c in (0, 8, 16, 31):
            for a in (1, 2, 4):
                s = DR.macro_stats(G, a, c, n_own=1, n_other=10, r_drv=10.0, r_wl=0.72, drive_both_ends=True, own_all_match=True, g=g, seed=C.WIRE_SEED + 5)
                gains.append(s["gain_row"])
    gains = np.array(gains)
    return dict(gain_min=float(gains.min()), gain_max=float(gains.max()), spread_frac=float(gains.max() - gains.min()))


def frontend(r_lrs: float, gap_hrs: float) -> dict:
    """1F front-end noise vs window and the collected step ratio with this array (port.py's branch resistances patched)."""
    P.R_LRS_BR = R_TX + float(DM.device_resistance(gap_for(r_lrs)))
    P.R_HRS_BR = R_TX + float(DM.device_resistance(gap_hrs))
    out = {}
    for vb in (0.42, 0.46, 0.50, 0.54, 0.58):
        des = dict(DESIGN); des["vb"] = vb
        dz = mc.Design(**des)
        n = mc.noise(dz, windows=tuple(t * 1e-9 for t in (0.5, 1, 2, 4, 8, 16, 32, 64)))
        fid = {f"{T:g}": mc.fidelity(dz, T * 1e-9) for T in (1, 4)}
        pu = power_up(dz, t_end=12e-9)
        out[str(vb)] = dict(sigma_uA={f"{t:g}": v * 1e6 for t, v in ((k * 1e9, s) for k, s in n["sigma"].items())}, eta={k: v["step_ratio_min"] for k, v in fid.items()},
                            i_idle_uA=pu["i_final_uA"], t_en_ns=pu["t_settle_ns"], i_bias_uA=mc.bias_current(dz)["i_vdd_a"] * 1e6)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ron", type=float, nargs="*", default=[541.8, 5000.0, 20000.0, 40000.0, 70000.0])
    ap.add_argument("--hrs", type=float, default=GAP_HRS)
    a = ap.parse_args()
    res = {}
    for ron in a.ron:
        r = dict(ron=ron)
        r["levels"] = spread(ron, a.hrs)
        r["row_gain"] = gain_flatness(ron, a.hrs)
        r["frontend"] = frontend(ron, a.hrs)
        res[str(ron)] = r
        print(ron, json.dumps(r["levels"])[:400], r["row_gain"], flush=True)
    (RP.MACRO / "operating_point.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
