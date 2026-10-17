"""C2(b): crosstalk between adjacent bitlines, from ngspice transients of one macro read (64 bitlines, ideal supply/ground, row drivers at both ends).

Convention (see scaleup/transient.py): C_LINE = 0.2 fF/pitch total per bitline, cc_fraction of it coupled equally to the two neighbours. Victim = the middle cell column (both
bitlines have two neighbours, all columns sensing). For each (group, cc_fraction) and for N random weight patterns of ALL other cells (own pattern fixed) the victim's
differential current is recorded against time. Error at time t = d(t) - d(final). The COUPLING-induced part = error(cc) - error(cc = 0) on the same pattern (the cc = 0
run has the same total capacitance, all to ground: pure RC settling). Data dependence = spread over the patterns at each sampling time.
Usage: python -m scaleup.run_crosstalk"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.transient import TranConfig, build_tran_deck, currents, run_tran

K = C.MACRO_BITLINES
VICTIM_CELL = 15
T_S = np.array([40, 60, 80, 100, 130, 160, 200, 300, 500, 1000]) * 1e-12
N_PAT = 12


def job(cfg):
    G, ccf, pat = cfg
    p = params_for(C.AREA_1C, C.RS_1C)
    rng = np.random.default_rng([C.WIRE_SEED, G, pat])
    rows = np.arange(8 * G, 8 * G + 8)
    w_own = np.random.default_rng([C.WIRE_SEED, G, 999]).random(8) < 0.5            # same own pattern for every run of this group
    W = rng.random((8, K // 2)) < 0.5
    if pat == N_PAT - 2:
        W[:] = True                                                               # adversarial neighbours: every + device LRS (largest column current swing)
    if pat == N_PAT - 1:
        W[:] = False
    W[:, VICTIM_CELL] = w_own
    st = np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)
    gaps = np.where(st, p.gap_lrs, p.gap_hrs)
    cfgt = TranConfig(cc_fraction=ccf, t_stop=1.2e-9)
    res = run_tran(build_tran_deck(gaps, rows + 1.0, p, cfgt, C.RS_1C), K)
    i = currents(res, np.ones(K)); d = i[:, 2 * VICTIM_CELL] - i[:, 2 * VICTIM_CELL + 1]
    err = np.interp(T_S, res["t"], d) - d[-1]
    return dict(G=G, cc=ccf, pat=pat, err_a=err.tolist(), final_a=float(d[-1]))


def main() -> None:
    RP.TRANSIENT.mkdir(parents=True, exist_ok=True)
    cfgs = list(product((0, 63), C.CC_FRACTION_SWEEP + (0.0,), range(N_PAT)))
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, cfgs, chunksize=1))
    (RP.TRANSIENT / "crosstalk_macro_raw.json").write_text(json.dumps(dict(t_s=T_S.tolist(), runs=res)))
    print("done", len(res))


if __name__ == "__main__":
    main()
