"""Topology (a): resistive-feedback transimpedance amplifier on the bitline (PMOS-input OTA, R_f from output to the summing node). The array current enters the node, so the output falls below the node
by (I - I_sub) R_f; an ideal DC current sink I_sub (noise-free here: it stands for the threshold current) keeps the output in range. One bitline channel."""
from __future__ import annotations

import numpy as np

import device.constants as C
from sense import port as P
from sense.acnoise import noise_spectrum
from sense.cells import ota_p
from sense.ngs import VDD, f as fmt, header, run, scalars

V_VG = 0.25


def netlist(m, pos0, rf, i_sub, cf=0.0, vb=0.40, ota=None, a=C.G_1C, row_dc=True, noisy=True):
    L = header("a channel") + ota_p("ota", **(ota or {})) + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {vb}", f"Vref vref 0 {V_VG}", f"Vrow row 0 {V_VG + (C.V_READ if row_dc else 0.0)}"]
    L += P.netlist("p", "row", "n", m, a - m, pos0, a=a, noisy=noisy) + ["Xo vref n o vdd vb ota", f"Rf n o {rf}", "Cn n 0 5f", "Cl o 0 10f", f"Isub n 0 DC {i_sub}", "Iin 0 n DC 0 AC 1"]
    if cf:
        L += [f"Cf n o {fmt(cf)}"]
    return L
