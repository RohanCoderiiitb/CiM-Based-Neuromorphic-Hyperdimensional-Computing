"""Operating-point SWEEP (second optimisation pass, S1): for each LRS value the whole analog chain, every point with its OWN select transistor.

The two-point study (`op_point.py`) gave every point the 20 F^2 transistor's 1016 ohm, while the chip-level 541.8 ohm macro is built with a 128 F cell. Here the cell follows the point:

  select transistor   the SET compliance current needed for an LRS state is the device's current at the SET voltage, which in this device model scales exactly with the state's conductance
                      (I(V, gap(R)) x R is the same function of V for every R: checked in `check_scaling`). The 1D write path fixes 128 F at 541.8 ohm, so   w_F = max(5, 128 x 541.8 / R)
                      (5 F is the minimum cell, 5 F x 4 F = 20 F^2; cells are 4 F high).  1A's width rule W = 0.6 x area x F gives the width, and R_tx x W = const (RTX_BY_AREA) the resistance.
  levels              population-mean levels and spread (margin.core) with that transistor and that LRS: the step, and the largest sigma_lnG at which 5 sigma stays inside half a step.
  row line            r_wl = 0.1189 ohm/um (PDK Metal9 at its 0.18 um minimum width, the strap item 7 assumed) x the cell width; both-end drivers 10 ohm; gain matrix over the same (group, cell, active rows)
                      grid as `run_rowline_metal.py`; rank-0..3 residuals; the budget a row-gain error may use scales with what the device spread leaves of the half step.
  front-end           the 1F conveyor front-end in ngspice with this array behind it (branch resistance = R_tx + R_device): input noise vs window, collected step ratio, idle current, power-up.
  energy              item 8 (boosted wake-up, 40 shared channels) and item 9 (per-plane relaxation of the noise requirement) applied at every point on the same footing: for each weight plane the
                      cheapest (vb, T) with (sigma / (eta step))^2 <= f_k x (the 541.8 ohm chain's own value at vb 0.5 V, T = 1 ns); T on a grid up to 64 ns.  Array + word line scaled with
                      the branch current x T and the transistor width; comparators and threshold correction as in `sense.energy_opt`.
  supply current      peak read current of one read = 160 channels x (front-end idle + signal) + array, for the decoupling estimate.
Usage: python -m scaleup.op_sweep [--procs 6] [--ron 541.8 1000 ...]"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from math import ceil, erfc, sqrt

import numpy as np

import device.constants as C
import device.model as DM
from margin import core as MC
from scaleup import droop as DR
from sense import energy_1f as E1
from sense import energy_opt as EO
from sense import mc, port as P
from sense.cal import DESIGN
from sense.enable import power_up

GAP_HRS = 1.55
RS_DEFAULT = (541.8, 1000.0, 1500.0, 2000.0, 3000.0, 5000.0, 7500.0, 10000.0, 15000.0, 20000.0, 30000.0, 40000.0)
F_UM = 0.045
TX_FILL = C.TX_FILL
RW_UM = 0.0214 / 0.18                         # ohm per um of row line: PDK Metal9, 0.18 um wide (item 7's strap)
GROUPS = tuple(range(0, 128, 8)) + (127,)
CELLS = tuple(range(0, 32, 2)) + (31,)
A_VALUES = (1, 2, 3, 4)
SIGMAS = (0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15)
TS_NS = (0.5, 1, 2, 4, 8, 16, 32, 64)
V = 1.1
TAIL = 0.3e-9
SHARED = 0.25
N_COL = 160
RTXW = C.RTX_BY_AREA[20] * (TX_FILL * 20 * C.FEATURE_NM * 1e-3)          # ohm x um, 1A

def gap_for(r_lrs: float) -> float:
    lo, hi = 0.2, 1.7
    for _ in range(80):
        mid = (lo + hi) / 2
        if float(DM.device_resistance(mid)) < r_lrs:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cell_for(r_lrs: float) -> dict:
    w_f = max(5.0, 128.0 * 541.8 / r_lrs)
    area = 4.0 * w_f
    w_um = TX_FILL * area * C.FEATURE_NM * 1e-3
    return dict(w_F=w_f, h_F=4.0, area_F2=area, tx_w_um=w_um, r_tx=RTXW / w_um, cell_w_um=w_f * F_UM, ns_read_min_w_F=39.8 * 541.8 / r_lrs)


def params(r_lrs: float, cell: dict):
    return MC.params_for(20, 1.0).with_(gap_lrs=gap_for(r_lrs), gap_hrs=GAP_HRS, r_tx=cell["r_tx"], tx_w_um=cell["tx_w_um"])


def check_scaling() -> float:
    g0 = gap_for(541.8)
    worst = 0.0
    for R in RS_DEFAULT:
        g = gap_for(R)
        for v in (0.2, 0.5, 0.8):
            worst = max(worst, abs(float(DM.device_current(v, g0)) / float(DM.device_current(v, g)) / (R / 541.8) - 1))
    return worst


def levels_and_sigma(p, g: int = 4, n: int = 400) -> dict:
    lv = MC.levels(g, g, p)
    step = float(np.min(np.abs(np.diff(lv["i_diff"]))))
    z = MC.draw_z(g, n)
    out = dict(step_uA=step * 1e6, i_lrs_branch_uA=C.V_READ / (p.r_tx + float(DM.device_resistance(p.gap_lrs))) * 1e6, full_scale_uA=float(np.abs(lv["i_diff"]).max() * 1e6), closes_at={})
    for sg in SIGMAS:
        mcl = MC.mc_levels(g, g, p, sg, z, gap_hrs=p.gap_hrs)
        mean, sd = mcl["mean_diff"], mcl["std_diff"]
        sp = np.abs(np.diff(mean))
        s5 = float((5 * np.maximum(sd[1:], sd[:-1]) / (sp / 2)).max())
        out["closes_at"][str(sg)] = dict(ok=bool(s5 < 1.0), spread_5sigma_over_half_step=s5, min_margin_uA=float((sp / 2 - 5 * np.maximum(sd[1:], sd[:-1])).min() * 1e6))
    ok = [sg for sg in SIGMAS if out["closes_at"][str(sg)]["ok"]]
    out["sigma_lnG_limit"] = max(ok) if ok else 0.0
    return out


def gain_job(args):
    p, rwl, G, c, a = args
    DR.params_for = lambda area, r_s: p
    s = DR.macro_stats(G, a, c, n_own=1, n_other=16, r_drv=10.0, r_wl=rwl, drive_both_ends=True, own_all_match=True, g=4, seed=C.WIRE_SEED + 5)
    return G, c, a, s["gain_row"]


def rowline(p, cell: dict, ex=None) -> dict:
    rwl = RW_UM * cell["cell_w_um"]
    jobs = [(p, rwl, G, c, a) for G in GROUPS for c in CELLS for a in A_VALUES]
    res = list(ex.map(gain_job, jobs, chunksize=16)) if ex else [gain_job(j) for j in jobs]
    Sa = np.zeros((len(CELLS), len(GROUPS) * len(A_VALUES)))
    for G, c, a, gr in res:
        Sa[CELLS.index(c), GROUPS.index(G) * len(A_VALUES) + A_VALUES.index(a)] = gr
    U, sv, Vt = np.linalg.svd(Sa, full_matrices=False)
    out = dict(r_wl_ohm_per_cell=rwl, gain_min=float(Sa.min()), gain_max=float(Sa.max()), spread_frac=float(Sa.max() - Sa.min()), resid_rank0=float(np.abs(Sa.mean(axis=1, keepdims=True) - Sa).max()))
    for k in (1, 2, 3):
        out[f"resid_rank{k}"] = float(np.abs((U[:, :k] * sv[:k]) @ Vt[:k] - Sa).max())
    return out


def frontend(p, vbs=(0.42, 0.46, 0.50, 0.54, 0.58)) -> dict:
    P.R_LRS_BR = p.r_tx + float(DM.device_resistance(p.gap_lrs))
    P.R_HRS_BR = p.r_tx + float(DM.device_resistance(p.gap_hrs))
    out = {}
    for vb in vbs:
        des = dict(DESIGN)
        des["vb"] = vb
        dz = mc.Design(**des)
        n = mc.noise(dz, windows=tuple(t * 1e-9 for t in TS_NS))
        fid = {f"{T:g}": mc.fidelity(dz, T * 1e-9) for T in (1, 4)}
        pu = power_up(dz, t_end=12e-9)
        out[str(vb)] = dict(sigma_uA={f"{t:g}": v * 1e6 for t, v in ((k * 1e9, s) for k, s in n["sigma"].items())}, eta={k: v["step_ratio_min"] for k, v in fid.items()},
                            i_idle_uA=pu["i_final_uA"], t_en_ns=pu["t_settle_ns"], i_bias_uA=mc.bias_current(dz)["i_vdd_a"] * 1e6)
    return out


def point(r_lrs: float, ex=None, with_fe: bool = True) -> dict:
    cell = cell_for(r_lrs)
    p = params(r_lrs, cell)
    lv = levels_and_sigma(p)
    rl = rowline(p, cell, ex)
    out = dict(ron=r_lrs, cell=cell, gap_lrs_nm=p.gap_lrs, levels=lv, rowline=rl)
    if with_fe:
        out["frontend"] = frontend(p)
    return out


def _job(r):
    return point(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--ron", type=float, nargs="*", default=list(RS_DEFAULT))
    ap.add_argument("--out", default="operating_point_sweep.json")
    a = ap.parse_args()
    worst = check_scaling()
    print(f"scaling check: I(V,gap(R)) R/541.8 constant to {worst:.2e}", flush=True)
    with ProcessPoolExecutor(a.procs, max_tasks_per_child=1) as ex:          # a fresh process per point: the front-end models cache their array resistances
        res = list(ex.map(_job, a.ron))
    out = dict(scaling_check_max_rel_dev=worst, points={str(r["ron"]): r for r in res})
    (RP.MACRO / a.out).write_text(json.dumps(out, indent=1, default=float))
    for r in res:
        c, lv, rl = r["cell"], r["levels"], r["rowline"]
        print(f"R {r['ron']:8.1f}  w {c['w_F']:6.1f} F  Rtx {c['r_tx']:6.1f}  step {lv['step_uA']:7.2f} uA  sigma_lim {lv['sigma_lnG_limit']:.2f}  gain spread {rl['spread_frac']*100:5.1f}%  rank0 resid {rl['resid_rank0']*100:5.2f}%", flush=True)


if __name__ == "__main__":
    main()
