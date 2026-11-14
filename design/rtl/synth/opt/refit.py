#!/usr/bin/env python3
"""Re-report the power of the windows of an existing power2 fit from their saved SAIF files (no new gate-level simulation) with 7 significant digits, and refit E = c0*cycles + e_ev*events + e_rd*passes.
   python opt/refit.py --tag s3 [--stage groute] [--lib fast]"""
import argparse, json, re, subprocess
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ap = argparse.ArgumentParser(); ap.add_argument("--tag", required=True); ap.add_argument("--stage", default="groute"); ap.add_argument("--lib", default="fast"); ap.add_argument("--c0-idle-w", type=float, default=None, help="fix c0 = this idle power x 10 ns (measured with power_prof.py --spec idle) and fit only e_ev, e_rd")
a = ap.parse_args()
run = HERE.parent / "work" / "opt" / a.tag
d = json.loads((run / f"power2_{a.stage}.json").read_text())
for k, w in enumerate(d["windows"]):
    name = f"w{k}_{w['dataset']}{w['row']}"
    src = (run / "an" / f"pw_{name}_fast.tcl").read_text()
    tcl = re.sub(r"report_power(?: -digits \d+)? >", "report_power -digits 7 >", src).replace("_fast.rpt", f"_{a.lib}7.rpt")
    if a.lib != "fast":
        tcl = tcl.replace("fast_vdd1v0", f"{a.lib}_vdd1v0").replace(f"{a.stage}_fast.spef", f"{a.stage}_{a.lib}.spef")
    f = run / "an" / f"pw_{name}_{a.lib}7.tcl"; f.write_text(tcl)
    subprocess.run([str(ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(f)], capture_output=True, text=True)
    txt = (run / "an" / f"power_{name}_{a.lib}7.rpt").read_text()
    tot = re.search(r"^Total\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)
    w["power_w"] = float(tot.group(4)); w["leakage_w"] = float(tot.group(3))
    print(w["spec"], w["power_w"], w["cycles"], w["events"], w["reads"], flush=True)
A = np.array([[w["cycles"], w["events"], w["reads"]] for w in d["windows"]], float)
E = np.array([w["power_w"] * w["cycles"] * 10e-9 for w in d["windows"]], float)
if a.c0_idle_w is None:
    coef, *_ = np.linalg.lstsq(A, E, rcond=None)
else:
    c0 = a.c0_idle_w * 10e-9
    c12, *_ = np.linalg.lstsq(A[:, 1:], E - c0 * A[:, 0], rcond=None)
    coef = np.array([c0, *c12])
pred = A @ coef
d["fit"] = dict(c0_J_per_cycle=coef[0], e_event_J=coef[1], e_read_J=coef[2], residual_rel=[float((p - e) / e) for p, e in zip(pred, E)], rank=3, lib=a.lib, digits=7)
out = run / f"power2_{a.stage}{'' if a.lib == 'fast' else '_' + a.lib}{'_idle' if a.c0_idle_w else ''}.json"
out.write_text(json.dumps(d, indent=1))
print("FIT", {k: (v * 1e12 if isinstance(v, float) else v) for k, v in d["fit"].items() if k != "residual_rel"}, [round(x, 4) for x in d["fit"]["residual_rel"]])
