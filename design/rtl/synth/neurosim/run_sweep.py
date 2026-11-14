#!/usr/bin/env python3
"""S1: NeuroSim area of ONE macro (512 rows x 32 weight columns, 64 physical columns) at every operating point of the sweep: cell = w_F x 4 F with w_F the select-transistor width the SET current needs
(scaleup.op_sweep.cell_for), Ron = the point's LRS. Same driver, geometry and settings as run_neurosim.py. Writes results/neurosim_sweep.json.   python run_sweep.py [--work DIR] [--ron ...]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3] / "studies" / "crossbar"))
import run_neurosim as RN  # noqa: E402
from scaleup import op_sweep as S  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--work", default=str(Path.home() / ".cache" / "cim_neurohdc" / "neurosim"))
ap.add_argument("--ron", type=float, nargs="*", default=list(S.RS_DEFAULT))
a = ap.parse_args()
bld = RN.build(Path(a.work))
OUTF = HERE.parent / "results" / "neurosim_sweep.json"
out = json.loads(OUTF.read_text()) if OUTF.exists() else {}          # merge: the sweep is run in several batches
for ron in a.ron:
    c = S.cell_for(ron)
    RN.RON = ron
    w = round(c["w_F"], 2)
    v = dict(w=w, h=4, F=45, racc=c["r_tx"], label=f"{w} F x 4 F cell, Ron {ron:.0f} ohm")
    d = RN.run_variant(bld, f"sw_{int(ron)}", v)
    d["ron"], d["cell"] = ron, c
    out[str(ron)] = d
    print(ron, "feasible" if d.get("feasible") else "INFEASIBLE: " + d.get("message", "")[:160], d.get("area_macro_um2"), flush=True)
OUTF.write_text(json.dumps(dict(sorted(out.items(), key=lambda kv: float(kv[0]))), indent=1))
