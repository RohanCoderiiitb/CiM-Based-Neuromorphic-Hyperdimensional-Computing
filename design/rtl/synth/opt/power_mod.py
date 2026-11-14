#!/usr/bin/env python3
"""Power BY MODULE of the new design: hierarchy-preserving synthesis (pre-layout: pin capacitance only, no wires, ideal clock), gate-level simulation of one window per spec, OpenSTA read_vcd, instance
power summed over the top two levels of the hierarchy. Proportions only - absolute numbers are lower than the laid-out ones.
  python opt/power_mod.py --out work/opt/hier2 --macro-dir work/opt/h5/macro --spec dvs:46:60000:4000 nm:7:200:2500"""
import argparse, collections, json, re, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gatesim as GS, power as PW, synth_opt as SO  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402
import nm_power as NP  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--macro-dir", required=True)
ap.add_argument("--build", default="ee_off")
ap.add_argument("--spec", nargs="+", required=True)
ap.add_argument("--skip-synth", action="store_true")
a = ap.parse_args()
out = Path(a.out).resolve()
if not a.skip_synth:
    print(SO.synth(a.build, out, 4, "slow", 10.0, ["*XL", "*X1"], "", True, "", 1), flush=True)
const = json.loads((out / "const_ports.json").read_text())
net, raw = out / "netlist.v", out / "netlist_raw.v"
res = {}
mdls = {}
for k, sp in enumerate(a.spec):
    ds, row, start, length = sp.split(":")
    row, start, length = int(row), int(start), int(length)
    if ds not in mdls:
        mdls[ds] = NP.nm_model() if ds == "nm" else H.load_model("r1", 0, "dvsgesture")
    d = GS.run(a.build, out / f"gs_{k}", raw, const, row, start, length, theta=4095, cols=40, mdl=mdls[ds], vcd_name=f"w{k}.vcd")
    tcl = f"""read_liberty {PW.PDK}/lib/fast_vdd1v0_basicCells.lib
foreach l [glob {Path(a.macro_dir).resolve()}/*.lib] {{ read_liberty $l }}
read_verilog {net}
link_design cim_neurohdc_top
read_sdc {PW.SYNTH}/constraints/cim_neurohdc_top.sdc
read_vcd -scope hdc_gate_tb/dut {d['vcd']}
report_power -instances [get_cells -hierarchical *] > {out}/inst_{k}.rpt
report_power > {out}/tot_{k}.rpt
"""
    (out / f"mp_{k}.tcl").write_text(tcl)
    subprocess.run([str(PW.ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(out / f"mp_{k}.tcl")], capture_output=True, text=True)
    Path(d["vcd"]).unlink(missing_ok=True)
    agg = collections.defaultdict(float)
    for l in open(out / f"inst_{k}.rpt"):
        f = l.split()
        if len(f) == 5 and re.match(r"[\d.e+-]+$", f[3]):
            parts = f[4].split("/")
            key = "/".join(parts[:2]) if parts[0].startswith("u_") and len(parts) > 2 else (parts[0] if len(parts) > 1 else "(top)")
            agg[key] += float(f[3])
    tot = sum(agg.values())
    res[sp] = dict(total_uW=tot * 1e6, modules={kk: v * 1e6 for kk, v in sorted(agg.items(), key=lambda kv: -kv[1])[:16]})
    print(sp, round(tot * 1e6, 1), {kk: round(v * 1e6, 1) for kk, v in sorted(agg.items(), key=lambda kv: -kv[1])[:14]}, flush=True)
(out / "modpower.json").write_text(json.dumps(res, indent=1))
