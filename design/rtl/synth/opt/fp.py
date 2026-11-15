#!/usr/bin/env python3
"""Floorplan parameters for the optimised flow: crossbar macro on top, the digital region under it against the macro's pin edge (as the earlier flow), the class-array macro inside the
digital region. UTIL is the target density of the digital region (macros excluded). Writes <out>/fp.tcl.   python fp.py --cells <um2> --util 0.6 --macro-dir <dir> --out <dir>"""
import argparse
import math
import re
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--cells", type=float, required=True, help="standard-cell area of the netlist, um^2")
ap.add_argument("--util", type=float, default=0.6)
ap.add_argument("--margin", type=float, default=10.0)
ap.add_argument("--macro-dir", required=True)
ap.add_argument("--extra-macros", nargs="*", default=[], help="name:W:H of additional macros kept inside the digital region (e.g. count_sram)")
ap.add_argument("--core-w", type=float, default=None, help="width of the standard-cell core (default: the macro width); a narrower core keeps the logic compact under the macro pins")
ap.add_argument("--out", required=True)
a = ap.parse_args()


def size(lef: Path) -> tuple[float, float]:
    m = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", lef.read_text())
    return float(m.group(1)), float(m.group(2))


md = Path(a.macro_dir)
cw, ch = size(md / "cim_macro.lef")
hw, hh = size(md / "hdc_class_array.lef")
extra = [(n, float(w), float(h)) for n, w, h in (s.split(":") for s in a.extra_macros)]
ROW = 1.71
m = a.margin
core_y0 = math.ceil(m / ROW) * ROW
macro_area = hw * hh * 1.2 + sum(w * h * 1.3 for _, w, h in extra)
cwid = min(a.core_w, cw) if a.core_w else cw
dig_h = (a.cells / a.util + macro_area) / cwid
if hh > 150:      # a tall class array (the unfactorised ablation) would otherwise split the logic into two side strips and force wires of >1 mm around it: keep a full-width band of cells above it
    dig_h = max(dig_h, hh * 1.2 + 150)
W = cw + 2 * m
cim_y = math.ceil((core_y0 + dig_h) / ROW) * ROW
H = cim_y + ch + m
lines = [f"set IO_W {min(cwid, 450.0):.1f}", f"set CORE_W {cwid + 0:.2f}", f"set DIE_W {W:.2f}", f"set DIE_H {H:.2f}", f"set MARGIN {m:.1f}", f"set CIM_X {m:.2f}", f"set CIM_Y {cim_y:.2f}", f"set UTIL_TARGET {a.util}"]
# bottom of the digital region: the counter-bank block, then the stretch of the bottom edge that holds the event (AER) pins (the ingest stage sits between its pins and its memories),
# then ONE COLUMN with the other small macros and the class array stacked (a row of them does not fit under a narrow crossbar; a macro off the core leaves its pins unreachable)
x = m + 5
EV_W = 150.0
col = []
for n, w, h in extra:
    if n == "count_sram":
        # FP_CNT_YFRAC (the large chip, default 0 = bottom): the block is raised by this fraction of the free height, so the scan logic between it and the crossbar's
        # bit-plane sequencer is not stretched over the whole (tall) digital region
        yf = float(__import__("os").environ.get("FP_CNT_YFRAC", "0"))
        lines.append(f"set MAC_{n}_X {x:.2f}\nset MAC_{n}_Y {core_y0 + 5 + yf * max(0.0, dig_h - h - 10):.2f}")
        x += w + 10
        lines.append(f"set EV_X0 {x:.2f}\nset EV_X1 {x + EV_W:.2f}")
        x += EV_W + 10
    else:
        col.append((n, w, h))
col.append(("HDC", hw, hh))
colw = max(w for _, w, _ in col)
if x + colw > m + cw:
    x = m + cw - colw - 5
import os
if os.environ.get("FP_COL_TOP") == "1":     # the large chip: the column hangs from the top of the digital region (under the crossbar), against the right edge; with HDC_ORI=MX (flow.tcl) the class memory's
    x = m + cw - colw - 5                      # pin edge (the LEF top) is mirrored to face the logic, and its write port is near the right-edge class-image pins (flow.tcl CM_PINS_RIGHT)
    y = cim_y - 10
    for n, w, h in col:
        y -= h
        lines.append(f"set HDC_X {x:.2f}\nset HDC_Y {y:.2f}" if n == "HDC" else f"set MAC_{n}_X {x:.2f}\nset MAC_{n}_Y {y:.2f}")
        y -= 10
    col = []
    y = core_y0
y = core_y0 + 5 if col else y
for n, w, h in col:
    lines.append(f"set HDC_X {x:.2f}\nset HDC_Y {y:.2f}" if n == "HDC" else f"set MAC_{n}_X {x:.2f}\nset MAC_{n}_Y {y:.2f}")
    y += h + 10
if y > cim_y:
    raise SystemExit(f"fp: the macro column ({y:.0f} um) does not fit under the crossbar ({cim_y:.0f} um)")
Path(a.out).mkdir(parents=True, exist_ok=True)
Path(a.out, "fp.tcl").write_text("\n".join(lines) + "\n")
print(f"die {W:.0f} x {H:.0f} um = {W * H * 1e-6:.4f} mm^2; digital region {cwid:.0f} x {dig_h:.0f} for {a.cells:,.0f} um^2 of cells + macros at util {a.util}")
