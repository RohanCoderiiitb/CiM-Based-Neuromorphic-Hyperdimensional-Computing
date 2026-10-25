"""Item 10, second half: the operating point (Ron = 40 kohm, 20 F^2 cell) against the 541.8 ohm baseline, side by side, from the operating_point.json simulations.

Crossbar energy per read with the SAME front-end optimisations (items 8a/8b) for both points:
   window T = the smallest grid window at which 5 sigma of the front-end input noise <= 1/4 of the collected level step (eta x step); bias vb = least energy among those that meet it.
   column read energy = V (i_idle t_en x ramp_mult x shared + (i_idle + i_sig)(T + tail)),   i_sig scaled with the LRS branch current, array + word line energy scaled with (branch current x T),
   comparators unchanged, threshold correction 0 where the row gain is flat (spread < 1 %), otherwise the rank-1 cost of items 7.
Latency: a pass takes ceil((T + tail + t_en)/10 ns) cycles (baseline 1) -> the extra cycles are charged to the digital block at a wait-state power (two bounds are given).
Area: cell array / periphery from the NeuroSim variants (final_ppa.md), 1F front-end unchanged, decoupling scaled with the supply current the macro draws at equal droop, 20 % overhead.
   python -m scaleup.op_point_report --reads 16748.154 [--p-wait-mw 0.543 --p-scan-mw 2.46 --extra-cycles-base ...]"""
from __future__ import annotations

import paths as RP

import argparse
import json
from math import ceil

from sense import energy_1f as E1
from sense import energy_opt as EO

V = 1.1
TAIL = 0.3e-9
SHARED = 0.25
CLK_NS = 10.0
AREA = dict(cell_128F=0.1699, periph_128F=0.0444, front=0.1052, decap_1nF=0.1667, ovh_128F=0.0972)
NS = dict(array_128F=33973.862, other_128F=8872.541, array_20F2=1327.104, other_20F2=5140.079)


def best_point(fe: dict, step_uA: float, i_sig_uA: float, ramp_mult: float, crit: float = 0.25) -> dict:
    """least-energy (vb, T) that meets the noise criterion; None if no window up to 64 ns does"""
    best = None
    for vb, d in fe.items():
        eta = d["eta"]["4"] if "4" in d["eta"] else d["eta"]["1"]
        for T_ns, sg in sorted(d["sigma_uA"].items(), key=lambda kv: float(kv[0])):
            T = float(T_ns) * 1e-9
            if 5 * sg <= crit * eta * step_uA:
                i_idle = d["i_idle_uA"] * 1e-6
                e = V * (i_idle * d["t_en_ns"] * 1e-9 * ramp_mult * SHARED + (i_idle + i_sig_uA * 1e-6) * (T + TAIL))
                cyc = ceil((T + TAIL + d["t_en_ns"] * 1e-9 * 0) / (CLK_NS * 1e-9))
                if best is None or e < best["col_read_pJ"] * 1e-12:
                    best = dict(vb=float(vb), T_ns=float(T_ns), sigma_uA=sg, eta=eta, col_read_pJ=e * 1e12, cycles_per_pass=cyc, i_idle_uA=d["i_idle_uA"], t_en_ns=d["t_en_ns"])
                break
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reads", type=float, default=EO.READS)
    ap.add_argument("--passes", type=int, default=4)
    ap.add_argument("--n-col", type=int, default=160)
    ap.add_argument("--cycles", type=float, default=310860.0, help="cycles per inference of the baseline (RTL)")
    ap.add_argument("--p-wait-mw", type=float, default=0.543, help="digital power while a pass integrates (ingest-window power: clock running, scan idle)")
    ap.add_argument("--p-scan-mw", type=float, default=2.46, help="upper bound: the scan-window power")
    a = ap.parse_args()
    op = json.loads((RP.MACRO / "operating_point.json").read_text())
    arr, en, rc = E1.load()
    base = E1.energy(0.5, 1e-9, TAIL, 4)
    wk = json.loads((RP.SENSE / "wakeup.json").read_text())
    best = min((r for r in wk["boost"] if r["t_settle_ns"] < 1.2), key=lambda r: r["e_ramp_pJ_per_channel"])
    ramp_mult = best["e_ramp_pJ_per_channel"] / wk["baseline"]["e_ramp_pJ_per_channel"]
    opt = EO.compute(a.reads)
    rows = {}
    for key, ron in (("541.8", 541.8), ("40000.0", 40000.0)):
        o = op[key]
        lv = o["levels"]
        i_lrs = lv["i_lrs_branch_uA"]
        i_lrs0 = op["541.8"]["levels"]["i_lrs_branch_uA"]
        scale_i = i_lrs / i_lrs0
        i_sig = base["i_sig_uA"] * scale_i
        bp = best_point(o["frontend"], lv["step_uA"], i_sig, ramp_mult)
        if bp is None:
            rows[key] = dict(ron=ron, feasible=False, reason="no window up to 64 ns meets 5 sigma <= step/4", step_uA=lv["step_uA"])
            continue
        col = bp["col_read_pJ"] * 1e-12
        sense = a.reads * a.n_col * col * 1e6
        scale_arr = scale_i * bp["T_ns"] / 1.0
        arr_wl = opt["steps"][-1]["array_wl_uJ"] * scale_arr
        cmp_ = opt["steps"][-1]["comparators_uJ"]
        flat = o["row_gain"]["spread_frac"] < 0.01
        thr = 0.0 if flat else opt["steps"][-1]["threshold_uJ"]
        xb = sense + arr_wl + cmp_ + thr
        cyc_pass = max(1, bp["cycles_per_pass"])
        extra = a.reads * a.passes * (cyc_pass - 1)
        t_ms = (a.cycles + extra) / 100e6 * 1e3
        e_wait = extra / 100e6 * a.p_wait_mw * 1e-3 * 1e6
        e_scan = extra / 100e6 * a.p_scan_mw * 1e-3 * 1e6
        rows[key] = dict(ron=ron, feasible=True, step_uA=lv["step_uA"], closes_sigma_lnG={s: v["ok"] for s, v in lv["closes_at"].items()}, row_gain_spread=o["row_gain"]["spread_frac"], threshold_correction="none (flat row gain)" if flat else "rank 1",
                         point=bp, crossbar_uJ=dict(sense_bias=sense, array_wl=arr_wl, comparators=cmp_, threshold=thr, total=xb), extra_cycles=extra, latency_ms=t_ms,
                         extra_digital_uJ=dict(wait_state=e_wait, scan_power=e_scan))
    # macro area
    a0 = AREA["cell_128F"] + AREA["periph_128F"] + AREA["front"] + AREA["decap_1nF"]
    cell20 = AREA["cell_128F"] * NS["array_20F2"] / NS["array_128F"]
    per20 = AREA["periph_128F"] * NS["other_20F2"] / NS["other_128F"]
    fe0 = op["541.8"]["frontend"]["0.5"]
    fe4 = op["40000.0"]["frontend"][str(rows["40000.0"]["point"]["vb"])] if rows["40000.0"].get("feasible") else fe0
    i_sup0 = fe0["i_idle_uA"] + 4 * op["541.8"]["levels"]["i_lrs_branch_uA"]
    i_sup4 = fe4["i_idle_uA"] + 4 * op["40000.0"]["levels"]["i_lrs_branch_uA"]
    decap_lo = AREA["decap_1nF"] * (4 * op["40000.0"]["levels"]["i_lrs_branch_uA"]) / (4 * op["541.8"]["levels"]["i_lrs_branch_uA"])      # array current only (the earlier assumption)
    decap_hi = AREA["decap_1nF"] * i_sup4 / i_sup0                                                                                           # front-end idle current included
    areas = {}
    for nm, dc in (("decap_array_current_only", decap_lo), ("decap_with_front_end_idle", decap_hi)):
        sub = cell20 + per20 + AREA["front"] + dc
        areas[nm] = dict(decap=dc, cell=cell20, periphery=per20, front_end=AREA["front"], overhead=0.2 * sub, total_mm2=sub * 1.2)
    out = dict(reads=a.reads, ramp_mult=ramp_mult, points=rows, macro_area_mm2=dict(baseline_128F=0.5833, op40k=areas))
    (RP.MACRO / "operating_point_report.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
