"""Topology (d) done properly: switched-capacitor-style charge integrator ON the bitline with a two-stage Miller OTA (open-loop gain ~60 dB), no copy device. The integration capacitor Cf sits between the
OTA output and the bitline (summing node); the output falls by Q/Cf. A 100 Mohm resistor closes the DC loop so the operating point exists (its current is nA); reset switch / autozero are discussed in
sense.az. One bitline channel; the differential decision subtracts two channels (and the threshold current is injected at the node of one of them)."""
from __future__ import annotations

import numpy as np

import device.constants as C
from sense import port as P
from sense.cells import ota2s
from sense.ngs import VDD, f as fmt, header, run_wrdata

V_VG = 0.25
OTA = dict(wi=16e-6, wt=16e-6, wm=8e-6, lm=180e-9, w5=4e-6, w6=16e-6)
VB, VBP = 0.46, 0.40


def netlist(m, pos0, cf, ota=None, vb=VB, vbp=VBP, a=C.G_1C, row=None, noisy=True, rb="100Meg", extra=None, dv=None):
    o = dict(OTA); o.update(ota or {})
    L = header("d2 channel") + ota2s("ota2s", dv=dv, **o) + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {vb}", f"Vbp vbp 0 {vbp}", f"Vref vref 0 {V_VG}"]
    L += row if row else [f"Vrow row 0 {V_VG + C.V_READ}"]
    L += P.netlist("p", "row", "n", m, a - m, pos0, a=a, noisy=noisy) + ["Xo n vref o vdd vb vbp ota2s", f"Cf o n {fmt(cf)}", f"Rb o n {rb}", "Cn n 0 5f", "Cl o 0 5f"]
    return L + (extra or [])


def transient(m, pos0, T, cf=300e-15, t0=0.3e-9, t_rise=20e-12, t_tail=0.3e-9, ota=None, a=C.G_1C, side="p", dv=None, vb=VB, vbp=VBP, ideal=False):
    row = [f"Vrow row 0 PULSE({V_VG} {V_VG + C.V_READ} {fmt(t0)} {fmt(t_rise)} {fmt(t_rise)} {fmt(T)} 1)"]
    mm = m if side == "p" else a - m
    L = netlist(mm, pos0, cf, ota, vb, vbp, a, row=row, dv=dv)
    d = run_wrdata(L + [f".tran 2p {fmt(t0 + T + t_tail)}"], ["v(n)", "v(o)", "i(Vrow)"])
    return d, t0


def collect(m, pos0, T, side="p", cf=300e-15, **kw):
    """(measured charge Cf*dV(out) [C], array charge, node min, node max, ideal-virtual-ground charge) over the window [t0, T + t_tail]."""
    from sense.collect import ideal_charge
    d, t0 = transient(m, pos0, T, cf, side=side, **kw)
    t = d["time"]; sel = t >= t0 - 1e-12
    q_arr = float(np.trapezoid(-d["i(vrow)"][sel], t[sel]))
    i0 = int(np.argmin(abs(t - (t0 - 5e-12)))); q_meas = -(d["v(o)"][-1] - d["v(o)"][i0]) * cf
    s2 = (t > t0 + 0.05e-9) & (t < t0 + T)
    mm = m if side == "p" else C.G_1C - m
    return q_meas, q_arr, float(d["v(n)"][s2].min()), float(d["v(n)"][s2].max()), ideal_charge(mm, C.G_1C - mm, pos0, T) * 1.0
