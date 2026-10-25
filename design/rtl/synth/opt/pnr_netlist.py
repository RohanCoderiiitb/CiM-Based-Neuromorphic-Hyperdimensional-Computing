#!/usr/bin/env python3
"""Netlist-format step before place-and-route (no re-synthesis): constants -> TIEHI/TIELO cells, `assign`s -> buffers, no expressions.
  python pnr_netlist.py --net <netlist.v> --macro-lib <lib>... --out <netlist_pnr.v>"""
import argparse
import subprocess
import sys
from pathlib import Path

SYNTH = Path(__file__).resolve().parents[1]
PDK = SYNTH.parents[2] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lib"
ap = argparse.ArgumentParser()
ap.add_argument("--net", required=True)
ap.add_argument("--macro-lib", nargs="+", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--top", default="cim_neurohdc_top")
a = ap.parse_args()
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
ys = out.with_suffix(".ys")
ys.write_text("\n".join([f"read_liberty -lib {PDK / 'fast_vdd1v0_basicCells.lib'}", *(f"read_liberty -lib {m}" for m in a.macro_lib), f"read_verilog {a.net}", f"hierarchy -check -top {a.top}",
                         "hilomap -singleton -hicell TIEHI Y -locell TIELO Y", "insbuf -buf BUFX2 A Y", "opt_clean -purge", "stat", f"write_verilog -noattr -noexpr -nohex -nodec {out}"]) + "\n")
r = subprocess.run(["yosys", "-q", "-l", str(out.with_suffix(".log")), str(ys)], capture_output=True, text=True)
txt = out.read_text() if out.exists() else ""
print(f"{'OK' if r.returncode == 0 else 'FAILED'}: {out}  assigns left: {txt.count('assign ')}  TIEHI/TIELO: {txt.count('TIEHI ')}/{txt.count('TIELO ')}")
if r.returncode:
    print((r.stdout + r.stderr)[-800:])
sys.exit(r.returncode)
