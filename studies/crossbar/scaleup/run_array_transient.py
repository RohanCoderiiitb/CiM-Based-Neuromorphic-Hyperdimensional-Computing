"""C3(d): the whole 512 x 160 array (five macros, 320 bitlines, rows driven from both ends of each macro) read in one transient, to confirm that the array energy and latency are
five times / equal to the single-macro values of C1(d). Ideal supply and ground. Usage: python -m scaleup.run_array_transient"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.transient import TranConfig, build_tran_deck, currents, energy_to, run_tran

K = 2 * C.FULL_CELLS
EPS_A = (0.05e-6, 0.1e-6, 0.2e-6)


def job(cfg):
    G, a = cfg
    p = params_for(C.AREA_1C, C.RS_1C)
    rng = np.random.default_rng([C.WIRE_SEED, 4242, G, a])
    rows = np.sort(8 * G + rng.choice(8, a, replace=False))
    W = rng.random((a, K // 2)) < 0.5
    gaps = np.where(np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1), p.gap_lrs, p.gap_hrs)
    res = run_tran(build_tran_deck(gaps, rows + 1.0, p, TranConfig(t_stop=1e-9), C.RS_1C, blocks=(2 * C.CELLS_PER_MACRO_ROW,) * C.N_MACROS), K)
    i = currents(res, np.ones(K)); d = i[:, 0::2] - i[:, 1::2]; err = np.abs(d - d[-1][None, :]).max(axis=1)
    ts = {}
    for e in EPS_A:
        idx = np.flatnonzero(err > e); ts[str(e)] = float(res["t"][idx[-1]]) if len(idx) else 0.0
    return dict(G=G, a=a, i_sup_A=float(res["i_sup"][-1]), t_settle_s=ts, energy_J={str(T): energy_to(res, T) for T in (0.25e-9, 0.5e-9, 1e-9)})


def main() -> None:
    with ProcessPoolExecutor(6) as ex:
        res = list(ex.map(job, list(product((0, 32, 63), (8, 4)))))
    (RP.FULL_ARRAY / "array_transient.json").write_text(json.dumps(res, indent=1))
    for r in res:
        print(r["G"], r["a"], f"I {r['i_sup_A']*1e3:.2f} mA", {k: f"{v*1e12:.0f}ps" for k, v in r["t_settle_s"].items()}, {k: f"{v*1e12:.3f}pJ" for k, v in r["energy_J"].items()}, flush=True)


if __name__ == "__main__":
    main()
