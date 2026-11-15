#!/usr/bin/env python3
"""Out-of-sample check of the frozen energy model on windows of a NEW dataset: the windows of a power2 run (--windows, written with power2.py --out) are re-reported from
their saved SAIFs at 7 digits at the fast and the slow library (as refit.py does), and their measured energy is compared with E = c0*cycles + e_ev*events + e_rd*passes using
the layout's existing idle-anchored fits (power2_<stage>_idle.json, power2_<stage>_slow_idle.json). Nothing is refitted.
   python opt/validate_windows.py --tag s7 --windows work/opt/s7/power2_groute_c10.json"""
import argparse, json, re, subprocess
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ap = argparse.ArgumentParser(); ap.add_argument("--tag", required=True); ap.add_argument("--stage", default="groute"); ap.add_argument("--windows", required=True)
a = ap.parse_args()
run = HERE.parent / "work" / "opt" / a.tag
d = json.loads(Path(a.windows).read_text())
fits = {"fast": json.loads((run / f"power2_{a.stage}_idle.json").read_text())["fit"], "slow": json.loads((run / f"power2_{a.stage}_slow_idle.json").read_text())["fit"]}
out = []
for k, w in enumerate(d["windows"]):
    name = f"w{k}_{w['dataset']}{w['row']}"
    src = (run / "an" / f"pw_{name}_fast.tcl").read_text()
    rec = dict(spec=w["spec"], golden=w["golden"], cycles=w["cycles"], events=w["events"], reads=w["reads"])
    for lib, fit in fits.items():
        tcl = re.sub(r"report_power(?: -digits \d+)? >", "report_power -digits 7 >", src).replace("_fast.rpt", f"_{lib}7.rpt")
        if lib != "fast":
            tcl = tcl.replace("fast_vdd1v0", f"{lib}_vdd1v0").replace(f"{a.stage}_fast.spef", f"{a.stage}_{lib}.spef")
        f = run / "an" / f"pw_{name}_{lib}7.tcl"; f.write_text(tcl)
        subprocess.run([str(ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(f)], capture_output=True, text=True)
        tot = re.search(r"^Total\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", (run / "an" / f"power_{name}_{lib}7.rpt").read_text(), re.M)
        meas = float(tot.group(4)) * w["cycles"] * 10e-9
        pred = fit["c0_J_per_cycle"] * w["cycles"] + fit["e_event_J"] * w["events"] + fit["e_read_J"] * w["reads"]
        rec[lib] = dict(power_w=float(tot.group(4)), measured_nJ=meas * 1e9, model_nJ=pred * 1e9, model_error_rel=(pred - meas) / meas)
    out.append(rec)
    print(json.dumps(rec), flush=True)
Path(a.windows).with_name(Path(a.windows).stem + "_validation.json").write_text(json.dumps(dict(fits=fits, windows=out), indent=1))
