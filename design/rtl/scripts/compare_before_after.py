#!/usr/bin/env python3
"""Bit-exactness of the digital-energy pass: every canonical regression log of the Phase 2-5 RTL (a saved copy of results/hdc/ from before the pass) against the same configuration re-run
on the modified RTL. The canonical log carries EVERY timestep (spikes, X, V, the SNN's per-timestep counters, the N scores, leader, second score, fire flag, rows gated) and every sample's END
record (cycles, events ingested, prediction, early flag, exit timestep, reload cycles), so equal logs mean every functional number is unchanged, not only the headline ones.

  compare_before_after.py --before <dir with the old results/hdc>   -> results/hdc/before_after.json; exit status 1 on any difference
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "results" / "hdc"
SAMPLE_KEYS = ("row", "pred", "exit_tstep", "n_timesteps", "events_ingested", "cycles_inf", "cycles_query", "stall_cycles", "idle_cycles", "reload_cycles", "group_reads_allcols",
               "group_reads_issued", "zero_groups", "rows_gated_total", "raster_hash", "ok")
SUMMARY_KEYS = ("samples", "mismatching_samples", "accuracy", "mean_exit_tstep", "mean_cycles_inf", "mean_events_ingested")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    a = ap.parse_args()
    before = Path(a.before)
    rows, bad, skipped = [], 0, []
    for f in sorted(before.glob("*.out.txt.gz")):
        tag = f.name[: -len(".out.txt.gz")]
        if tag.startswith(("zz_", "e0_")):
            continue
        g = NEW / f.name
        rec = dict(tag=tag)
        if not g.exists():
            rec.update(status="not re-run (reduced scope)")
            skipped.append(tag)
            rows.append(rec)
            continue
        A = gzip.open(f, "rt").read().splitlines()
        B = gzip.open(g, "rt").read().splitlines()
        n_ts = sum(1 for line in A if line.startswith("TS"))
        diff = [(i, x[:120], y[:120]) for i, (x, y) in enumerate(zip(A, B)) if x != y]
        rec.update(lines_before=len(A), lines_after=len(B), timesteps=n_ts, differing_lines=len(diff) + abs(len(A) - len(B)), first=diff[:2])
        ja, jb = json.loads((before / f"{tag}.json").read_text()), json.loads((NEW / f"{tag}.json").read_text())
        rec["summary_equal"] = all(ja["summary"].get(k) == jb["summary"].get(k) for k in SUMMARY_KEYS)
        rec["per_sample_equal"] = len(ja["samples"]) == len(jb["samples"]) and all(
            {k: x.get(k) for k in SAMPLE_KEYS if k in x} == {k: y.get(k) for k in SAMPLE_KEYS if k in x} for x, y in zip(ja["samples"], jb["samples"]))        # keys the old JSON never recorded (zero_groups) are not compared
        rec["status"] = "IDENTICAL" if rec["differing_lines"] == 0 and rec["summary_equal"] and rec["per_sample_equal"] else "DIFFERENT"
        bad += rec["status"] != "IDENTICAL"
        rows.append(rec)
    tot_ts = sum(r.get("timesteps", 0) for r in rows)
    out = dict(configurations=len(rows) - len(skipped), identical=sum(r["status"] == "IDENTICAL" for r in rows), different_or_missing=bad, not_re_run=len(skipped), timesteps_compared=tot_ts, rows=rows)
    (NEW / "before_after.json").write_text(json.dumps(out, indent=1))
    print(f"{out['identical']}/{out['configurations']} configurations bit-identical to the Phase 2-5 logs, {tot_ts:,} timesteps compared line by line, {bad} not identical ({len(skipped)} old configurations not re-run)")
    for r in rows:
        if r["status"] != "IDENTICAL":
            print("  ", r["tag"], r["status"], r.get("first"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
