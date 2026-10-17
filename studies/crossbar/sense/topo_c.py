"""Topology (c): regenerative current comparator input stage. The bitline drives the drain of a diode-connected NMOS (the latch's input device in its reset/bias state); the cross-coupled regeneration
is evaluated separately. One bitline channel. The node sits at V_gs of the input device (~0.65 V): the row supply must be V_gs + V_READ."""
from __future__ import annotations

import numpy as np

import device.constants as C
from sense import port as P
from sense.cells import NM
from sense.ngs import VDD, f as fmt, header


def netlist(m, pos0, w=20e-6, l=45e-9, vrow=None, a=C.G_1C, row_dc=True, noisy=True, vnode_guess=0.7):
    vr = vrow if vrow is not None else vnode_guess + C.V_READ
    L = header("c channel") + [f"Vdd vdd 0 {VDD}", f"Vrow row 0 {vr if row_dc else vnode_guess}"]
    L += P.netlist("p", "row", "n", m, a - m, pos0, a=a, noisy=noisy) + [f"Mi n n 0 0 {NM} W={fmt(w)} L={fmt(l)}", "Cn n 0 5f", "Iin 0 n DC 0 AC 1"]
    return L
