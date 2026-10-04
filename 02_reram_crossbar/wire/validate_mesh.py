"""Validate the 2-D mesh solver against ngspice on small arrays, exhaustively in the active-row count (1B C1).

Arrays (rows x columns): 16x8, 32x8, 64x16. For every active count a = 1..R and four activation patterns (rows nearest the sense node, rows farthest,
two random subsets), random 2T2R weights (complementary LRS/HRS per column pair) with log-normal spread, and two wire settings (a realistic and a
deliberately exaggerated one to stress the nodal equations). Reports the WORST disagreement:
  primary:   |dI_col| / I_col            (column currents are strictly positive for a >= 1, so this is well conditioned)
  secondary: |dI_diff| / max(I+, I-)     (1A's primary metric, per 2T2R column pair)
Writes results/wire_resistance/mesh_vs_ngspice_validation.csv (resumable).

Usage: python -m wire.validate_mesh
"""
from __future__ import annotations

import paths as RP

import csv
import time
from pathlib import Path

import numpy as np

import device.constants as C
from device.constants import DEFAULT
from wire.mesh import solve_mesh
from wire.netlist import run_mesh_ngspice

ROOT = Path(__file__).resolve().parents[1]
OUT = RP.MESH_VALIDATION_CSV
ARRAYS = ((16, 8), (32, 8), (64, 16))
WIRE_SETTINGS = ((0.72, 0.72, 10.0), (5.0, 5.0, 100.0))        # (r_bl, r_wl, r_drv): realistic upper end; exaggerated stress
SIGMA = 0.10
N_WEIGHT_DRAWS = 2
FIELDS = ["R", "K", "a", "pattern", "draw", "r_bl", "r_wl", "r_drv", "rel_col", "rel_diff_scale", "iters", "residual_a", "mesh_s", "ngspice_s"]


def patterns(R: int, a: int, rng) -> dict[str, np.ndarray]:
    near = np.zeros(R, bool); near[:a] = True
    far = np.zeros(R, bool); far[R - a:] = True
    r1 = np.zeros(R, bool); r1[rng.choice(R, a, replace=False)] = True
    r2 = np.zeros(R, bool); r2[rng.choice(R, a, replace=False)] = True
    return {"near": near, "far": far, "rand1": r1, "rand2": r2}


def draw_gaps(R: int, K: int, rng) -> np.ndarray:
    w = rng.integers(0, 2, (R, K // 2)).astype(bool)
    stored = np.repeat(w, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)      # even column: LRS if w; odd column: complementary
    nom = np.where(stored, DEFAULT.gap_lrs, DEFAULT.gap_hrs)
    return nom - DEFAULT.g0 * SIGMA * rng.standard_normal((R, K))


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if OUT.exists():
        with OUT.open() as f:
            done = {(int(r["R"]), int(r["K"]), int(r["a"]), r["pattern"], int(r["draw"]), float(r["r_bl"])) for r in csv.DictReader(f)}
    new = not OUT.exists()
    fh = OUT.open("a", newline="")
    w = csv.DictWriter(fh, FIELDS)
    if new:
        w.writeheader()
    p = DEFAULT
    for (R, K) in ARRAYS:
        for (rbl, rwl, rdrv) in WIRE_SETTINGS:
            for a in range(1, R + 1):
                for d in range(N_WEIGHT_DRAWS):
                    rng = np.random.default_rng([R, K, a, d])
                    gaps = draw_gaps(R, K, rng)
                    for name, act in patterns(R, a, rng).items():
                        if (R, K, a, name, d, rbl) in done:
                            continue
                        rows = np.flatnonzero(act)
                        t0 = time.perf_counter()
                        m = solve_mesh(gaps[rows], rows + 1.0, p, r_bl=rbl, r_wl=rwl, r_drv=rdrv)
                        t1 = time.perf_counter()
                        ref = run_mesh_ngspice(gaps, act, p, r_bl=rbl, r_wl=rwl, r_drv=rdrv)
                        t2 = time.perf_counter()
                        rel = np.abs(m.i_col / ref - 1)
                        ip, im = m.i_col[0::2], m.i_col[1::2]
                        rp, rm = ref[0::2], ref[1::2]
                        sc = np.maximum(np.maximum(rp, rm), 1e-300)
                        dd = np.abs((ip - im) - (rp - rm)) / sc
                        w.writerow(dict(R=R, K=K, a=a, pattern=name, draw=d, r_bl=rbl, r_wl=rwl, r_drv=rdrv, rel_col=float(rel.max()),
                                        rel_diff_scale=float(dd.max()), iters=m.iters, residual_a=m.residual, mesh_s=t1 - t0, ngspice_s=t2 - t1))
                        fh.flush()
            print(f"{R}x{K} wire {rbl}/{rwl}/{rdrv} done", flush=True)
    fh.close()
    rows = list(csv.DictReader(OUT.open()))
    wc = max(float(r["rel_col"]) for r in rows); wd = max(float(r["rel_diff_scale"]) for r in rows)
    print(f"cases={len(rows)} worst rel column current={wc:.3e}  worst scale-normalised I_diff={wd:.3e}  threshold={C.ACCEPT_REL_DIFF:.0e}")
    return 0 if max(wc, wd) < C.ACCEPT_REL_DIFF else 1


if __name__ == "__main__":
    raise SystemExit(main())
