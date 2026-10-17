"""1D-i: one selected row of the full 512 x 160 array during a WRITE, in ngspice, at the write voltage (not extrapolated from the read).

What is in the deck (the 1C structure, carried forward unchanged unless a parameter says otherwise):
  - five macros of 64 bitlines (32 2T2R cells); the selected row's row line is 0.72 ohm per bitline pitch [ASSUM, 1B/1C], BROKEN between macros, with a write driver of
    R_WDRV at BOTH ends of every macro row (1C's both-end drive);
  - all ten drivers of the row hang on one tap of the vertical SUPPLY rail (0.0072 ohm per row pitch, fed from both ends [1C]); for one selected row at physical position
    `row` the rail is the parallel combination of its two arms, r_rail x row x (513 - row) / 513 [MODEL, exact for one active tap];
  - every bitline: the selected cell (device + PTM 45 nm LP BSIM4 access transistor, word line at V_WL), then the bitline wire from the selected row to the write bitline
    driver at the array edge (0.72 ohm/pitch x distance [ASSUM]) as an 8-section RC ladder carrying the bitline's 512 x 0.2 fF [ASSUM, 1C], then the bitline write driver
    R_BLDRV whose reference is the horizontal GROUND rail (0.0072 ohm per column pitch, one pad per macro at its first column [1C]) or, for an inhibited bitline, the inhibit
    supply V_INH;
  - unselected rows: their access transistors are off; their leakage is a separate deck (write/run_d3.py), < 1e-9 of the write current.
The device is either a fixed resistor (DC snapshots: 'before' = targets still HRS, 'after' = targets switched to LRS) or the behavioural threshold switch of write/behav.py.
Bitline k of a macro belongs to cell k // 2; device '+' is the even bitline (stored 1 = LRS on +, HRS on -, as in 1A-1C).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from spice.netlist import PTM_LIB
from write import behav

N_MACROS = 5
BL_PER_MACRO = 64
N_BL = N_MACROS * BL_PER_MACRO
R_LRS = 541.82           # ohm [SIM, 1A] read-bias secant resistance at gap 0.2 nm
R_HRS = 218586.0         # ohm [SIM, 1A] at gap 1.7 nm
TX_W_UM = 0.54           # um  [MODEL, 1A] 20 F^2 access transistor
TX_L_UM = 0.045
C_PITCH_F = 0.2e-15      # F per pitch [ASSUM, 1A/1C]
N_LADDER = 8             # [CHOICE] RC sections representing the bitline between the selected row and the driver


@dataclass(frozen=True)
class RowWrite:
    mode: str = "set"                  # "set": row line at v_drive, target bitlines at 0 | "reset": row line at 0, target bitlines at v_drive
    v_drive: float = 1.5               # V at the write supply pad
    row: int = 512                     # physical row (1 = next to the bitline drivers, 512 = farthest)
    r_wdrv: float = 10.0               # ohm per row write driver (two per macro row) [ASSUM: 1C's read driver value; sized in D1]
    r_bldrv: float = 10.0              # ohm per bitline write driver [ASSUM]
    r_wl: float = 0.72                 # ohm per bitline pitch, row line [ASSUM 1B/1C]
    r_bl: float = 0.72                 # ohm per row pitch, bitline [ASSUM 1B/1C]
    r_rail: float = 0.0072             # ohm per row pitch, supply rail fed from both ends [1C]
    r_gnd: float = 0.0072              # ohm per column pitch, ground rail [1C]
    v_wl: float = 1.1                  # V word line of the selected row [1A]
    orientation: str = "bl"            # "bl": access transistor between device and bitline | "rl": between row line and device
    temp_c: float = 27.0
    w_um: float = TX_W_UM
    unselected: str = "inhibit"        # non-target bitlines: "inhibit" (driven to v_inh) | "float" | "clamp0" (driven to 0 V)
    v_inh: float | None = None         # inhibit level (default: the row-line level of this mode, i.e. zero volts across a non-target device)

    def with_(self, **kw) -> "RowWrite":
        return replace(self, **kw)

    @property
    def inhibit_level(self) -> float:
        if self.v_inh is not None:
            return self.v_inh
        return self.v_drive if self.mode == "set" else 0.0


def rail_r_eff(r_rail: float, row: int, rows: int = 512) -> float:
    """[MODEL] a single tap at `row` on a rail fed from both ends (pads at 0 and rows + 1): the two arms in parallel."""
    d1, d2 = row, rows + 1 - row
    return r_rail * d1 * d2 / (d1 + d2)


def _f(x: float) -> str:
    return f"{x:.12g}"


def build(w: RowWrite, targets: np.ndarray, r_dev: np.ndarray | None = None, behavioural: dict | None = None, tran: tuple | None = None,
          extra_print: bool = True) -> str:
    """targets: bool (N_BL,) - bitlines whose device is written. r_dev: (N_BL,) resistor values for a DC snapshot, or None with `behavioural`
    (dict(vth=, tmin=, tsw=, x0=array) -> write/behav.py devices). tran: (t_rise, t_flat, t_stop) for a transient; None = .op."""
    targets = np.asarray(targets, bool)
    L = [f"row write {w.mode}", f".include {PTM_LIB}", f".temp {_f(w.temp_c)}",
         ".options method=gear reltol=1e-5 abstol=1e-12 vntol=1e-7 gmin=1e-15 itl1=500 itl4=500"]
    if behavioural:
        L += behav.subckt_lines()
    if tran:
        tr, tf, ts = tran
        pulse = lambda v: f"PWL(0 0 {_f(tr)} {_f(v)} {_f(tr + tf)} {_f(v)} {_f(2 * tr + tf)} 0 {_f(ts)} 0)"
    else:
        pulse = lambda v: f"DC {_f(v)}"
    v_row = w.v_drive if w.mode == "set" else 0.0
    v_tgt = 0.0 if w.mode == "set" else w.v_drive
    # supply pad -> rail tap -> 10 drivers; the pad carries the row-line level (a pulse in SET mode, ground in RESET mode)
    L += [f"Vpad pad 0 {pulse(v_row) if w.mode == 'set' else 'DC 0'}", f"Rrail pad rt {_f(max(rail_r_eff(w.r_rail, w.row), 1e-6))}",
          f"Vwl wl 0 DC {_f(w.v_wl)}"]
    # bitline drive sources: target level and inhibit level (shared ideal sources behind each R_BLDRV)
    L += [f"Vtg vtg 0 {pulse(v_tgt) if w.mode == 'reset' else 'DC 0'}"]
    vinh = w.inhibit_level
    L += [f"Vinh vinh 0 {pulse(vinh) if (w.mode == 'set' and w.v_inh is None) else 'DC ' + _f(vinh)}"]
    dist = w.row          # pitches of bitline between the selected row and the edge drivers
    c_bl = 512 * C_PITCH_F
    for m in range(N_MACROS):
        # row line of macro m: nodes w{m}_{k}, driver at both ends
        for k in range(BL_PER_MACRO - 1):
            L.append(f"Rw{m}_{k} w{m}_{k} w{m}_{k + 1} {_f(w.r_wl)}")
        L += [f"Rd{m}a rt w{m}_0 {_f(w.r_wdrv)}", f"Rd{m}b rt w{m}_{BL_PER_MACRO - 1} {_f(w.r_wdrv)}",
              f"Crw{m} w{m}_0 0 {_f(BL_PER_MACRO * C_PITCH_F)}"]
        # ground rail of macro m: pad at column 0, taps g{m}_{k}
        L.append(f"Rgp{m} g{m}_0 0 {_f(max(w.r_gnd, 1e-6))}")
        for k in range(BL_PER_MACRO - 1):
            L.append(f"Rg{m}_{k} g{m}_{k} g{m}_{k + 1} {_f(max(w.r_gnd, 1e-6))}")
        for k in range(BL_PER_MACRO):
            j = m * BL_PER_MACRO + k
            top, mid, bot = f"w{m}_{k}", f"d{j}", f"x{j}"
            # device + access transistor
            if w.orientation == "bl":
                dev_a, dev_b, tx_d, tx_s = top, mid, mid, bot
            else:
                dev_a, dev_b, tx_d, tx_s = mid, bot, top, mid
            if behavioural:
                x0 = float(np.asarray(behavioural["x0"])[j])
                L.append(f"X{j} {dev_a} {dev_b} u{j} s{j} bdev vth={_f(behavioural['vth'])} tmin={_f(behavioural['tmin'])} tsw={_f(behavioural.get('tsw', 2e-9))} pol={1 if w.mode == 'set' else -1}")
                L.append(f".ic v(s{j})={_f(x0)} v(u{j})=0")
            else:
                L.append(f"Rdev{j} {dev_a} {dev_b} {_f(r_dev[j])}")
            L.append(f"M{j} {tx_d} wl {tx_s} 0 ptm45n_lp W={_f(w.w_um * 1e-6)} L={_f(TX_L_UM * 1e-6)}")
            # bitline wire as an RC ladder from the cell (x) to the driver end (e)
            rs = w.r_bl * dist / N_LADDER
            prev = bot
            for s in range(N_LADDER):
                nxt = f"e{j}" if s == N_LADDER - 1 else f"l{j}_{s}"
                L += [f"Rl{j}_{s} {prev} {nxt} {_f(max(rs, 1e-6))}", f"Cl{j}_{s} {nxt} 0 {_f(c_bl / N_LADDER)}"]
                prev = nxt
            # bitline driver (target / inhibit / float / clamp0); its return is the ground rail tap of this column
            if targets[j]:
                ref = "vtg" if w.mode == "reset" else f"g{m}_{k}"
                L.append(f"Rb{j} e{j} {ref} {_f(w.r_bldrv)}")
            elif w.unselected == "inhibit":
                L.append(f"Rb{j} e{j} vinh {_f(w.r_bldrv)}")
            elif w.unselected == "clamp0":
                L.append(f"Rb{j} e{j} g{m}_{k} {_f(w.r_bldrv)}")
            elif w.unselected == "float":
                pass
            else:
                raise ValueError(w.unselected)
    if tran:
        L.append(f".tran {_f(tran[0] / 20)} {_f(tran[2])} 0 {_f(min(tran[0] / 4, tran[2] / 2000))} uic")
    else:
        L.append(".op")
    return "\n".join(L)
