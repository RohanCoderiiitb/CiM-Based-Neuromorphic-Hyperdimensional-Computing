"""C5: crosstalk when only ONE bit-plane (every 8th cell, 20 of 160) is sensed: the neighbours of the victim cell are idle. An idle cell's bitlines are left floating (R_s = 1 Gohm);
the cells on them still hang on the driven row line, so those bitlines charge toward V_read through their devices and the neighbour DOES move: this is the quantity measured.
One macro (4 sensed cells: 7, 15, 23, 31), victim cell 15. Same conventions as run_crosstalk. Usage: python -m scaleup.run_crosstalk_bitplane"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.run_crosstalk import N_PAT, T_S, VICTIM_CELL
from scaleup.transient import TranConfig, build_tran_deck, currents, run_tran

K = C.MACRO_BITLINES
SENSED = (7, 15, 23, 31)


def job(cfg):
    G, ccf, pat = cfg
    p = params_for(C.AREA_1C, C.RS_1C)
    rng = np.random.default_rng([C.WIRE_SEED, G, pat, 31])
    rows = np.arange(8 * G, 8 * G + 8)
    w_own = np.random.default_rng([C.WIRE_SEED, G, 999]).random(8) < 0.5
    W = rng.random((8, K // 2)) < 0.5
    if pat == N_PAT - 2:
        W[:] = True
    if pat == N_PAT - 1:
        W[:] = False
    W[:, VICTIM_CELL] = w_own
    gaps = np.where(np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1), p.gap_lrs, p.gap_hrs)
    rs = np.full(K, 1e9)
    for c in SENSED:
        rs[2 * c: 2 * c + 2] = C.RS_1C
    res = run_tran(build_tran_deck(gaps, rows + 1.0, p, TranConfig(cc_fraction=ccf, t_stop=1.2e-9), rs), K)
    i = res["v_s"] / rs[None, :]
    d = i[:, 2 * VICTIM_CELL] - i[:, 2 * VICTIM_CELL + 1]
    return dict(G=G, cc=ccf, pat=pat, err_a=(np.interp(T_S, res["t"], d) - d[-1]).tolist(), final_a=float(d[-1]))


def main() -> None:
    cfgs = list(product((0, 63), (0.0, 0.5, 0.75), range(N_PAT)))
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, cfgs, chunksize=1))
    (RP.TRANSIENT / "crosstalk_bitplane_raw.json").write_text(json.dumps(dict(t_s=T_S.tolist(), runs=res)))
    print("done", len(res))


if __name__ == "__main__":
    main()
