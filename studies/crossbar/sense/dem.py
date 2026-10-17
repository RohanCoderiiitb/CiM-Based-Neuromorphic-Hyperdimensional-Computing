"""Dynamic element matching of the copy devices (and the PMOS mirror) of the differential front-end (b).

Mismatch of the 1:k copy devices (a gain error of ~10% per channel, the dominant static error: sense.mc) is cancelled by swapping them between the two channels half-way through the integration window:
the copy device M2A mirrors BL+ in the first half and BL- in the second; M2B the other way round. The charge each channel collects then carries the average gain (g_A + g_B)/2 and the DIFFERENCE of the two
channels carries a common gain only; what remains is (g_A - g_B)(f - 1/2)(Q_p + Q_n) with f the share of the charge collected before the swap. The PMOS mirror (Mp1 diode / Mp2 output) swaps roles at
the same instant (its gain becomes (g + 1/g)/2 = 1 + O(eps^2)). Switches: transmission gates (PTM 45 nm LP), break-before-make clocks. Everything is a transient; mismatch by BSIM4 delvto per device.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from sense import port as P
from sense.cells import NM, PM, tgate
from sense.mc import Design, V_VG, L_N, _ota
from sense.ngs import VDD, f as fmt, header, run_wrdata

W_SW = 4e-6        # n width of the swap transmission gates (p = 2x) [CHOICE]
NOV = 15e-12       # break-before-make gap, s [CHOICE]
DEVICES_EXTRA = ("M2A", "M2B", "MpA", "MpB")


def devices(dz: Design) -> dict:
    d = dz.devices()
    for t in "pn":
        d.pop(f"M2{t}")
    d["M2A"] = (dz.w1 / dz.k / 2, L_N); d["M2B"] = (dz.w1 / dz.k / 2, L_N)
    d["MpA"] = (dz.wp, dz.lp); d["MpB"] = (dz.wp, dz.lp); d.pop("Mp1"); d.pop("Mp2")
    return d


def netlist(dz: Design, m: int, pos0: float, dv: dict | None, t0: float, T: float, t_sw: float | None, swap_mp: bool = True, t_rise: float = 20e-12, a: int = C.G_1C, ideal: bool = False, temp: float = 27.0) -> list[str]:
    """t_sw: swap instant (None = no swap, plain mirror devices A/B kept with fixed assignment A->BL+, B->BL-)."""
    dv = dv or {}
    L = header("b dem channel", temp=temp) + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {dz.vb}", f"Vref vref 0 {V_VG}", f"Vrow row 0 PULSE({V_VG} {V_VG + C.V_READ} {fmt(t0)} {fmt(t_rise)} {fmt(t_rise)} {fmt(T)} 1)",
                                             f"Vs sref 0 {dz.vs}", "RL s sref 1000 noisy=0"]
    sw = t_sw is not None
    ts = t_sw if sw else 1.0                                      # swap never happens when no swap
    # phase clocks: ph1 high until ts, ph2 high after ts; complements for the p devices of the gates
    L += [f"Vph1 ph1 0 PULSE({VDD} 0 {fmt(ts - NOV)} 10p 10p 1 2)", f"Vph1b ph1b 0 PULSE(0 {VDD} {fmt(ts - NOV)} 10p 10p 1 2)",
          f"Vph2 ph2 0 PULSE(0 {VDD} {fmt(ts + NOV)} 10p 10p 1 2)", f"Vph2b ph2b 0 PULSE({VDD} 0 {fmt(ts + NOV)} 10p 10p 1 2)"]
    for t in "pn":
        node, y, x = f"n{t}", f"y{t}", ("xp" if t == "p" else "xnd")
        nl, nh = (m, a - m) if t == "p" else (a - m, m)
        L += [f"M1{t} {node} g1{t} 0 0 {NM} W={fmt(dz.w1)} L={fmt(L_N)} delvto={dv.get(f'M1{t}', 0.0):.6g}", f"M3{t} {x} g3{t} {y} 0 {NM} W={fmt(dz.w3m * dz.w1 / dz.k)} L={fmt(L_N)}"]
        L += _ota(f"a{t}", node, "vref", f"g1{t}", dz.wi1, dz.li1, dz.wm1, dz.lm1, dz.wt1, dz.lt, dv)
        L += _ota(f"b{t}", "vref", y, f"g3{t}", dz.wi2, dz.li2, dz.wm2, dz.lm2, dz.wt2, dz.lt, dv)
        L += P.netlist(t, "row", node, nl, nh, pos0, a=a) + [f"C{node} {node} 0 5f"]
    # copy devices A (phase 1 -> BL+, phase 2 -> BL-) and B (phase 1 -> BL-, phase 2 -> BL+)
    for s, (p1, p2) in (("A", ("p", "n")), ("B", ("n", "p"))):
        L += [f"M2{s} d{s} gt{s} 0 0 {NM} W={fmt(dz.w1 / dz.k / 2)} L={fmt(L_N)} delvto={dv.get(f'M2{s}', 0.0):.6g}"]
        L += tgate(f"g{s}1", f"gt{s}", f"g1{p1}", "ph1", "ph1b", W_SW) + tgate(f"d{s}1", f"d{s}", f"y{p1}", "ph1", "ph1b", W_SW)
        L += tgate(f"g{s}2", f"gt{s}", f"g1{p2}", "ph2", "ph2b", W_SW) + tgate(f"d{s}2", f"d{s}", f"y{p2}", "ph2", "ph2b", W_SW)
    # PMOS mirror: phase 1: MpA diode (gate=drain=xn), MpB output (gate=xn, drain=s); phase 2 swapped
    pa, pb = f"delvto={dv.get('MpA', 0.0):.6g}", f"delvto={dv.get('MpB', 0.0):.6g}"
    L += [f"MpA da_ ga_ vdd vdd {PM} W={fmt(dz.wp)} L={fmt(dz.lp)} {pa}", f"MpB db_ gb_ vdd vdd {PM} W={fmt(dz.wp)} L={fmt(dz.lp)} {pb}",
          "Vxp xp s 0", "Vxn xnd xn 0"]
    if swap_mp and sw:
        # gate of A: xn in both phases (diode in phase 1: drain to xn; output in phase 2: drain to s)
        L += [f"Rga ga_ xn 1m", f"Rgb gb_ xn 1m"]
        L += tgate("pa1", "da_", "xn", "ph1", "ph1b", W_SW) + tgate("pa2", "da_", "s", "ph2", "ph2b", W_SW)
        L += tgate("pb1", "db_", "s", "ph1", "ph1b", W_SW) + tgate("pb2", "db_", "xn", "ph2", "ph2b", W_SW)
    else:
        L += ["Rga ga_ xn 1m", "Rgb gb_ xn 1m", "Rda da_ xn 1m", "Rdb db_ s 1m"]
    if ideal:
        raise NotImplementedError
    return L


def charges(dz: Design, m: int, pos0: float, dv: dict | None, T: float, t_sw: float | None, swap_mp: bool = True, t0: float = 0.3e-9, t_tail: float = 0.3e-9, temp: float = 27.0) -> tuple[float, float]:
    """(Q_p, Q_n): charge collected from BL+ / BL- copies x k over [t0, t0 + T + t_tail]. The copy currents flow in the switch-routed devices, so the measurement is taken where the current leaves
    the channel: through Vxp (into S) and Vxn (diode branch)."""
    tend = t0 + T + t_tail
    d = run_wrdata(netlist(dz, m, pos0, dv, t0, T, t_sw, swap_mp, temp=temp) + [f".tran 2p {fmt(tend)}"], ["i(Vxp)", "i(Vxn)"])
    t = d["time"]; s_ = t >= t0 - 1e-12
    return float(np.trapezoid(-d["i(vxp)"][s_], t[s_])) * dz.k, float(np.trapezoid(-d["i(vxn)"][s_], t[s_])) * dz.k
