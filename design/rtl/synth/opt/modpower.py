#!/usr/bin/env python3
"""Power BY MODULE of the hierarchy-preserving synthesis (pre-layout, pin capacitance only, no wires, ideal clock) over the same two windows: where does the digital activity sit?
  python opt/modpower.py --net work/opt/hier/netlist_raw.v --const work/opt/hier/const_ports.json --macro-dir work/opt/c8s/macro --out work/opt/hier"""
import argparse, json, re, subprocess, sys, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gatesim as GS, power as PW  # noqa: E402
ap = argparse.ArgumentParser()
ap.add_argument("--net", required=True); ap.add_argument("--const", required=True); ap.add_argument("--macro-dir", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--row", type=int, default=46); ap.add_argument("--ts", type=int, default=10)
a = ap.parse_args()
out = Path(a.out).resolve(); win = PW.windows(a.row, a.ts)
const = json.loads(Path(a.const).read_text())
res = {}
for w in ("ing", "mvm"):
    d = GS.run("full", out / f"gs_{w}", Path(a.net).resolve(), const, a.row, win[w]["start"], win[w]["length"], vcd_name=f"{w}.vcd")
    tcl = f"""read_liberty {PW.PDK}/lib/fast_vdd1v0_basicCells.lib
foreach l [glob {Path(a.macro_dir).resolve()}/*.lib] {{ read_liberty $l }}
read_verilog {str(Path(a.net).resolve()).replace("_raw", "")}
link_design cim_neurohdc_top
read_sdc {PW.SYNTH}/constraints/cim_neurohdc_top.sdc
read_vcd -scope hdc_gate_tb/dut {d['vcd']}
report_power -instances [get_cells -hierarchical *] > {out}/inst_{w}.rpt
report_power > {out}/tot_{w}.rpt
"""
    (out / f"mp_{w}.tcl").write_text(tcl)
    subprocess.run([str(PW.ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(out / f"mp_{w}.tcl")], capture_output=True, text=True)
    Path(d["vcd"]).unlink(missing_ok=True)
    agg = collections.defaultdict(float)
    for l in open(out / f"inst_{w}.rpt"):
        f = l.split()
        if len(f) == 5 and re.match(r"[\d.e+-]+$", f[3]):
            parts = f[4].split("/")
            k = "/".join(parts[:2]) if parts[0].startswith("u_") and len(parts) > 2 else parts[0] if len(parts) > 1 else "(top)"
            agg[k] += float(f[3])
    tot = sum(agg.values())
    res[w] = dict(total_uW=tot * 1e6, modules={k: v * 1e6 for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:14]})
    print(w, round(tot * 1e6, 1), {k: round(v * 1e6, 1) for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:12]})
(out / "modpower.json").write_text(json.dumps(res, indent=1))
