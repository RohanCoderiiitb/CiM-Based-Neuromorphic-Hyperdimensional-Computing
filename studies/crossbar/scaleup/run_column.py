"""C1 (a)-(c): all 64 groups of one column, level profile, per-group ladder table, size, antisymmetry; then the accumulation test.
Usage: python -m scaleup.run_column [--workers N] [--n-fit 40]"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import device.constants as C
from scaleup.column import build_group_table, n_groups

G = C.G_1C


def _task(a):
    g, Gi, r, nf = a
    return build_group_table(g, Gi, r, n_fit=nf, n_held=nf)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=9); ap.add_argument("--n-fit", type=int, default=40); args = ap.parse_args()
    RP.FULL_COLUMN.mkdir(parents=True, exist_ok=True)
    for r in C.BL_R_PER_PITCH_SWEEP:
        jobs = [(G, Gi, r, args.n_fit) for Gi in range(n_groups(G))]
        with ProcessPoolExecutor(args.workers) as ex:
            tabs = list(ex.map(_task, jobs, chunksize=2))
        RP.full_column_tables(r).write_text(json.dumps(tabs))
        span = np.array([t["span"] for t in tabs]); step = np.array([t["worst_step_full"] for t in tabs])
        print(f"r={r}: span {span[0]*1e6:.1f} -> {span[-1]*1e6:.1f} uA, step {step[0]*1e6:.1f} -> {step[-1]*1e6:.1f} uA, monotone span {np.all(np.diff(span) < 0)} step {np.all(np.diff(step) < 0)}", flush=True)


if __name__ == "__main__":
    main()
