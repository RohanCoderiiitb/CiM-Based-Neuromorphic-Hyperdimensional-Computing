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


def build_mesh_deck_ext(gaps: np.ndarray, active: np.ndarray, p: Params, r_bl: float, r_wl: float, r_drv: float, r_s=None, r_tx: float | None = None,
                        blocks: tuple[int, ...] | None = None, r_rail: float | None = None, rail_pos: np.ndarray | None = None, rail_length: float | None = None, r_gnd: float | None = None,
                        gnd_pad_pitches: float = 1.0, gnd_pad_per_block: bool = True, drive_both_ends: bool = False) -> str:
    """ngspice deck for wire.mesh.solve_mesh_ext with EVERY physical row present (nothing collapsed): bitline row i sits (i+1) pitches from the sense node;
    the supply rail runs through all physical rows in order of rail_pos (default i+1) from the pad; row-line blocks each have their own driver; the ground rail
    returns the sense nodes. Prints the sense-resistor voltage of every column, the rail voltage at every active row and the driver-resistor voltage drops."""
    R, K = gaps.shape
    blocks = (K,) if blocks is None else tuple(blocks)
    c0 = np.concatenate([[0], np.cumsum(blocks)[:-1]]).astype(int)
    rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (K,))
    rtx = p.r_tx if r_tx is None else r_tx
    act = np.flatnonzero(active)
    rp = (np.arange(R) + 1.0) if rail_pos is None else np.asarray(rail_pos, dtype=float)
    L = ["mesh_ext", OPTIONS, f"Vr vr 0 DC {_f(p.v_read)}"]
    top = int(act.max()) + 1
    use_rail, use_gnd = r_rail is not None, r_gnd is not None
    for j in range(K):
        if use_gnd:
            L.append(f"Rs{j} s{j} g{j} {_f(rs[j])}")
        else:
            L.append(f"Rs{j} s{j} 0 {_f(rs[j])}")
        prev = f"s{j}"
        for i in range(top):
            L.append(f"RB{i}_{j} {prev} b{i}_{j} {_f(r_bl)}")
            prev = f"b{i}_{j}"
    if use_gnd:
        for b, (c, w) in enumerate(zip(c0, blocks)):
            if gnd_pad_per_block or b == 0:
                L.append(f"RGp{b} g{c} 0 {_f(r_gnd * gnd_pad_pitches)}")
            for j in range(c + 1, c + w):
                L.append(f"RG{j} g{j - 1} g{j} {_f(r_gnd)}")
            if not gnd_pad_per_block and b > 0:
                L.append(f"RGb{b} g{c - 1} g{c} {_f(r_gnd)}")
    if use_rail:
        order = np.argsort(rp)
        order = order[rp[order] <= rp[act].max()]
        L.append(f"RRp vr rail{order[0]} {_f(r_rail * rp[order[0]])}")
        for a_, b_ in zip(order[:-1], order[1:]):
            L.append(f"RR{b_} rail{a_} rail{b_} {_f(r_rail * (rp[b_] - rp[a_]))}")
        if rail_length is not None:
            L.append(f"RRp2 vr rail{order[-1]} {_f(r_rail * (rail_length - rp[order[-1]]))}")
    cd = np.concatenate([c0, np.cumsum(blocks) - 1]) if drive_both_ends else c0
    for i in act:
        for b, c in enumerate(cd):
            L.append(f"RD{i}_{b} {'rail' + str(i) if use_rail else 'vr'} w{i}_{c} {_f(r_drv)}")
        for j in range(K):
            if j > 0 and j not in set(c0.tolist()):
                L.append(f"RW{i}_{j} w{i}_{j - 1} w{i}_{j} {_f(r_wl)}")
            L.append(f"RT{i}_{j} w{i}_{j} x{i}_{j} {_f(rtx)}")
            amp = p.i0 * np.exp(-gaps[i, j] / p.g0)
            L.append(f"B{i}_{j} x{i}_{j} b{i}_{j} I = {_f(amp)}*sinh(V(x{i}_{j},b{i}_{j})/{_f(p.v0)}) + {_f(p.gmin)}*V(x{i}_{j},b{i}_{j})")
    prints = [f"print v(s{j})" for j in range(K)]
    if use_gnd:
        prints += [f"print v(g{j})" for j in range(K)]
    for i in act:
        for b, c in enumerate(cd):
            prints.append(f"print v({'rail' + str(i) if use_rail else 'vr'},w{i}_{c})")
        if use_rail:
            prints.append(f"print v(rail{i})")
    L += [".op", ".control", "set noaskquit", "set numdgt=15", "run"] + prints + [".endc", ".end"]
    return "\n".join(L) + "\n"
