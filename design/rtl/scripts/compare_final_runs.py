#!/usr/bin/env python3
"""Bit-identity of two regression result directories (results/<old>, results/<new>): every sample record (prediction, exit timestep, events, cycles, reads, raster hash ...) and the summary's functional fields must be equal.
   python scripts/compare_final_runs.py hdc_final hdc_final2"""
import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "results"
old, new = R / sys.argv[1], R / sys.argv[2]
FIELDS = ("samples", "mismatching_samples", "accuracy", "mean_exit_tstep", "mean_cycles_inf", "mean_events_ingested", "assert_fail_messages")
n = bad = 0
for f in sorted(new.glob("*.json")):
    o = old / f.name
    if not o.exists() or f.name.endswith("timesteps.jsonl.gz"):
        continue
    a, b = json.loads(o.read_text()), json.loads(f.read_text())
    if "summary" not in a or "summary" not in b:
        continue
    n += 1
    diff = [k for k in FIELDS if (a["summary"].get(k) != b["summary"].get(k) if k != "samples" else False)]
    if a["samples"] != b["samples"]:
        diff.append("sample records")
    if diff:
        bad += 1
        print("DIFF", f.name, diff)
print(f"{n} result files compared, {bad} differ")
