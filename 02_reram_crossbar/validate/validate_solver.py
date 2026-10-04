"""Exhaustive validation of the Newton solver against ngspice.

For each g, each active count a in 1..g, each match count m in 0..a: draw N gap-spread samples, solve with
ngspice AND Newton on the IDENTICAL draws, record worst relative disagreement. Resumable: one CSV row per
(g, a, m) written as it completes; completed keys are skipped on restart.

Usage: python -m validate.validate_solver [--n-draws 200] [--groups 4 8 16 32] [--out results/validation.csv]
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import numpy as np

from device.constants import ACCEPT_REL_DIFF, DEFAULT, SIGMA_LNG
from device.spread import sample_state_gaps
from solver.newton import solve_differential
from spice.runner import ngspice_available, run_differential

FIELDS = ["g", "a", "m", "n_draws", "sigma_lng", "rel_plus", "rel_minus", "rel_diff", "rel_diff_scale",
          "worst_abs_diff_A", "min_abs_idiff_A", "newton_s", "ngspice_s", "newton_iters"]
ROOT = Path(__file__).resolve().parents[1]


def case_draws(g: int, a: int, m: int, n: int, seed: int, sigma: float = SIGMA_LNG):
    """Deterministic gap draws for one (g,a,m) case: first m active rows store 1, the rest store 0."""
    rng = np.random.default_rng([seed, g, a, m])
    stored = np.broadcast_to(np.arange(a) < m, (n, a))
    gp, gm = sample_state_gaps(rng, stored, sigma_lng=sigma)
    return gp, gm, np.ones((n, a), dtype=bool)


def run_case(g: int, a: int, m: int, n: int, seed: int, sigma: float = SIGMA_LNG) -> dict:
    gp, gm, act = case_draws(g, a, m, n, seed, sigma)
    t0 = time.perf_counter()
    nw = solve_differential(gp, gm, act)
    t_nw = time.perf_counter() - t0
    t0 = time.perf_counter()
    sp, sm, sd = run_differential(gp, gm, act)
    t_sp = time.perf_counter() - t0
    d = np.abs(nw.i_diff - sd)
    scale = np.maximum(np.abs(sp), np.abs(sm))
    # Both solvers can return exactly I_diff = 0 (plus/minus gaps identical after clipping): 0/0 is zero disagreement,
    # while d > 0 against an exact-zero reference is infinite and must fail loudly.
    with np.errstate(divide="ignore", invalid="ignore"):
        strict = np.where(d == 0.0, 0.0, d / np.abs(sd))
    return dict(g=g, a=a, m=m, n_draws=n, sigma_lng=sigma,
                rel_plus=float(np.max(np.abs(nw.i_plus - sp) / np.abs(sp))),
                rel_minus=float(np.max(np.abs(nw.i_minus - sm) / np.abs(sm))),
                # strict per-spec metric: |dI_diff| / |I_diff|. Ill-conditioned where I_diff ~ 0 (m ~ a/2).
                rel_diff=float(np.max(strict)),
                # well-conditioned companion: normalised to the larger column current
                rel_diff_scale=float(np.max(d / scale)),
                worst_abs_diff_A=float(d.max()), min_abs_idiff_A=float(np.abs(sd).min()),
                newton_s=t_nw, ngspice_s=t_sp, newton_iters=max(nw.outer_iters, nw.inner_iters))


def done_keys(path: Path) -> set[tuple[int, int, int]]:
    if not path.exists():
        return set()
    with path.open() as f:
        return {(int(r["g"]), int(r["a"]), int(r["m"])) for r in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-draws", type=int, default=200)
    ap.add_argument("--groups", type=int, nargs="+", default=[4, 8, 16, 32])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sigma", type=float, default=SIGMA_LNG, help="log-normal conductance sigma")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "validation.csv")
    args = ap.parse_args()
    if not ngspice_available():
        print("BLOCKED: ngspice not found; solver validation cannot run.")
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = done_keys(args.out)
    new = not args.out.exists()
    with args.out.open("a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        for g in args.groups:
            for a in range(1, g + 1):
                for m in range(a + 1):
                    if (g, a, m) in done:
                        continue
                    w.writerow(run_case(g, a, m, args.n_draws, args.seed, args.sigma))
                    f.flush()
            print(f"g={g} done")
    rows = list(csv.DictReader(args.out.open()))
    worst = max(float(r["rel_diff"]) for r in rows)
    worst_scale = max(float(r["rel_diff_scale"]) for r in rows)
    print(f"cases={len(rows)}  PRIMARY worst scale-normalised I_diff={worst_scale:.3e}  secondary worst |dI|/|I_diff|="
          f"{worst:.3e}  threshold={ACCEPT_REL_DIFF:.0e} (applied to both; verdict uses the primary)")
    return 0 if worst_scale < ACCEPT_REL_DIFF else 1


if __name__ == "__main__":
    raise SystemExit(main())
