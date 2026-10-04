"""Row-line / driver IR across K columns (the part of the 2-D mesh a single pair cannot show).

Each active row's V_read reaches column j through R_DRV and j row-line segments, and carries the current of EVERY cell on that row, so a row's droop depends on the
weights of the other columns - static after programming, but different for every row. Measured as the change of one pair's I_diff when it sits in a K-column array
versus alone (K = 2) with the same activation and weights for that pair; the other pairs' weights are random.
  mean   : weight-independent part for that column position (correctable per column / absorbed in the ladder)
  spread : variation with the other columns' weights (NOT correctable by a constant) -> the budget term
Group: the FAR contiguous group (bitline effect included, it is the worst), a = g, match pattern random.
Usage: python -m wire.rowside [--workers N]
"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import device.constants as C
from margin.core import params_for
from wire.decompose import AREA, RS, group_rows
from wire.mesh import solve_mesh

OUT = RP.ROW_LINE_JSON
R_WIRE = 0.72


N_OWN = 8        # own-pair activation patterns
N_OTHER = 10     # random weight draws for the OTHER columns per own pattern


def task(cfg: tuple) -> dict:
    """For each own pattern (S = all g rows, random w for the pair of interest) draw N_OTHER random weight sets for the other pairs.
      gain      : slope of mean_over_others(d_full) vs d_alone through the origin = a per-column-position constant (correctable: per-column ladder scale)
      uncorr    : spread of d_full ACROSS the other columns' weights for a fixed own pattern (not correctable by any constant): std and max deviation
    """
    g, K, rdrv, pos_name = cfg
    p = params_for(AREA, RS)
    rows = group_rows("contiguous", g, C.ROWS_TOTAL // g - 1)
    pairs = K // 2
    pi = {"first": 0, "mid": pairs // 2, "last": pairs - 1}[pos_name]
    rng = np.random.default_rng([C.WIRE_SEED, g, K, int(rdrv), pi])
    stds, maxdevs, means, alones = [], [], [], []
    for _ in range(N_OWN):
        w_own = rng.integers(0, 2, g).astype(bool)
        vals = []
        for _ in range(N_OTHER):
            W = rng.integers(0, 2, (g, pairs)).astype(bool)
            W[:, pi] = w_own
            stored = np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)
            full = solve_mesh(np.where(stored, p.gap_lrs, p.gap_hrs), rows + 1.0, p, r_bl=R_WIRE, r_wl=R_WIRE, r_drv=rdrv)
            vals.append(full.i_col[2 * pi] - full.i_col[2 * pi + 1])
        st = np.stack([w_own, ~w_own], axis=1)
        al = solve_mesh(np.where(st, p.gap_lrs, p.gap_hrs), rows + 1.0, p, r_bl=R_WIRE, r_wl=R_WIRE, r_drv=rdrv)
        alones.append(al.i_col[0] - al.i_col[1]); v = np.array(vals); means.append(v.mean()); stds.append(v.std(ddof=1)); maxdevs.append(np.abs(v - v.mean()).max())
    al_a, mn = np.array(alones), np.array(means)
    gain = float((al_a * mn).sum() / (al_a * al_a).sum())
    return dict(g=g, K=K, r_drv=rdrv, pos=pos_name, gain=gain, gain_error=1 - gain, gain_resid_a=float(np.abs(mn - gain * al_a).max()),
                uncorr_std_a=float(np.max(stds)), uncorr_std_rms_a=float(np.sqrt(np.mean(np.square(stds)))), uncorr_maxdev_a=float(np.max(maxdevs)))


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=8); args = ap.parse_args()
    cfgs = [(g, K, rd, pos) for g in (8, 16) for K in (C.MACRO_COLS, C.FULL_COLS) for rd in C.R_DRV_SWEEP for pos in ("first", "mid", "last")]
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(task, cfgs))
    OUT.write_text(json.dumps(res, indent=1))
    for r in res:
        print(r["g"], r["K"], r["r_drv"], r["pos"], "gain err %.3f  uncorr std %.3f uA maxdev %.3f uA" % (r["gain_error"], r["uncorr_std_a"] * 1e6, r["uncorr_maxdev_a"] * 1e6), flush=True)


if __name__ == "__main__":
    main()
