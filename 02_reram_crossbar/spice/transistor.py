"""Access-transistor characterisation with the PTM 45nm LP BSIM4 card (ngspice).

Topology of one array branch:  Vr(0.1V) -> NMOS(drain=vr, gate=WL, source=s, body=0) -> device(B-source) -> bitline -> R_s -> 0
"""
from __future__ import annotations

import numpy as np

from device.constants import DEFAULT, Params
from spice.netlist import OPTIONS, PTM_LIB, _f
from spice.runner import run_deck_prints


def _dev_source(name: str, a: str, b: str, gap: float, p: Params) -> str:
    amp = p.i0 * np.exp(-gap / p.g0)
    return f"B{name} {a} {b} I = {_f(amp)}*sinh(V({a},{b})/{_f(p.v0)}) + {_f(p.gmin)}*V({a},{b})"


def branch_rtx(gap: float, p: Params = DEFAULT, temp: float = 27.0, v_bl_fixed: float | None = None) -> dict:
    """One ON branch, single transistor + one device. Returns current and R_tx = (V_read - V_s)/I.

    v_bl_fixed: if given the bitline is held at that voltage (used to look at bias dependence); else it sits on R_s.
    """
    lines = ["branch rtx", OPTIONS, f".include {PTM_LIB}", f".temp {_f(temp)}",
             f"Vr vr 0 DC {_f(p.v_read)}", f"Vwl wl 0 DC {_f(p.v_wl)}",
             f"M1 vr wl s 0 ptm45n_lp W={_f(p.tx_w_um * 1e-6)} L={_f(p.tx_l_nm * 1e-9)}",
             _dev_source("d", "s", "bl", gap, p)]
    lines.append(f"Vb bl 0 DC {_f(v_bl_fixed)}" if v_bl_fixed is not None else f"Rs bl 0 {_f(p.r_s)}")
    lines += [".op", ".control", "set noaskquit", "set numdgt=15", "run",
              "print v(s)", "print v(bl)", "print i(Vr)", "print @m1[leff]", "print @m1[weff]", ".endc", ".end"]
    v = run_deck_prints("\n".join(lines) + "\n")
    i = -v["i(vr)"]
    return dict(i=i, v_s=v["v(s)"], v_bl=v["v(bl)"], r_tx=(p.v_read - v["v(s)"]) / i,
                leff_m=v.get("@m1[leff]"), weff_m=v.get("@m1[weff]"))


def idsat_per_um(p: Params = DEFAULT, vdd: float = 1.1, temp: float = 27.0) -> float:
    """Idsat/W at Vgs = Vds = vdd, W = 1 um, L = card L. Sanity check: should be ~0.5-0.6 mA/um."""
    deck = "\n".join(["idsat", OPTIONS, f".include {PTM_LIB}", f".temp {_f(temp)}", f"Vd d 0 {_f(vdd)}", f"Vg g 0 {_f(vdd)}",
                      f"M1 d g 0 0 ptm45n_lp W=1u L={_f(p.tx_l_nm * 1e-9)}", ".op", ".control", "set numdgt=15", "run",
                      "print @m1[id]", ".endc", ".end"]) + "\n"
    return run_deck_prints(deck)["@m1[id]"] / 1e-3 * 1.0


def rdsw_floor_ohm(w_um: float, rdsw_ohm_um: float = 210.0, wr: float = 1.0) -> float:
    """[MODEL] BSIM4 rdsmod=0 source/drain resistance floor: rdsw / (W_um)^wr. rdsw from the card (210 ohm*um)."""
    return rdsw_ohm_um / w_um ** wr


def width_um(area_f2: float, fill: float, f_nm: float) -> float:
    """[MODEL] W = fill * area_F2 * F  (matches the brief's table: 20 F^2 -> 0.54 um)."""
    return fill * area_f2 * f_nm * 1e-3


def cell_pitch_um(area_f2: float, f_nm: float) -> float:
    """[MODEL] square 1T1R cell: pitch = sqrt(area). The 2T2R cell is two 1T1R side by side along the WL, so the row pitch
    along the bitline equals the 1T1R cell side."""
    return float(np.sqrt(area_f2) * f_nm * 1e-3)
