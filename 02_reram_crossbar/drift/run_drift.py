"""1B Part D sweep: g* versus drift rate for the three strategies at the recommended cell (20 F^2, R_s = 5, no wire yet).

Task = (sigma_lnG, nu_mean, kappa). For each g in G_D:
  S1 headroom      : ok at life 1 y and 10 y
  S2 refresh       : ok for each candidate refresh interval
  S3 ref. cells    : ok for n_ref in REF_CELLS_SWEEP x {abs, ratio}, at life 1 y and 10 y
Writes results/drift/drift_sweep.json. Usage: python -m drift.run_drift [--workers N]
"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import device.constants as C
from drift.strategies import evaluate

OUT = RP.DRIFT_SWEEP_JSON
G_D = (1, 2, 4, 8, 16, 32)
AREA, RS = 20, 5.0
SIGMAS = (0.05, 0.10, 0.15)


def run_task(task):
    sigma, nu, kappa = task
    res = dict(sigma=sigma, nu=nu, kappa=kappa, s1={}, s2={}, s3={})
    for g in G_D:
        for life in C.DRIFT_LIFE_YEARS:
            r = evaluate(g, AREA, RS, sigma, nu, kappa, life, "S1")
            res["s1"][f"{g}|{life}"] = dict(ok=r["ok"], margin=r["worst_margin_frac"], binding=r["worst_binding"])
            for nr in C.REF_CELLS_SWEEP:
                for mode in ("abs", "ratio"):
                    r = evaluate(g, AREA, RS, sigma, nu, kappa, life, "S3", n_ref=nr, ref_mode=mode)
                    res["s3"][f"{g}|{life}|{nr}|{mode}"] = dict(ok=r["ok"], margin=r["worst_margin_frac"], binding=r["worst_binding"])
        for d in C.REFRESH_INTERVALS_DAYS:
            r = evaluate(g, AREA, RS, sigma, nu, kappa, 10.0, "S2", refresh_days=d)
            res["s2"][f"{g}|{d}"] = dict(ok=r["ok"], margin=r["worst_margin_frac"], binding=r["worst_binding"])
    return res


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=8); args = ap.parse_args()
    tasks = [(s, nu, 0.25) for s in SIGMAS for nu in C.NU_MEAN_SWEEP] + [(s, nu, 0.5) for s in SIGMAS for nu in (0.003, 0.01)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(run_task, tasks))
    OUT.write_text(json.dumps(res))
    print("wrote", OUT, len(res), "tasks")


if __name__ == "__main__":
    main()
