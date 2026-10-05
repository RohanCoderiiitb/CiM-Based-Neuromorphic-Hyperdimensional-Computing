"""C1(d): read energy and read latency PER GROUP READ, for all 64 groups of a column, from ngspice transients of one 512 x 32-cell macro (64 bitlines) read.

Per group G (rows 8G..8G+7, contiguous) and per pattern (a = 8 and a = 4 active rows; random weights): the supply current, the energy drawn from the read supply over a pulse of
length T (integral of V_pad * I_supply from the start of the rise), and the array settling time: the last instant at which the differential current of ANY of the 32 cell columns
is more than eps from its final value. Ideal supply and ground here (rail effects are C2); rows beyond the macro are not simulated (a macro row line holds 32 cells).
Pulse energy beyond the simulated window: once settled the supply current is constant, E(T) = E(t_stop) + V_read * I_final * (T - t_stop) (checked: i_sup is flat at t_stop).
Usage: python -m scaleup.run_energy_latency [--workers N]"""
from __future__ import annotations

import paths as RP

import argparse
import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.transient import TranConfig, build_tran_deck, currents, energy_to, run_tran

K = C.MACRO_BITLINES
EPS_A = (0.05e-6, 0.1e-6, 0.2e-6, 0.4e-6)
T_GRID_S = (0.1e-9, 0.2e-9, 0.25e-9, 0.5e-9, 1e-9, 2e-9, 5e-9, 10e-9)
T_STOP = 1e-9


def one_group(args: tuple) -> dict:
    G, a, seed, r = args
    p = params_for(C.AREA_1C, C.RS_1C)
    rng = np.random.default_rng([C.WIRE_SEED, G, a, seed])
    rows = np.arange(8 * G, 8 * G + 8)
    act = np.sort(rng.choice(8, a, replace=False)); rows = rows[act]
    W = rng.random((a, K // 2)) < 0.5
    st = np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)
    gaps = np.where(st, p.gap_lrs, p.gap_hrs)
    cfg = TranConfig(r_bl=r, r_wl=r, t_stop=T_STOP)
    res = run_tran(build_tran_deck(gaps, rows + 1.0, p, cfg, C.RS_1C), K)
    i = currents(res, np.ones(K)); d = i[:, 0::2] - i[:, 1::2]
    err = np.abs(d - d[-1][None, :]).max(axis=1)
    t_settle = {}
    for eps in EPS_A:
        idx = np.flatnonzero(err > eps); t_settle[str(eps)] = float(res["t"][idx[-1]]) if len(idx) else 0.0
    i_fin = float(res["i_sup"][-1]); e_stop = energy_to(res, T_STOP)
    flat = float(abs(res["i_sup"][-1] - res["i_sup"][-50]) / max(abs(i_fin), 1e-30))
    E = {str(T): (energy_to(res, T) if T <= T_STOP else e_stop + C.V_READ * i_fin * (T - T_STOP)) for T in T_GRID_S}
    return dict(G=G, a=a, seed=seed, r=r, rows_pos=[int(rows[0] + 1), int(rows[-1] + 1)], i_sup_final_A=i_fin, i_sup_peak_A=float(res["i_sup"].max()), i_sup_flatness=flat,
                t_settle_s=t_settle, energy_J=E, i_cols_sum_A=float(i[-1].sum()))


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=9); args = ap.parse_args()
    RP.TRANSIENT.mkdir(parents=True, exist_ok=True)
    jobs = [(G, a, s, 0.72) for G in range(C.GROUPS_PER_COLUMN) for a in (8, 4) for s in range(3)]
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(one_group, jobs, chunksize=2))
    (RP.TRANSIENT / "group_read_energy_latency_macro.json").write_text(json.dumps(res))
    print("done", len(res))


if __name__ == "__main__":
    main()
