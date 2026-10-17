"""ngspice transient of one read pulse on the 2-D array (C1d read energy / latency, C2 crosstalk, C3 multi-macro).

Topology = the validated DC mesh (wire.mesh.solve_mesh_ext: bitline chain to a virtual-ground sense node R_s, row lines with R_wl, per-block drivers R_drv fed from a supply
rail through r_rail) with capacitance added:
  bitline : distributed along the FULL physical length (to row 512, including the dead-end stub above the highest active row), pi-lumps of at most `lump` pitches;
            ground cap + neighbour coupling cap (CC_FRACTION of the total C_LINE per pitch is coupling to each... see below) between the SAME node of adjacent bitlines
  row line: C_LINE per pitch to ground at each cell
  sense   : C_sense at the virtual-ground node
  rail    : C_dec decoupling to ground at every active row's supply tap
Row drivers: one at each end of every row-line block (drive_both_ends, the 1C baseline; see scaleup/run_rowline.py).
Access transistors are ON before the pulse (word line asserted first; its energy is accounted separately as C_gate V_WL^2) and are the linear R_tx of the DC solver.
The pulse is the supply: V_pad rises 0 -> V_read in T_RISE and stays. Currents are read at the sense nodes (V(s_j)/R_s). Energy = integral of V_pad * I_supply over the window.
Coupling convention: C_LINE_PER_PITCH is the TOTAL capacitance per pitch seen by a bitline with both neighbours idle-at-ground; cc_fraction of it is split equally to the two
neighbours (cc_fraction / 2 each), the rest to ground. cc_fraction = 0 removes coupling at constant total capacitance.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import device.constants as C
from device.constants import Params
from spice.netlist import _f

TRAN_OPTIONS = ".options reltol=1e-7 abstol=1e-15 vntol=1e-12 gmin=1e-18 itl1=500 itl4=200 method=gear"


@dataclass(frozen=True)
class TranConfig:
    r_bl: float = 0.72
    r_wl: float = 0.72
    r_drv: float = C.R_DRV_DEFAULT
    c_line: float = C.C_LINE_PER_PITCH_F
    cc_fraction: float = C.CC_FRACTION_DEFAULT
    c_sense: float = 5e-15            # F [ASSUM] input capacitance of the current-mode sense stage at the virtual-ground node (not designed in 1C)
    r_rail: float | None = None       # ohm per pitch of the supply rail; None = ideal supply at every driver
    c_dec: float = 0.0                # F decoupling at each active row's supply tap [ASSUM, swept in C2]
    t_rise: float = C.T_RISE_S
    t_stop: float = 2e-9
    t_step: float = 1e-12
    lump: int = 16                    # pitches per bitline lump
    r_pad: float = 0.0                # ohm series resistance between the ideal source and the rail pad (regulator + package) [ASSUM, 1C supply-dynamics study]
    l_pad: float = 0.0                # H series inductance of the pad (package) [ASSUM]
    rail_length: float | None = None  # pitches: a SECOND supply pad at this distance from the first (rail fed from both ends)
    switched_driver: bool = False     # True: the rail sits at V_read (decoupling pre-charged) and the ROW DRIVER closes in t_rise; False: the supply itself ramps (energy runs)
    bl_len: int = C.ROWS_TOTAL


def build_tran_deck(gaps: np.ndarray, pos: np.ndarray, p: Params, cfg: TranConfig, r_s, blocks=None, rail_pos=None, r_tx=None, drive_both_ends: bool = True) -> str:
    n, K = gaps.shape
    blocks = (K,) if blocks is None else tuple(blocks)
    c0 = np.concatenate([[0], np.cumsum(blocks)[:-1]]).astype(int); c0set = set(c0.tolist())
    cdrv = np.concatenate([c0, np.cumsum(blocks) - 1]).astype(int) if drive_both_ends else c0       # row drivers at both ends of every block (the 1C baseline macro)
    rs = np.broadcast_to(np.asarray(r_s, dtype=float), (K,))
    rtx = p.r_tx if r_tx is None else r_tx
    pos = np.asarray(pos, dtype=float)
    xs = np.unique(np.concatenate([pos, np.arange(cfg.lump, cfg.bl_len + 1, cfg.lump, dtype=float), [float(cfg.bl_len)]]))
    xs = xs[xs >= pos.min() * 0 + 1]
    span = np.zeros(len(xs)); lo = np.concatenate([[0.0], xs[:-1]]); hi = np.concatenate([xs[1:], [xs[-1]]])
    span = 0.5 * (xs - lo) + 0.5 * (hi - xs)                       # pi-lump: half of each adjacent segment
    span[0] = 0.5 * xs[0] + 0.5 * (xs[1] - xs[0]) if len(xs) > 1 else xs[0]
    cg = cfg.c_line * (1.0 - cfg.cc_fraction); cc = cfg.c_line * cfg.cc_fraction / 2.0
    src = "vsrc" if (cfg.r_pad > 0 or cfg.l_pad > 0) else "vpad"
    L = ["tran", TRAN_OPTIONS, (f"Vsup {src} 0 DC {_f(p.v_read)}" if cfg.switched_driver else f"Vsup {src} 0 PWL(0 0 {_f(cfg.t_rise)} {_f(p.v_read)})")]
    if src == "vsrc":
        mid = "vp1" if cfg.l_pad > 0 else "vpad"
        L.append(f"Rpad vsrc {mid} {_f(max(cfg.r_pad, 1e-6))}")
        if cfg.l_pad > 0:
            L.append(f"Lpad vp1 vpad {_f(cfg.l_pad)}")
    for j in range(K):
        L.append(f"Rs{j} s{j} 0 {_f(rs[j])}")
        L.append(f"Cs{j} s{j} 0 {_f(cfg.c_sense)}")
        prev, xp = f"s{j}", 0.0
        for k, x in enumerate(xs):
            L.append(f"RB{j}_{k} {prev} b{j}_{k} {_f(cfg.r_bl * (x - xp))}")
            L.append(f"CB{j}_{k} b{j}_{k} 0 {_f(cg * span[k])}")
            if j + 1 < K:
                L.append(f"CC{j}_{k} b{j}_{k} b{j + 1}_{k} {_f(cc * 2.0 * span[k])}" if False else f"CC{j}_{k} b{j}_{k} b{j + 1}_{k} {_f(cc * span[k])}")
            prev, xp = f"b{j}_{k}", x
    kof = {float(x): k for k, x in enumerate(xs)}
    if cfg.r_rail is not None:
        rp = pos if rail_pos is None else np.asarray(rail_pos, dtype=float)
        order = np.argsort(rp)
        L.append(f"RRp vpad rail{order[0]} {_f(max(cfg.r_rail, 1e-4) * rp[order[0]])}")
        for a_, b_ in zip(order[:-1], order[1:]):
            L.append(f"RR{b_} rail{a_} rail{b_} {_f(max(cfg.r_rail, 1e-4) * (rp[b_] - rp[a_]))}")
        if cfg.rail_length is not None:
            L.append(f"RRp2 vpad rail{order[-1]} {_f(max(cfg.r_rail, 1e-4) * (cfg.rail_length - rp[order[-1]]))}")
        if cfg.c_dec > 0:
            for i in range(n):
                L.append(f"CD{i} rail{i} 0 {_f(cfg.c_dec)}")
    for i in range(n):
        k = kof[float(pos[i])]
        for b, c in enumerate(cdrv):
            a_ = 'rail' + str(i) if cfg.r_rail is not None else 'vpad'
            if cfg.switched_driver:
                L.append(f"BD{i}_{b} {a_} w{i}_{c} I = V({a_},w{i}_{c})/{_f(max(cfg.r_drv, 1e-4))}*min(1,time/{_f(cfg.t_rise)})")
            else:
                L.append(f"RD{i}_{b} {a_} w{i}_{c} {_f(max(cfg.r_drv, 1e-4))}")
        for j in range(K):
            if j > 0 and j not in c0set:
                L.append(f"RW{i}_{j} w{i}_{j - 1} w{i}_{j} {_f(cfg.r_wl)}")
            L.append(f"CW{i}_{j} w{i}_{j} 0 {_f(cfg.c_line)}")
            L.append(f"RT{i}_{j} w{i}_{j} x{i}_{j} {_f(rtx)}")
            amp = p.i0 * np.exp(-gaps[i, j] / p.g0)
            L.append(f"B{i}_{j} x{i}_{j} b{j}_{k} I = {_f(amp)}*sinh(V(x{i}_{j},b{j}_{k})/{_f(p.v0)}) + {_f(p.gmin)}*V(x{i}_{j},b{j}_{k})")
    cols = [f"v({src})", "i(Vsup)"] + [f"v(s{j})" for j in range(K)] + ([f"v(rail{i})" for i in range(n)] if cfg.r_rail is not None else [])
    L += [f".tran {_f(cfg.t_step)} {_f(cfg.t_stop)}", ".control", "set noaskquit", "set wr_singlescale", "set wr_vecnames", "set numdgt=12", "run",
          f"wrdata TRANOUT {' '.join(cols)}", ".endc", ".end"]
    return "\n".join(L) + "\n"


def run_tran(deck: str, K: int, timeout: float = 3600.0) -> dict:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "tran.dat"
        cir = Path(td) / "d.cir"; cir.write_text(deck.replace("TRANOUT", str(out)))
        proc = subprocess.run(["ngspice", "-b", str(cir)], capture_output=True, text=True, timeout=timeout)
        if not out.exists():
            raise RuntimeError("ngspice transient produced no output:\n" + (proc.stdout + proc.stderr)[-1500:])
        txt = out.read_text().splitlines()
    hdr = txt[0].split(); data = np.array([[float(x) for x in ln.split()] for ln in txt[1:] if ln.strip()])
    names = [h.lower() for h in hdr]
    col = {nm: data[:, i] for i, nm in enumerate(names)}
    t = data[:, 0]
    vp = col["v(vsrc)"] if "v(vsrc)" in col else col["v(vpad)"]
    rails = [k for k in col if k.startswith("v(rail")]
    return dict(t=t, v_pad=vp, i_sup=-col["i(vsup)"], v_s=np.stack([col[f"v(s{j})"] for j in range(K)], axis=1),
                v_rail=(np.stack([col[k] for k in sorted(rails)], axis=1) if rails else None))


def currents(res: dict, r_s) -> np.ndarray:
    return res["v_s"] / np.asarray(r_s, dtype=float)[None, :]


def energy_to(res: dict, t_end: float) -> float:
    m = res["t"] <= t_end
    return float(np.trapezoid(res["v_pad"][m] * res["i_sup"][m], res["t"][m]))
