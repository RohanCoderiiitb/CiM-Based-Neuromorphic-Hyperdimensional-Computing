#!/usr/bin/env python3
"""Compare the canonical raw logs of two Phase 2-4 regression runs line by line (every timestep: spikes, X, V, SNN counters, N scores, leader, second score, fire flag, rows
gated; and every END record: cycles, events ingested, prediction, early flag, exit timestep). Used for Verilator vs Icarus and for build vs build (early exit disabled vs
EARLY_EXIT_EN = 0; factorized vs unfactorized with the expanded class hypervector - the latter compares only the columns both builds share, see --cols).

  compare_hdc_runs.py A.out.txt.gz B.out.txt.gz [--tag NAME]   -> exit 0 iff identical; writes results/hdc/compare_<tag>.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    with gzip.open(path, "rt") as fh:
        return fh.read().splitlines()


def compare(a: str, b: str, tag: str | None = None, skip: set[int] | None = None) -> dict:
    skip = skip or set()
    A, B = read(a), read(b)
    n_ts = sum(1 for l in A if l.startswith("TS"))
    bad = []
    if len(A) != len(B):
        bad.append(("line count", len(A), len(B)))
    for i, (x, y) in enumerate(zip(A, B)):
        if x.startswith("END") and skip:
            fx, fy = x.split(), y.split()
            x = " ".join(f for k, f in enumerate(fx) if (k - 2) not in skip)
            y = " ".join(f for k, f in enumerate(fy) if (k - 2) not in skip)
        if x != y:
            bad.append((i, x[:160], y[:160]))
            if len(bad) > 5:
                break
    res = dict(a=str(a), b=str(b), lines=len(A), timesteps_compared=n_ts, disagreements=len(bad), first=bad[:3], verdict="AGREE" if not bad else "DISAGREE")
    tag = tag or (Path(a).name.split(".")[0] + "__vs__" + Path(b).name.split(".")[0])
    (ROOT / "results" / "hdc" / f"compare_{tag}.json").write_text(json.dumps(res, indent=1))
    res["tag"] = tag
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--skip-end-fields", default="", help="comma list of END field indices (0-based after 'END row') to ignore, e.g. the reload cycles (13)")
    args = ap.parse_args()
    res = compare(args.a, args.b, args.tag, {int(x) for x in args.skip_end_fields.split(",") if x})
    print(f"[{res['verdict']}] {res['tag']}: {res['timesteps_compared']} timesteps ({res['lines']} lines) compared, {res['disagreements']} disagreements")
    return 0 if not res["disagreements"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
