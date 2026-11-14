"""Operating-point sweep, second half (S1 d, S2, S4): from `operating_point_sweep.json` (device / row line / front-end at every LRS, each with its own select transistor) and
`design/rtl/synth/results/neurosim_sweep.json` (NeuroSim area at every cell) build, per point: the analog macro area by part, the crossbar energy per inference with items 7-9 applied at every
point on the same footing, the comparator re-costing (S2) and the wait cycles the integration window forces.

Energy (per inference, at the RTL's non-zero group reads):
  sense bias   item 8 (boosted wake-up x0.73 ramp, 40 shared channels: ramp paid once per read per channel) + item 9 (each of the 8 weight planes takes the cheapest (vb, T) whose
               (sigma / (eta step))^2 stays within f_k x the original 1F design's (0.0116^2); f_k = the per-plane variance relaxation of `energy_opt`)
  array + wl   `energy_1f` array energy x (branch current / the 20 F^2 branch current) x T, word line x transistor width
  comparators  n_cmp x (preamp + latch + threshold capacitor array); 'before' = 100 fJ x 2^0 (10-bit array, the 1F assumption); 'after' (S2) = array sized for the TRIM range left once the
               row-gain correction is static (rank 0): bits_k = ceil(log2(trim range / (sigma_k / 2))), trim range = 2 x (rank-0 row-gain residual x full scale + the 1F budget's per-column calibration residual, 6.3 uA), energy 100 fJ x 2^(bits_k - 10) + 3 fJ ladder select [ASSUM]
  threshold    rank-k correction (k MAC + n_cmp multiplies per position per read) where the row-gain residual does not fit the budget, 0 where rank 0 fits.  The budget a row-gain error may use
               is 4.24 % of full scale at the 541.8 ohm point (1F section 8) and scales with what the device spread leaves of the half step at sigma_lnG = 0.05.
Area (mm^2) = 1.2 x (5 x NeuroSim array + 5 x NeuroSim periphery + front-end + decoupling); front-end 0.1052 at 160 channels (1F 'mid'), decoupling 0.1667 x peak supply current / the 1F design's.
   python -m scaleup.op_sweep_report [--reads 16748.154]"""
from __future__ import annotations

import paths as RP

import argparse
import json
from math import ceil, log2
from pathlib import Path

from scaleup import op_sweep as S
from sense import energy_1f as E1
from sense import energy_opt as EO

V = 1.1
TAIL = 0.3e-9
SHARED = 0.25
CLK_NS = 10.0
SYNTH = Path(__file__).resolve().parents[3] / "design" / "rtl" / "synth"
FE = dict(front_ends_um2_160=83810.0, ladder_gain_um2=17862.0, calibration_um2=3200.0, straps_um2=323.85, per_col=dict(channel=141.41, int_caps=40.0, decision=62.4, thr_cap=250.0, trims=30.0))
DECAP_1NF_MM2 = 0.1666667
EPS_REF = 0.04239
E_COMP_FJ = dict(preamp=51e-6 * V * 0.3e-9 * 1e15, latch=10.0, dac=100.0)
E_SELECT_FJ = 3.0
RHO0 = 0.9366 / (0.6468 * 125.364)                      # the requirement: noise relative to the level step that the ORIGINAL 1F design delivered at vb 0.5 V, T = 1 ns (lowbias.json, 20 F^2 cell, step 125.36 uA); item 9 relaxes it per plane
CAL_RESIDUAL_UA = 6.30                                   # per-column calibration residual (5 sigma) of the 1F budget at the design point (closure_map.json), absolute uA
N_COL = S.N_COL
MUX_UM2_PER_COL = 10.0                                   # [ASSUM] analog column mux onto a shared channel


def tidx(T: float) -> str:
    return "1" if T <= 2 else "4"


def plane_choices(pt: dict, ref: dict, f: list[float], i_sig_uA: float, ramp: float, tcap: float | None = None) -> list[dict] | None:
    fe, step = pt["frontend"], pt["levels"]["step_uA"]
    eff0 = RHO0 ** 2
    out = []
    for k, fk in enumerate(f):
        best = None
        for vb, d in fe.items():
            for T in S.TS_NS:
                if tcap is not None and T > tcap:
                    continue
                sg = d["sigma_uA"][f"{T:g}"]
                eta = d["eta"][tidx(T)]
                if (sg / (eta * step)) ** 2 <= fk * eff0 * 1.0001:
                    i_idle = d["i_idle_uA"] * 1e-6
                    e = V * (i_idle * d["t_en_ns"] * 1e-9 * ramp * SHARED + (i_idle + i_sig_uA * 1e-6) * (T * 1e-9 + TAIL))
                    if best is None or e < best["col_read_J"]:
                        best = dict(plane=k, vb=float(vb), T_ns=float(T), sigma_uA=sg, eta=eta, i_idle_uA=d["i_idle_uA"], t_en_ns=d["t_en_ns"], col_read_J=e)
                    break
        if best is None:
            return None
        out.append(best)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reads", type=float, default=EO.READS)
    ap.add_argument("--tcap", type=float, default=None, help="largest sense window allowed, ns: decoupling scales with the window (C ~ I x (T + 0.3 ns) / 1.3 ns), so a short window trades energy for macro area")
    ap.add_argument("--out", default="operating_point_sweep_report.json")
    ap.add_argument("--sigma-device", type=float, default=0.05, help="sigma_lnG at which the row-gain budget is scaled")
    a = ap.parse_args()
    sw = json.loads((RP.MACRO / "operating_point_sweep.json").read_text())["points"]
    fine = RP.MACRO / "operating_point_sweep_fine.json"
    if fine.exists():
        sw.update(json.loads(fine.read_text())["points"])
    ns = json.loads((SYNTH / "results" / "neurosim_sweep.json").read_text())
    opt = EO.compute(a.reads)
    f = [p["variance_relaxation"] for p in opt["planes"]]
    ramp = opt["ramp_ratio"]
    base = E1.energy(0.5, 1e-9, TAIL, 4)
    sc = a.reads / base["reads_nonzero"]
    i_br20 = 64.19035                                              # uA, 20 F^2 branch current (op_point.json)
    ref = sw["541.8"]
    sg = str(a.sigma_device)
    s5_ref = ref["levels"]["closes_at"][sg]["spread_5sigma_over_half_step"]
    nc = base["n_cmp"]
    h = E1.HOROWITZ
    rows = []
    i_sup_ref = None
    for key in sorted(sw, key=float):
        pt = sw[key]
        R = pt["ron"]
        cell, lv, rl = pt["cell"], pt["levels"], pt["rowline"]
        i_sig = base["i_sig_uA"] * lv["i_lrs_branch_uA"] / i_br20
        pc = plane_choices(pt, ref, f, i_sig, ramp, a.tcap)
        row = dict(ron=R, w_F=cell["w_F"], r_tx=cell["r_tx"], tx_w_um=cell["tx_w_um"], cell_area_F2=cell["area_F2"], step_uA=lv["step_uA"], sigma_lnG_limit=lv["sigma_lnG_limit"],
                   closes_at={k: v["ok"] for k, v in lv["closes_at"].items()}, rowline=rl, i_lrs_branch_uA=lv["i_lrs_branch_uA"])
        if pc is None:
            row["feasible"] = False
            rows.append(row)
            continue
        row["feasible"] = True
        row["planes"] = pc
        e_cols = [c["col_read_J"] for c in pc]
        i_idle_mean = sum(c["i_idle_uA"] for c in pc) / 8
        gap_J = 3 * TAIL * V * i_idle_mean * 1e-6 * 40 * a.reads
        sense = a.reads * 20 * sum(e_cols) + gap_J
        Tmax = max(c["T_ns"] for c in pc)
        Tw = sum(c["T_ns"] for c in pc) / 8
        arr = base["array_J"] * sc * (lv["i_lrs_branch_uA"] / i_br20) * Tw
        wl = base["wordline_J"] * sc * (cell["tx_w_um"] / 0.54)
        # threshold correction: budget scaled by what the device spread leaves
        s5 = lv["closes_at"][sg]["spread_5sigma_over_half_step"]
        eps = EPS_REF * max(0.0, 1 - s5) / (1 - s5_ref)
        rk = next((k for k in (0, 1, 2, 3) if rl["resid_rank0" if k == 0 else f"resid_rank{k}"] <= eps), None)
        thr = 0.0 if not rk else 32 * (rk * (h["mult12_J"] + h["add12_J"]) + nc * h["mult12_J"]) * a.reads
        # comparators, before: 10-bit array; after (S2): array sized to the trim range
        fs = lv["full_scale_uA"]
        cmp_before = a.reads * N_COL * nc * (E_COMP_FJ["preamp"] + E_COMP_FJ["latch"] + E_COMP_FJ["dac"]) * 1e-15
        trim = 2 * (rl["resid_rank0"] * fs + CAL_RESIDUAL_UA)
        bits = [max(2, ceil(log2(trim / (c["sigma_uA"] / 2)))) for c in pc]
        bits_full = [max(2, ceil(log2(fs / (c["sigma_uA"] / 2)))) for c in pc]
        cmp_after = a.reads * 20 * nc * sum((E_COMP_FJ["preamp"] + E_COMP_FJ["latch"] + E_COMP_FJ["dac"] * 2 ** (b - 10) + E_SELECT_FJ) * 1e-15 for b in bits)
        row.update(dict(
            T_ns_by_plane=[c["T_ns"] for c in pc], vb_by_plane=[c["vb"] for c in pc], T_max_ns=Tmax, T_mean_ns=Tw,
            cycles_per_pass=max(1, ceil((Tmax + TAIL * 1e9 + 1.0) / CLK_NS)),
            budget_eps=eps, min_rank=rk, dac_bits_after=bits, dac_bits_full=bits_full,
            energy_uJ=dict(sense_bias=sense * 1e6, array=arr * 1e6, wordline=wl * 1e6, comparators_before=cmp_before * 1e6, comparators_after=cmp_after * 1e6, threshold=thr * 1e6,
                           total_before=(sense + arr + wl + cmp_before + thr) * 1e6, total_after=(sense + arr + wl + cmp_after + thr) * 1e6),
            i_idle_mean_uA=i_idle_mean, i_sig_uA=i_sig))
        # area
        n = ns[key]
        if not n.get("feasible"):
            row["area_note"] = "NeuroSim infeasible"
            rows.append(row)
            continue
        cell_arr = 5 * n["area_array_um2"] * 1e-6
        periph = 5 * n["area_other_um2"] * 1e-6
        fe160 = (FE["front_ends_um2_160"] + FE["ladder_gain_um2"] + FE["calibration_um2"] + FE["straps_um2"]) * 1e-6
        pc_ = FE["per_col"]
        dac_f = 2 ** (sum(bits) / 8 - 10)
        fe_after160 = fe160 - 160 * pc_["thr_cap"] * (1 - dac_f) * 1e-6
        fe_shared = (40 * (pc_["channel"] + pc_["int_caps"] + pc_["decision"] + pc_["thr_cap"] * dac_f) + 160 * (pc_["trims"] + MUX_UM2_PER_COL) + FE["ladder_gain_um2"] + FE["calibration_um2"] + FE["straps_um2"]) * 1e-6
        i_sup = N_COL * (i_idle_mean + i_sig)
        if i_sup_ref is None:
            i_sup_ref = N_COL * (base["i_idle_uA"] + base["i_sig_uA"])
        decap_arr = DECAP_1NF_MM2 * (lv["i_lrs_branch_uA"] * 4 * 160) / (i_br20 * 4 * 160)
        # the droop is set by the ARRAY current (the front-end bias is a quiet DC load) and the pulse: charge ~ I x (T + 0.3 ns tail); the 1F design is 8.7 mA, 1.3 ns, 8 mV for 1 nF
        decap = decap_arr * (Tmax + 0.3) / 1.3
        row["area_mm2"] = dict(cell_array=cell_arr, periphery=periph, front_end_160=fe160, front_end_160_s2=fe_after160, front_end_40shared_s2=fe_shared, decap=decap, decap_array_current_only=decap_arr,
                               macro_160_before=1.2 * (cell_arr + periph + fe160 + decap), macro_160_s2=1.2 * (cell_arr + periph + fe_after160 + decap), macro_40shared_s2=1.2 * (cell_arr + periph + fe_shared + decap),
                               macro_40shared_s2_decaplow=1.2 * (cell_arr + periph + fe_shared + decap_arr), ns_macro_um2=n["area_macro_um2"], ns_h_um=n["height_um"], ns_w_um=n["width_um"])
        rows.append(row)
    out = dict(reads=a.reads, sigma_device=a.sigma_device, rows=rows)
    (RP.MACRO / a.out).write_text(json.dumps(out, indent=1, default=float))
    print(f"{'Ron':>8} {'w_F':>6} {'Rtx':>6} {'step':>6} {'sig':>4} {'rk':>2} {'Tmax':>5} {'cyc':>3} {'sense':>6} {'arr':>5} {'wl':>5} {'cmpB':>5} {'cmpA':>5} {'thr':>5} {'totB':>5} {'totA':>5}  macro160 macro160S2 macro40S2")
    for r in rows:
        if not r.get("feasible"):
            print(f"{r['ron']:8.1f} {r['w_F']:6.1f} INFEASIBLE (no window up to 64 ns meets the per-plane noise requirement)")
            continue
        e, ar = r["energy_uJ"], r.get("area_mm2", {})
        print(f"{r['ron']:8.1f} {r['w_F']:6.1f} {r['r_tx']:6.1f} {r['step_uA']:6.1f} {r['sigma_lnG_limit']:4.2f} {str(r['min_rank']):>2} {r['T_max_ns']:5.1f} {r['cycles_per_pass']:3d} {e['sense_bias']:6.3f} {e['array']:5.3f} {e['wordline']:5.3f} "
              f"{e['comparators_before']:5.3f} {e['comparators_after']:5.3f} {e['threshold']:5.3f} {e['total_before']:5.3f} {e['total_after']:5.3f}  {ar.get('macro_160_before', 0):.3f} {ar.get('macro_160_s2', 0):.3f} {ar.get('macro_40shared_s2', 0):.3f}")


if __name__ == "__main__":
    main()
