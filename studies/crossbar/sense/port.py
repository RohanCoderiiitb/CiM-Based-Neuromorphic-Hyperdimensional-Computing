"""The array as seen from the sense node (1F): one bitline of a group read = V_read source -> parallel cell branches -> bitline wire (+ lumped bitline capacitance) -> sense node.

At 0.1 V read bias the ReRAM+transistor branch is linear (the user's brief; 1A section 5), so each active branch is the fixed resistor R_tx + R_LRS or R_tx + R_HRS, from constants / the
1A results. Checked against the 1C mesh solver: the far group's differential level span is 351 uA here vs 347 uA (mesh, r = 0.72); the worst step 34.3 vs 34.1 uA.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from device.model import device_resistance
from margin.core import params_for

R_TX = C.RTX_BY_AREA[C.AREA_1C]
R_LRS_BR = R_TX + float(device_resistance(C.GAP_LRS))     # one low-resistance branch, access transistor included
R_HRS_BR = R_TX + float(device_resistance(C.GAP_HRS))
R_WIRE_PER_PITCH = 0.72                                    # ohm per row, the 1B/1C recommended-point value [ASSUM]
C_BL_PER_PITCH = C.C_LINE_PER_PITCH_F                      # F per row (total bitline capacitance per pitch) [ASSUM, 1C]


def wire_r(pos0: float, g: int = C.G_1C) -> float:
    """Bitline resistance between the group's rows (middle of the group) and the sense node, ohm."""
    return R_WIRE_PER_PITCH * (pos0 + (g - 1) / 2.0)


def branch_g(n_lrs: int, n_hrs: int) -> float:
    return n_lrs / R_LRS_BR + n_hrs / R_HRS_BR


def levels(pos0: float, a: int = C.G_1C, r_in: float = 0.0):
    """Nominal I+(m), I-(m) for m = 0..a matching rows, a active rows, a group whose nearest row is pos0 pitches from the sense node, sense-node resistance r_in (ohm)."""
    rw = wire_r(pos0)
    ip, im = [], []
    for m in range(a + 1):
        ip.append(C.V_READ / (1.0 / branch_g(m, a - m) + rw + r_in))
        im.append(C.V_READ / (1.0 / branch_g(a - m, m) + rw + r_in))
    return np.array(ip), np.array(im)


def worst_step(pos0: float, a: int = C.G_1C) -> float:
    ip, im = levels(pos0, a)
    return float(np.min(np.abs(np.diff(ip - im))))


FAR_POS0 = C.ROWS_TOTAL - C.G_1C + 1.0                      # 505 pitches
NEAR_POS0 = 1.0


def netlist(prefix: str, row: str, node: str, n_lrs: int, n_hrs: int, pos0: float, c_x: float | None = None, noisy: bool = True, a: int = C.G_1C) -> list[str]:
    """ngspice lines of one bitline: row source node -> parallel branches -> X (half of the bitline capacitance) -> bitline wire -> sense node `node`.
    noisy=False makes the resistors noiseless (to separate the array's own thermal noise from the amplifier's in .noise runs)."""
    rw = wire_r(pos0, a)
    g = branch_g(n_lrs, n_hrs)
    cx = (0.5 * C_BL_PER_PITCH * (pos0 + a)) if c_x is None else c_x
    nz = "" if noisy else " noisy=0"
    return [f"R{prefix}c {row} {prefix}x {1.0 / g:.9g}{nz}", f"R{prefix}w {prefix}x {node} {rw:.9g}{nz}", f"C{prefix}x {prefix}x 0 {cx:.9g}"]
