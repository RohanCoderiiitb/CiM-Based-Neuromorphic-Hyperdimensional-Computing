"""F3: for every (OTA bias vb, read pulse T, integration tail) collect what sets the front-end's error and energy, all from the transistor-level runs:
  thermal+flicker noise of the channel integrated over the window T_w = T + tail (sense.mc.noise, device level), referred to the ideal array current through the collected-charge ratio eta (sense.mc.fidelity);
  integrator reset noise + comparator preamplifier noise + latch (sense.comparator: preamp device-level, latch [ASSUM]);
  calibration residual on the real transient (sense.cal.run_transient / sense.run_cal_transient), far group, worst level;
  power-up time of the bias (sense.enable) and supply current (idle + signal), giving energy per column per read.
The combination into the budget and the energy per inference is done in sense.budget_1f (F6) and sense.energy_1f (F3). Usage: python -m sense.pareto"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from sense import comparator as K, mc, port as P
from sense.cal import DESIGN

VBS = (0.42, 0.46, 0.50)
TS = (0.5e-9, 1e-9, 2e-9)
TAILS = (0.3e-9, 1.0e-9)
C_INT = 200e-15
PRE_W = 32e-6


def one(args):
    vb, T, tail = args
    des = dict(DESIGN); des["vb"] = vb
    dz = mc.Design(**des)
    tw = T + tail
    n = mc.noise(dz, windows=(tw,))
    fid = mc.fidelity(dz, T, t_tail=tail)
    eta = float(np.mean([np.mean(v) for v in fid["eta"].values()]))
    sig_thermal_window = n["sigma"][tw]
    # equivalent current noise referred to the ideal array current: charge noise / (signal charge per unit ideal current)
    sig_ref = sig_thermal_window * tw / (eta * T)
    return dict(vb=vb, T=T, tail=tail, eta_mean=eta, step_ratio_min=fid["step_ratio_min"], sigma_window_uA=sig_thermal_window * 1e6, sigma_thermal_ref_uA=sig_ref * 1e6, vn_mV=fid["vn_mV"])


def main() -> None:
    grid = list(itertools.product(VBS, TS, TAILS))
    with Pool(10) as p:
        rows = p.map(one, grid)
    pre = K.preamp(wi=PRE_W, wt=PRE_W)
    cal = {(round(r["design"]["vb"], 3), round(r["T"], 12), round(r["tail"], 12)): r for r in json.loads((RP.SENSE / "calibration_transient.json").read_text())}
    for r in rows:
        key = (round(r["vb"], 3), round(r["T"], 12), round(r["tail"], 12))
        c = cal[key]
        sp = np.array(c["gain_and_offset"]["sigma_by_point_uA"])
        r["cal_sigma_far_uA"] = float(sp[:9].max()); r["cal_sigma_near_uA"] = float(sp[9:].max()); r["cal_rms_uA"] = c["gain_and_offset"]["rms_uA"]; r["raw_rms_uA"] = c["raw_rms_uA"]
        # comparator side at the same T (charge collection time) with the preamplifier of width PRE_W
        s = K.sigma_i(pre["sigma_v_by_window"]["0.3"], pre["a_pre"], C_INT, DESIGN["k"], r["T"])
        r["comparator_uA"] = s["total_uA"]; r["comparator_parts"] = s
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "pareto_raw.json").write_text(json.dumps(dict(c_int=C_INT, preamp_w=PRE_W, preamp=pre, rows=rows), indent=1, default=float))
    for r in rows:
        print(f"vb {r['vb']} T {r['T']*1e9:g} tail {r['tail']*1e9:g}: eta {r['eta_mean']:.2f} thermal(ref) {r['sigma_thermal_ref_uA']:.2f} comp {r['comparator_uA']:.2f} cal far {r['cal_sigma_far_uA']:.2f} near {r['cal_sigma_near_uA']:.2f}")


if __name__ == "__main__":
    main()
