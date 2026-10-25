"""Crossbar read energy per inference after optimisation items 7, 8, 9 (stacked in that order), from the 1F energy model (sense.energy_1f) with its inputs replaced by the new simulations:
  item 7  the threshold correction at the rank the row-line metal needs (results/macro_512x32/row_line_metal_sweep.json; rank r costs 32 positions x (r MAC + n_cmp multiplies) per read, rank 0 = static ladder)
  item 8a boosted wake-up (sense/wakeup.json: ramp energy x0.73, settle 0.95 ns)       8b front-end kept powered across the 4 passes of a read (40 shared channels: the ramp is paid 40x per read instead of 160x)
  item 9  per-plane (vb, window) from the tolerated error rate of each weight plane (sense/plane_readout*.json, sense/lowbias.json)
Reads: the RTL's mean non-zero group reads per inference (16,748, g = 4, early exit theta = 50).   Usage: python -m sense.energy_opt"""
from __future__ import annotations

import json
from math import erfc, sqrt

import numpy as np

import paths as RP
from sense import energy_1f as E

V = 1.1
READS = 16748.154
N_COL = 160
TAIL = 0.3e-9


def qinv(p):
    lo, hi = 0.0, 12.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if 0.5 * erfc(mid / sqrt(2)) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def compute(READS: float = READS) -> dict:
    """all steps of the crossbar energy for a given number of non-zero group reads per inference"""
    arr, en, rc = E.load()
    base = E.energy(0.5, 1e-9, TAIL, 4)
    i_sig = base["i_sig_uA"] * 1e-6
    wk = json.loads((RP.SENSE / "wakeup.json").read_text())
    best = min((r for r in wk["boost"] if r["t_settle_ns"] < 1.2), key=lambda r: r["e_ramp_pJ_per_channel"])
    ramp_ratio = best["e_ramp_pJ_per_channel"] / wk["baseline"]["e_ramp_pJ_per_channel"]
    lb = {r["vb"]: r for r in json.loads((RP.SENSE / "lowbias.json").read_text()) if "error" not in r}
    nc = base["n_cmp"]
    h = E.HOROWITZ

    def thr(rank):
        return 0.0 if rank == 0 else 32 * (rank * (h["mult12_J"] + h["add12_J"]) + nc * h["mult12_J"]) * READS

    def col_read_J(vb, T, ramp_mult=1.0, shared=1.0):
        """energy of one column's front-end for one read: ramp (x ramp_mult, x shared channels fraction) + idle + signal over the window"""
        i_idle = lb[vb]["i_idle_uA"] * 1e-6 if vb != 0.5 else base["i_idle_uA"] * 1e-6
        t_en = lb[vb]["t_powerup_ns"] * 1e-9 if vb != 0.5 else base["t_en_ns"] * 1e-9
        return V * (i_idle * t_en * ramp_mult * shared + i_idle * (T + TAIL) + i_sig * (T + TAIL))

    e_arr = base["array_J"] + base["wordline_J"] if False else None
    arr_wl = E.energy(0.5, 1e-9, TAIL, 4)
    # array + word line + comparators: as 1F, scaled to the RTL's read count
    scale = READS / base["reads_nonzero"]
    e_array = (base["array_J"] + base["wordline_J"]) * scale if base["array_J"] else 0.0
    e_cmp = base["decision_J"] * scale
    rows = []

    def total(sense, rank):
        return e_array + e_cmp + sense + thr(rank)

    sense0 = READS * N_COL * col_read_J(0.5, 1e-9)
    t0 = base["total_J"] * scale if False else None
    rows.append(("1F baseline (rank-3 threshold correction, 160 front-ends, ramp per read)", sense0, 3))
    # item 7: rank from the metal sweep
    sw = json.loads((RP.MACRO / "row_line_metal_sweep.json").read_text())["rows"]
    by_r = {r["r_wl_ohm_per_cell"]: r for r in sw}
    rows.append(("+ item 7: rank-1 correction (row line R 1.15 ohm/cell, r_drv 10 ohm)", sense0, 1))
    rows.append(("  (item 7 alternative: rank 0 - residual 4.1 % = the whole budget margin)", sense0, 0))
    s8a = READS * N_COL * col_read_J(0.5, 1e-9, ramp_ratio)
    rows.append((f"+ item 8a: boosted wake-up (vb {best['vb_boost']} for {best['t_boost_ns']} ns, ramp x{ramp_ratio:.2f}, settle {best['t_settle_ns']:.2f} ns)", s8a, 1))
    gap_J = 3 * 0.3e-9 * V * base["i_idle_uA"] * 1e-6 * 40 * READS
    s8b = READS * N_COL * col_read_J(0.5, 1e-9, ramp_ratio, 0.25) + gap_J
    rows.append(("+ item 8b: front-end kept powered across the 4 passes (40 shared channels)", s8b, 1))
    # item 9
    pr = json.loads((RP.SENSE / "plane_readout.json").read_text())
    combo = json.loads((RP.SENSE / "plane_readout_combo.json").read_text())
    scale_p = 0.03
    tol = [0.3, 0.1, 0.01, 0.003, 0.003, 1e-4, 1e-4, 1e-4]
    p_use = [min(0.5, t * scale_p) for t in tol]
    sig0 = qinv(5.7e-7 / 2)
    f = [(sig0 / qinv(p / 2)) ** 2 for p in p_use]
    eta = {0.5: {v: lb[v]["step_ratio_min"]["0.5"] for v in lb}, 1.0: {v: lb[v]["step_ratio_min"]["1"] for v in lb}}
    sig = {0.5: {v: lb[v]["sigma_uA"]["0.5"] for v in lb}, 1.0: {v: lb[v]["sigma_uA"]["1"] for v in lb}}
    eff0 = (sig[1.0][0.5] / eta[1.0][0.5]) ** 2
    choice, e_cols = [], []
    for k in range(8):
        cands = []
        for vb in lb:
            for T in (0.5, 1.0):
                if (sig[T][vb] / eta[T][vb]) ** 2 <= f[k] * eff0 * 1.0001:
                    cands.append((col_read_J(vb, T * 1e-9, ramp_ratio, 0.25), vb, T))
        c = min(cands)
        choice.append(dict(plane=k, p_err=p_use[k], variance_relaxation=f[k], vb=c[1], window_ns=c[2], col_read_pJ=c[0] * 1e12))
        e_cols.append(c[0])
    s9 = READS * 20 * sum(e_cols) + gap_J
    rows.append(("+ item 9: per-plane bias / window (vb, T by weight bit-plane)", s9, 1))
    out = []
    for name, s, rank in rows:
        out.append(dict(step=name, sense_bias_uJ=s * 1e6, threshold_uJ=thr(rank) * 1e6, array_wl_uJ=e_array * 1e6, comparators_uJ=e_cmp * 1e6, crossbar_total_uJ=total(s, rank) * 1e6))
    return dict(reads=READS, steps=out, planes=choice, ramp_ratio=ramp_ratio, boost=best)


def main() -> None:
    r = compute()
    for s in r["steps"]:
        print(f"{s['step']:100s} sense {s['sense_bias_uJ']:.3f}  thr {s['threshold_uJ']:.3f}  arr {s['array_wl_uJ']:.3f} cmp {s['comparators_uJ']:.3f} -> {s['crossbar_total_uJ']:.3f} uJ")
    (RP.SENSE / "energy_opt.json").write_text(json.dumps(r, indent=1, default=float))


if __name__ == "__main__":
    main()
