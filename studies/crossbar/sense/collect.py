"""Virtual-ground quality of each topology, measured the same way: the charge the ARRAY delivers into the sense node during a read pulse (row pulse of length T), per matching count m, for the far
group of the 8 active rows, compared with what an ideal virtual ground (node held exactly at V_VG) would draw. Also the node-voltage excursion. This is topology independent of how the current is then measured."""
from __future__ import annotations

import numpy as np

import device.constants as C
from sense import port as P
from sense.cells import NM, ota_p
from sense.ngs import VDD, f as fmt, header, run_wrdata
from sense import topo_d


def ideal_charge(n_lrs, n_hrs, pos0, T, a=C.G_1C):
    return C.V_READ / (1.0 / P.branch_g(n_lrs, n_hrs) + P.wire_r(pos0, a)) * T


def collect_d(m, pos0, T, side="p", cf=150e-15, **kw):
    n_l, n_h = (m, C.G_1C - m) if side == "p" else (C.G_1C - m, m)
    # reuse the + channel builder with the complementary counts through m
    d, t0 = topo_d.transient(m if side == "p" else C.G_1C - m, pos0, T, cf=cf, **kw)
    t = d["time"]; sel = (t >= t0) & (t <= t0 + T + 0.55e-9)
    q = float(np.trapezoid(-d["i(vrow)"][sel], t[sel]))
    s2 = (t > t0 + 0.05e-9) & (t < t0 + T)
    return q, float(d["v(n)"][s2].min()), float(d["v(n)"][s2].max())


def collect_a(m, pos0, T, rf=500.0, i_sub=None, vb=0.40, a=C.G_1C, side="p", ota=None):
    mm = m if side == "p" else a - m
    ip, _ = P.levels(pos0)
    i_sub = ip[a // 2] if i_sub is None else i_sub
    t0 = 0.3e-9
    L = header("a tran") + ota_p("ota", **(ota or {})) + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {vb}", "Vref vref 0 0.25", f"Vrow row 0 PULSE(0.25 {0.25 + C.V_READ} {fmt(t0)} 20p 20p {fmt(T)} 1)"]
    L += P.netlist("p", "row", "n", mm, a - mm, pos0, a=a) + ["Xo vref n o vdd vb ota", f"Rf n o {rf}", "Cn n 0 5f", "Cl o 0 10f",
                                                          f"Isub n 0 PULSE(0 {i_sub} {fmt(t0)} 20p 20p {fmt(T)} 1)", ".ic v(n)=0.25 v(o)=0.25", f".tran 2p {fmt(t0 + T + 0.55e-9)} uic"]
    d = run_wrdata(L, ["v(n)", "v(o)", "i(Vrow)"])
    t = d["time"]; sel = (t >= t0) & (t <= t0 + T + 0.55e-9)
    q = float(np.trapezoid(-d["i(vrow)"][sel], t[sel])); s2 = (t > t0 + 0.05e-9) & (t < t0 + T)
    return q, float(d["v(n)"][s2].min()), float(d["v(n)"][s2].max())


def collect_c(m, pos0, T, w=20e-6, a=C.G_1C, side="p", vn0=0.55):
    mm = m if side == "p" else a - m
    t0 = 0.3e-9
    L = header("c tran") + [f"Vdd vdd 0 {VDD}", f"Vrow row 0 PULSE({vn0} {vn0 + C.V_READ} {fmt(t0)} 20p 20p {fmt(T)} 1)"]
    L += P.netlist("p", "row", "n", mm, a - mm, pos0, a=a) + [f"Mi n n 0 0 {NM} W={fmt(w)} L=45n", "Cn n 0 5f", f".tran 2p {fmt(t0 + T + 0.55e-9)}"]
    d = run_wrdata(L, ["v(n)", "i(Vrow)"])
    t = d["time"]; sel = (t >= t0) & (t <= t0 + T + 0.55e-9)
    q = float(np.trapezoid(-d["i(vrow)"][sel], t[sel])); s2 = (t > t0 + 0.05e-9) & (t < t0 + T)
    return q, float(d["v(n)"][s2].min()), float(d["v(n)"][s2].max())
