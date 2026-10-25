#!/usr/bin/env python3
"""The Yosys netlist of results/ppa_digital/<build> made ready for place-and-route: constants become TIEHI / TIELO cells, `assign` statements become buffers, no expressions. Same logic, same
cells - this is a netlist-format step, not a re-synthesis.   python make_pnr_netlist.py --build full  ->  synth/work/<build>/pnr/netlist.v"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
LIB = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lib" / "fast_vdd1v0_basicCells.lib"
ap = argparse.ArgumentParser()
ap.add_argument("--build", default="full")
a = ap.parse_args()
src = ROOT / "results" / "ppa_digital" / a.build / "cim_neurohdc_top_flat_buf_fast.v"
out = SYNTH / "work" / a.build / "pnr"
out.mkdir(parents=True, exist_ok=True)
ys = out / "netlist.ys"
ys.write_text(f"""read_liberty -lib {LIB}
read_liberty -lib {SYNTH / 'macro' / 'cim_macro.lib'}
read_liberty -lib {SYNTH / 'macro' / ('hdc_class_array_fact.lib' if a.build in ('full', 'ee_off') else 'hdc_class_array_unfact.lib')}
read_verilog {src}
hierarchy -check -top cim_neurohdc_top
hilomap -singleton -hicell TIEHI Y -locell TIELO Y
insbuf -buf BUFX2 A Y
opt_clean -purge
stat
write_verilog -noattr -noexpr -nohex -nodec {out / 'netlist.v'}
""")
r = subprocess.run(["yosys", "-q", "-l", str(out / "netlist.log"), str(ys)], capture_output=True, text=True)
txt = (out / "netlist.v").read_text() if (out / "netlist.v").exists() else ""
print(f"[{a.build}] {'OK' if r.returncode == 0 else 'FAILED'}: {out / 'netlist.v'}  assigns left: {txt.count('assign ')}  TIEHI/TIELO: {txt.count('TIEHI ')}/{txt.count('TIELO ')}  buffers inserted for assigns: {txt.count('BUFX2 ') }")
if r.returncode:
    print((r.stdout + r.stderr)[-800:])
sys.exit(r.returncode)
