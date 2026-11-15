"""Crossbar of the LARGE chip (40 neurons = 320 columns, 10 NeuroSim macros of 512 x 32): energy per packed read and macro area, same footing as packed_reads.py
(3.5 kohm, per-plane cheapest (vb, T), window cap 1 ns, S rows per read), with the ASL-DVS packed read population at W_COUNT = 12 bit-planes, for 40 and 80 shared channels.
   python -m scaleup.packed_reads_large [--rows 5]     -> results/macro_512x32/packed_reads_large.json"""
from __future__ import annotations

import paths as RP

import argparse
import json

from scaleup import packed_reads as PR
from scaleup import op_sweep_report as R
from sense import energy_1f as E1
from sense import energy_opt as EO


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=5)
    ap.add_argument("--tcap", type=float, default=1.0)
    ap.add_argument("--ron", type=float, default=3500.0)
    ap.add_argument("--datasets", nargs="+", default=["asl"])
    a = ap.parse_args()
    sw = json.loads((RP.MACRO / "operating_point_sweep.json").read_text())["points"]
    sw.update(json.loads((RP.MACRO / "operating_point_sweep_fine.json").read_text())["points"])
    ns = json.loads((R.SYNTH / "results" / "neurosim_sweep.json").read_text())
    key = str(float(a.ron))
    pt, ref = sw[key], sw["541.8"]
    opt = EO.compute(EO.READS)
    f = [p["variance_relaxation"] for p in opt["planes"]]
    base = E1.energy(0.5, 1e-9, R.TAIL, 4)
    out = dict(ron=a.ron, tcap=a.tcap, s_rows=a.rows, n_neurons=40, w_count=12, datasets={})
    pops = PR.packed_population(a.rows, tuple(a.datasets), w_count=12)
    for ds, pop in pops.items():
        out["datasets"][ds] = dict(population=pop, channels={})
        for n_ch in (40, 80):
            pr = PR.per_read(pt, ref, f, opt["ramp_ratio"], a.tcap, base, pop, a.rows, 64.19035, ns, key, n_neur=40, n_ch=n_ch)
            out["datasets"][ds]["channels"][n_ch] = dict(crossbar=pr, pJ_per_read=pr["pJ_per_read"]["total"], crossbar_uJ=pr["pJ_per_read"]["total"] * pop["reads"] * 1e-6)
            e = pr["pJ_per_read"]
            print(f"{ds} S={a.rows} ch={n_ch}: reads {pop['reads']:.0f} (mean active {pop['mean_active']:.2f}, n_cmp {pop['n_cmp']:.2f}) | pJ/read {e['total']:.2f} (sense {e['sense']:.1f} arr {e['array']:.1f} "
                  f"wl {e['wordline']:.1f} cmp {e['comparators']:.1f}) | crossbar {out['datasets'][ds]['channels'][n_ch]['crossbar_uJ']:.4f} uJ | macro {pr['macro_mm2']:.4f} mm2 (decap {pr['decap_mm2']:.4f}, front end {pr['front_end_mm2']:.4f})", flush=True)
    (RP.MACRO / "packed_reads_large.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
