"""ngspice deck for the full 2-D mesh: EVERY physical row's bitline segment is present (no chain elimination), so this validates the
mesh solver's collapse of inactive rows as well as its nodal equations."""
from __future__ import annotations

import numpy as np

from device.constants import DEFAULT, Params
from spice.netlist import OPTIONS, _f
from spice.runner import run_deck_prints


def build_mesh_deck(gaps: np.ndarray, active: np.ndarray, p: Params, r_bl: float, r_wl: float, r_drv: float,
                    r_s: float | np.ndarray | None = None, r_tx: float | None = None) -> str:
    """gaps (R, K) for every physical row, active (R,) bool. Sense node at row 0 end: row i sits (i + 1) pitches away."""
    R, K = gaps.shape
    rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (K,))
    rtx = p.r_tx if r_tx is None else r_tx
    top = int(np.max(np.flatnonzero(active))) if active.any() else -1
    L = ["mesh", OPTIONS, f"Vr vr 0 DC {_f(p.v_read)}"]
    for j in range(K):
        L.append(f"Rs{j} s{j} 0 {_f(rs[j])}")
        prev = f"s{j}"
        for i in range(top + 1):              # rows above the highest active row carry no current and are omitted
            L.append(f"RB{i}_{j} {prev} b{i}_{j} {_f(r_bl)}")
            prev = f"b{i}_{j}"
    for i in np.flatnonzero(active):
        L.append(f"RD{i} vr w{i}_0 {_f(r_drv)}")
        for j in range(K):
            if j > 0:
                L.append(f"RW{i}_{j} w{i}_{j - 1} w{i}_{j} {_f(r_wl)}")
            L.append(f"RT{i}_{j} w{i}_{j} x{i}_{j} {_f(rtx)}")
            amp = p.i0 * np.exp(-gaps[i, j] / p.g0)
            L.append(f"B{i}_{j} x{i}_{j} b{i}_{j} I = {_f(amp)}*sinh(V(x{i}_{j},b{i}_{j})/{_f(p.v0)}) + {_f(p.gmin)}*V(x{i}_{j},b{i}_{j})")
    L += [".op", ".control", "set noaskquit", "set numdgt=15", "run"] + [f"print v(s{j})" for j in range(K)] + [".endc", ".end"]
    return "\n".join(L) + "\n"


def run_mesh_ngspice(gaps, active, p: Params = DEFAULT, **kw) -> np.ndarray:
    """Column currents (K,) from ngspice for the full-physical-array mesh."""
    gaps = np.asarray(gaps, dtype=float); active = np.asarray(active, dtype=bool)
    K = gaps.shape[1]
    rs = np.broadcast_to(np.asarray(p.r_s if kw.get("r_s") is None else kw["r_s"], dtype=float), (K,))
    v = run_deck_prints(build_mesh_deck(gaps, active, p, **kw))
    return np.array([v[f"v(s{j})"] for j in range(K)]) / rs
