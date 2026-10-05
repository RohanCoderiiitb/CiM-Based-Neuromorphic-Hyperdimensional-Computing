"""C1(c)/C2: the per-(group, column) row-line gain matrix s[G, c] of the true macro (a = g = 8, driver at both ends, ideal rails) and how well a low-rank / separable
correction represents it.

1B treated the row-line gain as 'correctable by a per-column ladder scale'. The gain of column c depends on the group G (a different bitline distance changes the cell currents,
hence the row-line drop), so a single per-column scale leaves a residual; a full per-(group, column) table would be 64 x 160 numbers. Here the exact matrix is measured on the
mesh (gain = mean victim I_diff at full scale m = a = 8 divided by the same pair alone, averaged over random other columns) and fitted by sum_i u_i(c) v_i(G).
Usage: python -m scaleup.gain_matrix"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import device.constants as C
from scaleup.droop import macro_stats

GROUPS = tuple(range(0, 64, 3))      # includes 63
CELLS = tuple(range(0, 32, 2)) + (31,)
A_VALUES = (1, 2, 4, 6, 8)


def job(args):
    G, c, a, rails = args
    kw = dict(r_rail=C.RAIL_R_DEFAULT, r_gnd=C.RAIL_R_DEFAULT, feed_both=True) if rails else {}
    s = macro_stats(G, a, c, **kw, n_own=1, n_other=30, r_drv=10.0, r_wl=0.72, drive_both_ends=True, own_all_match=True, seed=C.WIRE_SEED + 5)
    return G, c, a, s["gain_total"] if rails else s["gain_row"]


def main(rails: bool = False) -> None:
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, [(G, c, a, rails) for G in GROUPS for c in CELLS for a in A_VALUES], chunksize=4))
    S = np.zeros((len(CELLS), len(GROUPS)))
    Sa = np.zeros((len(CELLS), len(GROUPS) * len(A_VALUES)))                  # columns indexed by (group, a)
    for G, c, a, g in res:
        if a == 8:
            S[CELLS.index(c), GROUPS.index(G)] = g
        Sa[CELLS.index(c), GROUPS.index(G) * len(A_VALUES) + A_VALUES.index(a)] = g
    U, sv, Vt = np.linalg.svd(S, full_matrices=False)
    Ua, sva, Vta = np.linalg.svd(Sa, full_matrices=False)
    out = dict(groups=list(GROUPS), cells=list(CELLS), a_values=list(A_VALUES), gain=S.tolist(), gain_by_a=Sa.tolist(), singular_values=sv.tolist(), min=float(S.min()), max=float(S.max()),
               min_all_a=float(Sa.min()), max_all_a=float(Sa.max()))
    for rank in (1, 2, 3, 4):
        approx = (Ua[:, :rank] * sva[:rank]) @ Vta[:rank]
        out[f"joint_a_rank{rank}_max_resid_frac"] = float(np.abs(approx - Sa).max())
    out["joint_a_per_column_only_max_resid_frac"] = float(np.abs(Sa.mean(axis=1, keepdims=True) - Sa).max())
    for rank in (1, 2, 3, 4):
        approx = (U[:, :rank] * sv[:rank]) @ Vt[:rank]
        out[f"rank{rank}_max_resid_frac"] = float(np.abs(approx - S).max()); out[f"rank{rank}_rms_resid_frac"] = float(np.sqrt(np.mean((approx - S) ** 2)))
    colonly = S.mean(axis=1, keepdims=True) * np.ones((1, len(GROUPS)))
    out["per_column_only_max_resid_frac"] = float(np.abs(colonly - S).max())
    (RP.MACRO / ("row_gain_matrix_with_rails.json" if rails else "row_gain_matrix.json")).write_text(json.dumps(out, indent=1))
    print({k: (round(v, 5) if isinstance(v, float) else None) for k, v in out.items() if isinstance(v, float)})


if __name__ == "__main__":
    main(False)
    main(True)
