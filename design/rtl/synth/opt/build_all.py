#!/usr/bin/env python3
"""Layout + power of one build with the final flow settings (detail-routed, both corners, 100 % annotated activity windows).
  python opt/build_all.py --build full --tag f_full [--util 0.45 --density 0.85]"""
import argparse, subprocess, sys, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--build", required=True); ap.add_argument("--tag", required=True)
ap.add_argument("--util", default="0.45"); ap.add_argument("--density", default="0.85")
ap.add_argument("--stages", default="floorplan place cts groute route"); ap.add_argument("--power", action="store_true")
ap.add_argument("--extra", nargs="*", default=[])
a = ap.parse_args()
py = sys.executable
cmd = [py, str(HERE / "run_flow.py"), "--tag", a.tag, "--build", a.build, "--g", "4", "--util", a.util, "--density", a.density, "--gen-macros", "--dont-use", "*XL", "*X1", "--stages", a.stages, *a.extra]
r = subprocess.run(cmd, text=True, capture_output=True)
print(r.stdout[-1500:], r.stderr[-500:])
if r.returncode:
    sys.exit(r.returncode)
if a.power:
    r = subprocess.run([py, str(HERE / "power.py"), "--tag", a.tag, "--build", a.build, "--stage", "routed", "--instances"], text=True, capture_output=True)
    print(r.stdout[-800:], r.stderr[-300:])
