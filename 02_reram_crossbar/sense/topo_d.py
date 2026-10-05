"""Topology (d): charge integrator directly on the bitline: PMOS-input OTA (summing node = bitline) with a feedback capacitor. One bitline channel.
No reset switches in the transient here (the integration starts from initial conditions); switch charge injection / offset cancellation are treated in F2(c)."""
from __future__ import annotations

import numpy as np

import device.constants as C
from sense import port as P
from sense.cells import ota_p
from sense.ngs import VDD, f as fmt, header, run_wrdata

V_VG = 0.25
V_OUT0 = 0.69         # quiescent output of the OTA with both inputs at V_VG (vb = 0.40), the integrator's start level


def netlist(m, pos0, cf, vb=0.40, ota=None, a=C.G_1C, row=None, extra=None, noisy=True, rb=None):
    L = header("d channel") + ota_p("ota", **(ota or {})) + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {vb}", f"Vref vref 0 {V_VG}"]
    L += row if row else [f"Vrow row 0 {V_VG}"]
    L += P.netlist("p", "row", "n", m, a - m, pos0, a=a, noisy=noisy) + ["Xo vref n o vdd vb ota", f"Cf n o {fmt(cf)}", "Cn n 0 5f", "Cl o 0 5f"]
    if rb:
        L += [f"Rb n o {rb}"]
    return L + (extra or [])


def transient(m, pos0, t_pulse, cf=150e-15, vb=0.40, ota=None, t0=0.3e-9, t_rise=20e-12, trail=0.6e-9, a=C.G_1C):
    row = [f"Vrow row 0 PULSE({V_VG} {V_VG + C.V_READ} {fmt(t0)} {fmt(t_rise)} {fmt(t_rise)} {fmt(t_pulse)} 1)"]
    L = netlist(m, pos0, cf, vb, ota, a, row=row) + [f".ic v(n)={V_VG} v(o)={V_OUT0}", f".tran 2p {fmt(t0 + t_pulse + trail)} uic"]
    d = run_wrdata(L, ["v(n)", "v(o)", "i(Vrow)"])
    return d, t0
