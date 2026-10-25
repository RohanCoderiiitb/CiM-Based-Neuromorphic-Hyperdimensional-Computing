#!/usr/bin/env python3
"""Cheap check after every RTL change: ONE sample, ONE seed, the full build, Verilator only (seconds). Runs the regression harness on the sample (which compares every timestep with the golden
model) AND diffs every functional field of the DUT's log - spikes, X, V, prefix scores, top-1/top-2, fire, and the END record's prediction / exit timestep / events ingested / assertion bits -
against the log of the unmodified RTL (results/hdc/ab_full_g4_s0, run on the commit before the optimisation). Cycle and read counters are NOT compared (they may change).
  python scripts/smoke_check.py [--rows 46] [--g 4] [--args '--early-exit 1 ...']"""
import argparse
import gzip
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "results" / "hdc" / "ab_full_g4_s0.out.txt.gz"
ap = argparse.ArgumentParser()
ap.add_argument("--rows", default="46")
ap.add_argument("--g", type=int, default=4)
ap.add_argument("--extra", nargs="*", default=[])
a = ap.parse_args()
cmd = [str(ROOT.parents[1] / "venv" / "bin" / "python"), str(ROOT / "scripts" / "run_hdc_regression.py"), "--model", "r1", "--seed", "0", "--factorized", "1", "--early-exit", "1", "--theta", "50",
       "--rows", a.rows, "--g", str(a.g), "--sim", "verilator", "--tag", "smoke", *a.extra]
r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
print(r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr[-800:])
rows = set(a.rows.split(","))
ref = {}
for line in gzip.open(REF, "rt"):
    f = line.split()
    if f[1] in rows:
        ref.setdefault(f[1], []).append(f)
got = {}
for line in gzip.open(ROOT / "results" / "hdc" / "smoke.out.txt.gz", "rt"):
    f = line.split()
    got.setdefault(f[1], []).append(f)
STAT = range(44, 55)           # TS fields 44..54 are the eleven access / cycle counters
END_FUNC = (5, 8, 9, 10, 11, 12, 13, 14)       # events_ingested, events_total, errors, hdc_errors, ts_seen, pred, early, pred_tstep  (END <s> then 15 fields)
bad = 0
for row in sorted(rows, key=int):
    A, B = ref.get(row, []), got.get(row, [])
    if len(A) != len(B):
        print(f"row {row}: {len(B)} records, reference {len(A)}"); bad += 1; continue
    for x, y in zip(A, B):
        if x[0] == "TS":
            fx = [v for i, v in enumerate(x) if i not in STAT]
            fy = [v for i, v in enumerate(y) if i not in STAT]
        else:
            fx = [x[i] for i in END_FUNC if i < len(x)]
            fy = [y[i] for i in END_FUNC if i < len(y)]
        if fx != fy:
            print(f"row {row}: first functional difference in {' '.join(x[:3])}"); bad += 1; break
    else:
        e = [v for v in B if v[0] == "END"][0]
        print(f"row {row}: {len(B) - 1} timesteps identical to the reference in every functional field; cycles {e[2]} (reference {[v for v in A if v[0] == 'END'][0][2]})")
sys.exit(1 if bad or r.returncode else 0)
