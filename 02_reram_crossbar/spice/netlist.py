"""Build ngspice decks. A deck holds many independent columns (one batch), each solved by .op.

Per column: shared ideal source `vr` -> R_tx -> node d -> behavioural device (B-source) -> bitline -> R_s -> 0.
The B-source implements exactly the read equation of rram.va:
    I = I0*exp(-Gap/g0)*sinh(V/V0) + GMIN*V
Inactive rows are omitted from the deck (access transistor open: no branch at all).
"""
from __future__ import annotations

import numpy as np

from pathlib import Path

from device.constants import DEFAULT, Params

PTM_LIB = Path(__file__).resolve().parents[1] / "device" / "ptm" / "ptm45n_lp.lib"

# ngspice option block: defaults (reltol 1e-3) would swamp a 0.01% comparison.
OPTIONS = ".options reltol=1e-10 abstol=1e-16 vntol=1e-13 itl1=1000 gmin=1e-18 noopac"


def _f(x: float) -> str:
    return f"{x:.17g}"


def build_deck(gaps, active, p: Params = DEFAULT, r_s=None, r_tx=None, title: str = "2T2R columns",
               tx: str = "linear", temp: float = 27.0) -> tuple[str, int]:
    """gaps, active: (ncol, n). r_s / r_tx: scalar or length-ncol. Returns (deck_text, ncol).

    tx="linear": access transistor is a resistor r_tx (matches the Newton solver exactly).
    tx="bsim":   access transistor is the PTM 45nm LP BSIM4 NMOS (gate at V_WL, body at 0), W/L from Params.
    """
    gaps = np.asarray(gaps, dtype=float)
    active = np.asarray(active, dtype=bool)
    ncol, n = gaps.shape
    rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (ncol,))
    rtx = np.broadcast_to(np.asarray(p.r_tx if r_tx is None else r_tx, dtype=float), (ncol,))
    lines = [title, OPTIONS, f"Vr vr 0 DC {_f(p.v_read)}"]
    if tx == "bsim":
        lines += [f'.include {PTM_LIB}', f".temp {_f(temp)}", f"Vwl wl 0 DC {_f(p.v_wl)}"]
    elif tx != "linear":
        raise ValueError(tx)
    for c in range(ncol):
        lines.append(f"Rs{c} bl{c} 0 {_f(rs[c])}")
        for i in np.flatnonzero(active[c]):
            if tx == "bsim":
                lines.append(f"M{c}_{i} vr wl d{c}_{i} 0 ptm45n_lp W={_f(p.tx_w_um * 1e-6)} L={_f(p.tx_l_nm * 1e-9)}")
                top = f"d{c}_{i}"
            elif rtx[c] > 0:
                lines.append(f"Rt{c}_{i} vr d{c}_{i} {_f(rtx[c])}")
                top = f"d{c}_{i}"
            else:
                top = "vr"
            a_amp = p.i0 * np.exp(-gaps[c, i] / p.g0)
            lines.append(f"B{c}_{i} {top} bl{c} I = {_f(a_amp)}*sinh(V({top},bl{c})/{_f(p.v0)}) "
                         f"+ {_f(p.gmin)}*V({top},bl{c})")
    lines.append(".op")
    lines.append(".control")
    lines.append("set noaskquit")
    lines.append("set numdgt=15")
    lines.append("run")
    for c in range(ncol):
        lines.append(f"print v(bl{c})")
    lines.append(".endc")
    lines.append(".end")
    return "\n".join(lines) + "\n", ncol
