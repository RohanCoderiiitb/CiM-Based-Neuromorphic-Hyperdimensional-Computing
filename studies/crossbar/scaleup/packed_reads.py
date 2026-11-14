"""Crossbar energy and macro area for PACKED-ROW reads with S rows per read (the RTL's plane_seq: a read drives up to S active rows of one count bit-plane inside one 128-row position band).

Same footing as `op_sweep_report` (3.5 kohm point, per-plane cheapest (vb, T) under the item-9 noise requirement, 40 shared channels, comparators after S2, window cap `--tcap`), with the three terms
that depend on the rows of a read taken from the PACKED read population instead of the fixed-group population of `read_counts.json`:
  signal current   i_sig scales with the mean active rows per read (a 4-row packed read is mostly full, a fixed group of 4 averaged 1.61)
  comparators      n_cmp = mean ceil(log2(a + 1)) over the packed reads (binary search over the a + 1 possible match counts)
  decoupling       the array part scales with the rows driven at once (peak array current ~ S x LRS branch current)
plus the device-spread check of `op_sweep.levels_and_sigma` at g = S (5 sigma / half step) at the programmed sigma_lnG.
Read populations come from the golden count vectors (DVS-Gesture r1 seed 0, all 240 rows; N-MNIST, all rows).
   python -m scaleup.packed_reads [--tcap 1] [--ron 3500]"""
from __future__ import annotations

import paths as RP

import argparse
import json
import sys
from math import ceil, log2
from pathlib import Path

import numpy as np

from scaleup import op_sweep as S
from scaleup import op_sweep_report as R
from sense import energy_1f as E1
from sense import energy_opt as EO
from margin import core as MC

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "design" / "rtl"))
sys.path.insert(0, str(REPO / "design" / "rtl" / "synth" / "opt"))


def packed_population(s_rows: int) -> dict:
    """reads per inference and the histogram of active rows per read, packed as plane_seq does."""
    from tb.common import hdc_golden as H
    import nm_power as NP
    out = {}
    for ds, mdl in (("dvs", H.load_model("r1", 0, "dvsgesture")), ("nm", NP.nm_model())):
        C = mdl["counts"].astype(np.int64)
        hist = np.zeros(s_rows + 1)
        for r in range(C.shape[0]):
            for t in range(C.shape[1]):
                c = C[r, t]
                for b in range(11):
                    bits = ((c >> b) & 1).reshape(4, 128).sum(axis=1)
                    for n in bits:
                        n = int(n)
                        hist[s_rows] += n // s_rows
                        if n % s_rows:
                            hist[n % s_rows] += 1
        hist /= C.shape[0]
        a = np.arange(s_rows + 1)
        out[ds] = dict(reads=float(hist.sum()), mean_active=float((hist * a).sum() / hist.sum()), n_cmp=float((hist[1:] * np.ceil(np.log2(a[1:] + 1))).sum() / hist[1:].sum()), hist=hist.tolist())
    return out


def device_spread(r_lrs: float, g: int, sigmas) -> dict:
    cell = S.cell_for(r_lrs)
    p = S.params(r_lrs, cell)
    z = MC.draw_z(g, 400)
    res = {}
    for sg in sigmas:
        m = MC.mc_levels(g, g, p, sg, z, gap_hrs=p.gap_hrs)
        sp = np.abs(np.diff(m["mean_diff"])); sd = m["std_diff"]
        res[f"{sg:g}"] = float((5 * np.maximum(sd[1:], sd[:-1]) / (sp / 2)).max())
    return res


def per_read(pt: dict, ref: dict, f: list, ramp: float, tcap: float | None, base: dict, pop: dict, s_rows: int, i_br20: float, ns: dict, key: str) -> dict:
    lv, rl, cell = pt["levels"], pt["rowline"], pt["cell"]
    i_sig = base["i_sig_uA"] * lv["i_lrs_branch_uA"] / i_br20 * pop["mean_active"] / base_mean_active()
    pc = R.plane_choices(pt, ref, f, i_sig, ramp, tcap)
    e_cols = [c["col_read_J"] for c in pc]
    i_idle_mean = sum(c["i_idle_uA"] for c in pc) / 8
    gap = 3 * R.TAIL * R.V * i_idle_mean * 1e-6 * 40
    sense = 20 * sum(e_cols) + gap
    Tw = sum(c["T_ns"] for c in pc) / 8
    Tmax = max(c["T_ns"] for c in pc)
    sc1 = 1.0 / base["reads_nonzero"]
    arr = base["array_J"] * sc1 * (lv["i_lrs_branch_uA"] / i_br20) * Tw * pop["mean_active"] / base_mean_active()      # array energy ~ conducting branches x T
    wl = base["wordline_J"] * sc1 * (cell["tx_w_um"] / 0.54) * pop["mean_active"] / base_mean_active()                    # word lines driven ~ active rows
    fs = lv["full_scale_uA"] * s_rows / 4                                                                                  # the levels span 0..S
    trim = 2 * (rl["resid_rank0"] * fs + R.CAL_RESIDUAL_UA)
    bits = [max(2, ceil(log2(trim / (c["sigma_uA"] / 2)))) for c in pc]
    cmp = 20 * pop["n_cmp"] * sum((R.E_COMP_FJ["preamp"] + R.E_COMP_FJ["latch"] + R.E_COMP_FJ["dac"] * 2 ** (b - 10) + R.E_SELECT_FJ) * 1e-15 for b in bits)
    n = ns[key]
    pc_ = R.FE["per_col"]
    dac_f = 2 ** (sum(bits) / 8 - 10)
    fe_shared = (40 * (pc_["channel"] + pc_["int_caps"] + pc_["decision"] + pc_["thr_cap"] * dac_f) + 160 * (pc_["trims"] + R.MUX_UM2_PER_COL) + R.FE["ladder_gain_um2"] + R.FE["calibration_um2"] + R.FE["straps_um2"]) * 1e-6
    decap_arr = R.DECAP_1NF_MM2 * (lv["i_lrs_branch_uA"] * s_rows) / (i_br20 * 4)
    decap = decap_arr * (Tmax + 0.3) / 1.3
    macro = 1.2 * (5 * n["area_array_um2"] * 1e-6 + 5 * n["area_other_um2"] * 1e-6 + fe_shared + decap)
    return dict(pJ_per_read=dict(sense=sense * 1e12, array=arr * 1e12, wordline=wl * 1e12, comparators=cmp * 1e12, total=(sense + arr + wl + cmp) * 1e12),
                T_ns=[c["T_ns"] for c in pc], vb=[c["vb"] for c in pc], dac_bits=bits, n_cmp=pop["n_cmp"], mean_active=pop["mean_active"], i_sig_uA=i_sig,
                macro_mm2=macro, decap_mm2=decap, front_end_mm2=fe_shared)


_BMA = None


def base_mean_active() -> float:
    global _BMA
    if _BMA is None:
        _BMA = E1.load()[2]["4"]["mean_active_per_nonzero"]
    return _BMA


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcap", type=float, default=1.0)
    ap.add_argument("--ron", type=float, default=3500.0)
    ap.add_argument("--rows", type=int, nargs="+", default=[4, 5, 6, 8])
    ap.add_argument("--out", default="packed_reads.json")
    a = ap.parse_args()
    sw = json.loads((RP.MACRO / "operating_point_sweep.json").read_text())["points"]
    sw.update(json.loads((RP.MACRO / "operating_point_sweep_fine.json").read_text())["points"])
    ns = json.loads((R.SYNTH / "results" / "neurosim_sweep.json").read_text())
    key = str(float(a.ron))
    pt, ref = sw[key], sw["541.8"]
    opt = EO.compute(EO.READS)
    f = [p["variance_relaxation"] for p in opt["planes"]]
    base = E1.energy(0.5, 1e-9, R.TAIL, 4)
    out = dict(ron=a.ron, tcap=a.tcap, rows={})
    for s in a.rows:
        pop = packed_population(s)
        pr = per_read(pt, ref, f, opt["ramp_ratio"], a.tcap, base, pop["dvs"], s, 64.19035, ns, key)
        pr_nm = per_read(pt, ref, f, opt["ramp_ratio"], a.tcap, base, pop["nm"], s, 64.19035, ns, key)          # the N-MNIST read population (fewer active rows per read)
        spread = device_spread(a.ron, s, (0.0453, 0.066, 0.079, 0.10))
        out["rows"][s] = dict(population=pop, crossbar=pr, crossbar_nm=pr_nm, spread_5sigma_over_half_step=spread,
                              pJ_per_read=dict(dvs=pr["pJ_per_read"]["total"], nm=pr_nm["pJ_per_read"]["total"]),
                              crossbar_uJ=dict(dvs=pr["pJ_per_read"]["total"] * pop["dvs"]["reads"] * 1e-6, nm=pr_nm["pJ_per_read"]["total"] * pop["nm"]["reads"] * 1e-6))
        e = pr["pJ_per_read"]
        print(f"S={s}: DVS reads {pop['dvs']['reads']:8.0f} (mean active {pop['dvs']['mean_active']:.2f}, n_cmp {pop['dvs']['n_cmp']:.2f})  NM reads {pop['nm']['reads']:6.0f} | "
              f"pJ/read {e['total']:.2f} (sense {e['sense']:.1f} arr {e['array']:.1f} wl {e['wordline']:.1f} cmp {e['comparators']:.1f}) | crossbar DVS {out['rows'][s]['crossbar_uJ']['dvs']:.3f} uJ NM {out['rows'][s]['crossbar_uJ']['nm']:.4f} uJ | "
              f"macro {pr['macro_mm2']:.4f} mm2 (decap {pr['decap_mm2']:.4f}) | 5sig/half-step at sigma 0.0453/0.066/0.079/0.10: " + " ".join(f"{v:.2f}" for v in spread.values()), flush=True)
    (RP.MACRO / a.out).write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
