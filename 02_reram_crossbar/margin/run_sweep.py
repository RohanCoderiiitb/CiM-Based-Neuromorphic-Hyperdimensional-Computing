"""1B-i main sweep: every (g, cell area, R_s, sigma_lnG) point evaluated against the budget. Writes results/margin_budget/g_surface_points.csv.

sigma in {0, .05, .10, .15, .20}; g in G_SWEEP; area in AREA_SWEEP_F2; R_s in R_S_SWEEP. Common random numbers are shared across
(sigma, R_s, area) at each g. Resumable: finished (g, area, r_s, sigma) keys are skipped.

Usage: python -m margin.run_sweep [--draws 1000]
"""
from __future__ import annotations

import paths as RP

import argparse
import csv
import time
from pathlib import Path

import device.constants as C
from margin.core import draw_z
from margin.point import evaluate_point

OUT = RP.SURFACE_POINTS_CSV


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=C.MC_DRAWS)
    ap.add_argument("--sigmas", type=float, nargs="+", default=list(C.SIGMA_LNG_SWEEP))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    OUT_, SIGMAS = args.out, args.sigmas
    OUT_.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT_.exists():
        with OUT_.open() as f:
            done = {(int(r["g"]), int(r["area"]), float(r["r_s"]), float(r["sigma"])) for r in csv.DictReader(f)}
    writer, fh = None, OUT_.open("a", newline="")
    t0 = time.time()
    for g in C.G_SWEEP:
        z = draw_z(g, args.draws)
        for area in C.AREA_SWEEP_F2:
            for r_s in C.R_S_SWEEP:
                for sg in SIGMAS:
                    if (g, area, r_s, sg) in done:
                        continue
                    row = evaluate_point(g, area, r_s, sg, n=args.draws, z=z)
                    if writer is None:
                        writer = csv.DictWriter(fh, list(row)); 
                        if OUT_.stat().st_size == 0:
                            writer.writeheader()
                    writer.writerow(row); fh.flush()
        print(f"g={g} done  ({time.time() - t0:.0f} s)", flush=True)
    fh.close()


if __name__ == "__main__":
    main()
