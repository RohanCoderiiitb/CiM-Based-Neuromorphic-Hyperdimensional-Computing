"""End-to-end Monte Carlo of one PACKED crossbar read (the final design: S = 5 rows per read, 3.5 kohm LRS point): instead of the analytic 5-sigma / half-step check
(op_sweep.levels_and_sigma: device spread only, Gaussian extrapolation) and the separate "row gains within a band match to ~2 %" assumption, every read here draws
  device spread   every + and - device of every active row: log-normal conductance, sigma_lnG (program-verify with 4 averaged verify reads: 0.0453, Phase 1D-ii)
  row gain        every active row its own IR-drop gain, uniform over a spread `--gain-spread` (main case: the WHOLE-macro spread of the 3.5 kohm point, 1.55 %,
                  without the per-column calibration that leaves 0.065 %), applied as a conductance factor of both devices of the row
  front end       Gaussian input-referred current noise with 5 sigma = 1/4 of the smallest level step (the item-9 sizing rule of the read window)
and solves the differential column with the validated Newton solver (1A), then decides the match count with the nearest-level ladder (population-mean levels at sigma, as the
chip's calibrated ladder). Reported: decision errors per read for a = 1..S active rows, with the binomial 95 % upper bound when no error is seen.
   python -m scaleup.mc_packed_read [--n 200000] [--sigma 0.0453] [--gain-spread 0.0155]  -> results/macro_512x32/mc_packed_read.json"""
from __future__ import annotations

import paths as RP

import argparse
import json
import time

import numpy as np

from margin import core as MC
from scaleup import op_sweep as S
from solver.comparator import decide
from solver.newton import solve_differential


def read_errors(p, a: int, n: int, sigma: float, gain_spread: float, noise_frac: float, rng, chunk: int = 20000) -> dict:
    lv = MC.mc_levels(a, a, p, sigma, MC.draw_z(a, 4000), gap_hrs=p.gap_hrs)["mean_diff"]       # the ladder: population-mean levels at this sigma
    step = float(np.min(np.abs(np.diff(lv))))
    sd_fe = noise_frac * step / 5.0
    err = 0; err_by_m = np.zeros(a + 1, int); n_by_m = np.zeros(a + 1, int); worst = 0.0
    for lo in range(0, n, chunk):
        k = min(chunk, n - lo)
        m = rng.integers(0, a + 1, k)
        stored = rng.permuted(np.arange(a)[None, :] < m[:, None], axis=1)                         # which of the a rows hold a match: random positions
        g_row = 1.0 + gain_spread * (rng.random((k, a)) - 0.5)                                    # per-row IR gain, uniform over the spread
        sh = p.g0 * np.log(g_row)                                                                 # conductance x g_row  <=>  gap - g0 ln g_row
        gp = np.where(stored, p.gap_lrs, p.gap_hrs) - p.g0 * sigma * rng.standard_normal((k, a)) - sh
        gm = np.where(stored, p.gap_hrs, p.gap_lrs) - p.g0 * sigma * rng.standard_normal((k, a)) - sh
        i = solve_differential(gp, gm, np.ones((k, a), bool), p).i_diff + sd_fe * rng.standard_normal(k)
        d = decide(i, lv)
        bad = d != m
        err += int(bad.sum())
        np.add.at(err_by_m, m[bad], 1); np.add.at(n_by_m, m, 1)
        worst = max(worst, float((np.abs(i - lv[m]) / (step / 2)).max()))                         # largest deviation from the right level, in half steps (>= 1: error)
    return dict(a=a, n=n, errors=err, error_rate=err / n, upper95=(3.0 / n if err == 0 else None), errors_by_m=err_by_m.tolist(), reads_by_m=n_by_m.tolist(),
                step_uA=step * 1e6, worst_deviation_half_steps=worst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200000, help="reads per active-row count a")
    ap.add_argument("--ron", type=float, default=3500.0)
    ap.add_argument("--s-rows", type=int, default=5)
    ap.add_argument("--sigma", type=float, nargs="+", default=[0.0453, 0.066])
    ap.add_argument("--gain-spread", type=float, nargs="+", default=[0.0, 0.0155, 0.02, 0.04])
    ap.add_argument("--noise-frac", type=float, default=0.25, help="front-end noise: 5 sigma = this fraction of the smallest step")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(RP.MACRO / "mc_packed_read.json"))
    a = ap.parse_args()
    p = S.params(a.ron, S.cell_for(a.ron))
    out = dict(ron=a.ron, s_rows=a.s_rows, n_per_a=a.n, noise_frac=a.noise_frac, seed=a.seed, gap_lrs_nm=float(p.gap_lrs), gap_hrs_nm=float(p.gap_hrs), cases=[])
    for sg in a.sigma:
        for gs in a.gain_spread:
            rng = np.random.default_rng([a.seed, int(sg * 1e4), int(gs * 1e4)])
            t0 = time.time()
            rows = [read_errors(p, k, a.n, sg, gs, a.noise_frac, rng) for k in range(1, a.s_rows + 1)]
            tot = sum(r["errors"] for r in rows); n_tot = sum(r["n"] for r in rows)
            case = dict(sigma_lnG=sg, gain_spread=gs, errors=tot, reads=n_tot, error_rate=tot / n_tot, upper95=(3.0 / n_tot if tot == 0 else None),
                        worst_deviation_half_steps=max(r["worst_deviation_half_steps"] for r in rows), by_a=rows)
            out["cases"].append(case)
            print(f"sigma {sg:.4f} gain spread {gs:.4f}: {tot} errors / {n_tot} reads (rate {tot / n_tot:.2e}{'' if tot else f', < {3.0 / n_tot:.1e} at 95 %'}), "
                  f"worst deviation {case['worst_deviation_half_steps']:.3f} half steps ({time.time() - t0:.0f} s)", flush=True)
            open(a.out, "w").write(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
