"""Optimisation item 7: can the row-line gain variation be removed by metal instead of by the digital rank-3 threshold correction?
The correction exists because the row-line gain of column c depends on the group G and on the number of active rows a (row-line IR). Here the true macro (32 cells per row, driver at both
ends, ideal rails, g = 4, 128 groups) is solved on the mesh for a sweep of the row-line resistance PER CELL, the gain matrix s[c, (G, a)] is built, and for every point:
  gain min / max, the residual left by a per-column scale only (rank 0: static, no per-read arithmetic), by a rank-1, rank-2, rank-3 separable correction (rank k = k multiplies per read per position),
  and the lowest rank whose max residual is below (A) the margin the budget has left at the g = 4 design point and (B) the 10-bit threshold quantisation.
r_wl is in ohm per cell. 1C's 0.72 ohm/pitch is for the 5 F wide (20 F^2) cell; the chip-level macro uses the 128 F wide cell the write path needs, whose row line is 25.6x longer per cell at the same
metal: 18.43 ohm per cell. The sweep covers both.   Usage: python -m scaleup.run_rowline_metal [--procs 6]"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import device.constants as C
from scaleup.droop import macro_stats

G_ROWS = 4
GROUPS = tuple(range(0, 128, 8)) + (127,)
CELLS = tuple(range(0, 32, 2)) + (31,)
A_VALUES = (1, 2, 3, 4)
R_WL = (18.43, 9.22, 4.61, 2.30, 1.15, 0.72, 0.36, 0.18, 0.09, 0.045)
R_DRV = 10.0


def job(args):
    rwl, G, c, a, rdrv = args
    s = macro_stats(G, a, c, n_own=1, n_other=16, r_drv=rdrv, r_wl=rwl, drive_both_ends=True, own_all_match=True, g=G_ROWS, seed=C.WIRE_SEED + 5)
    return rwl, G, c, a, s["gain_row"], rdrv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--rwl", type=float, nargs="*", default=None)
    ap.add_argument("--rdrv", type=float, nargs="*", default=[10.0])
    ap.add_argument("--tag", default="")
    ap.add_argument("--margin-a", type=float, default=5.17, help="budget margin left at the g = 4, T = 1 ns point (1F section 8), uA")
    ap.add_argument("--fullscale-a", type=float, default=4 * 30.49, help="far-group full-scale differential current at a = g = 4, uA")
    a = ap.parse_args()
    rwls = tuple(a.rwl) if a.rwl else R_WL
    jobs = [(r, G, c, aa, rd) for rd in a.rdrv for r in rwls for G in GROUPS for c in CELLS for aa in A_VALUES]
    with ProcessPoolExecutor(a.procs) as ex:
        res = list(ex.map(job, jobs, chunksize=16))
    out = []
    for rd, rwl in [(rd, r) for rd in a.rdrv for r in rwls]:
        Sa = np.zeros((len(CELLS), len(GROUPS) * len(A_VALUES)))
        for r, G, c, aa, g, rdd in res:
            if r == rwl and rdd == rd:
                Sa[CELLS.index(c), GROUPS.index(G) * len(A_VALUES) + A_VALUES.index(aa)] = g
        U, sv, Vt = np.linalg.svd(Sa, full_matrices=False)
        row = dict(r_drv_ohm=rd, r_wl_ohm_per_cell=rwl, gain_min=float(Sa.min()), gain_max=float(Sa.max()), spread_frac=float(Sa.max() - Sa.min()))
        row["resid_rank0_per_column_scale"] = float(np.abs(Sa.mean(axis=1, keepdims=True) - Sa).max())
        for k in (1, 2, 3):
            row[f"resid_rank{k}"] = float(np.abs((U[:, :k] * sv[:k]) @ Vt[:k] - Sa).max())
        eps_a = a.margin_a / a.fullscale_a                 # (A) budget
        eps_b = 1.0 / 1024                                 # (B) 10-bit threshold LSB
        for tag, eps in (("A_budget", eps_a), ("A_half_budget", eps_a / 2), ("B_quantisation", eps_b)):
            need = next((k for k in (0, 1, 2, 3) if row[f"resid_rank{k}" if k else "resid_rank0_per_column_scale"] <= eps), None)
            row[f"min_rank_{tag}"] = need
        out.append(row)
        print({k: (round(v, 5) if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
    (RP.MACRO / f"row_line_metal_sweep{a.tag}.json").write_text(json.dumps(dict(g=G_ROWS, groups=list(GROUPS), cells=list(CELLS), a_values=list(A_VALUES), eps_budget=a.margin_a / a.fullscale_a, eps_quant=1 / 1024, rows=out), indent=1))


if __name__ == "__main__":
    main()
