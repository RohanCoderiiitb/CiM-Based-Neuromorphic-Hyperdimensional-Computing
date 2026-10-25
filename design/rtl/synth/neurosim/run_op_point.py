#!/usr/bin/env python3
"""Item 10: NeuroSim area of ONE macro at the high-LRS operating point (cell 20 F^2, 5 F x 4 F: at Ron = 40 kohm the access transistor needs no more than the minimum width, so NeuroSim accepts the cell it refused
at 541.8 ohm). Same driver, geometry and settings as run_neurosim.py; only Ron / Roff / racc change.  python run_op_point.py [--work DIR] [--ron 40000]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_neurosim as RN  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--work", default="/private/tmp/claude-501/nswork")
ap.add_argument("--ron", type=float, nargs="*", default=[40000.0])
a = ap.parse_args()
bld = RN.build(Path(a.work))
out = {}
for ron in a.ron:
    RN.RON = ron
    for tag, w in (("20F2", 5), ("40F", 40)):
        v = dict(w=w, h=4, F=45, racc=1016.0459 if w == 5 else 505.79, label=f"{w} F x 4 F cell, Ron {ron:.0f} ohm")
        d = RN.run_variant(bld, f"op_{tag}_{int(ron)}", v)
        out[f"{tag}_{int(ron)}"] = d
        print(tag, ron, "feasible" if d.get("feasible") else "INFEASIBLE: " + d.get("message", "")[:200], d.get("area_macro_um2"), d.get("read_energy_pJ"))
(HERE.parent / "results" / "neurosim_op_point.json").write_text(json.dumps(out, indent=1))
