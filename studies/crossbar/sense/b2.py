"""Front-end (b2): the chopped dual-integrator version of topology (b).

(b) as first built (sense.mc) subtracts the two channels inside one summing node, through a PMOS mirror. Its static errors (copy-gain mismatch of each channel, amplifier offset times the array conductance,
mirror gain) are ~39 uA rms uncalibrated and four numbers per column must be calibrated, a calibration that does not survive a 20 K change of temperature (sense.cal). (b2) removes the mechanism instead:

  * two identical regulated conveyors A and B (OTA1 + M1 sink holding the bitline at V_VG, copy M2 at 1:k regulated by OTA2 + cascode M3);
  * input switches swap which bitline (BL+ / BL-) each conveyor serves half-way through the integration window; output switches swap which integration capacitor (S+ / S-) each cascode drain feeds, so BL+
    always integrates on S+ and BL- on S-: no PMOS mirror, no inversion;
  * the charge each bitline delivers therefore carries the average of the two conveyors' gains and the average of their offsets, a COMMON gain on both channels;
  * the decision variable is V(S-) - V(S+) = (Q+ - Q- - Q_thr)/C_int (the threshold current sinks from S-), read by the comparator after the window.
What is left per column is one gain (the common gain, plus the C+/C- mismatch) and the charge injection of the switches. Everything is a transient on the PTM 45 nm LP card; mismatch by BSIM4 delvto.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from sense import port as P
from sense.cells import NM, tgate
from sense.mc import Design, V_VG, L_N, _ota
from sense.ngs import VDD, f as fmt, header, run_wrdata

NOV = 15e-12
V_S0 = 0.80            # reset level of the integration capacitors [CHOICE]


class Chop:
    """Chopping / integrator parameters."""
    def __init__(self, c_int=150e-15, w_in=40e-6, w_out=4e-6, f_sw=0.5, t_tail=0.3e-9, c_mis=0.0):
        self.c_int, self.w_in, self.w_out, self.f_sw, self.t_tail, self.c_mis = c_int, w_in, w_out, f_sw, t_tail, c_mis


def devices(dz: Design) -> dict:
    d = {}
    for t in "AB":
        d[f"M1{t}"] = (dz.w1, L_N); d[f"M2{t}"] = (dz.w1 / dz.k, L_N)
        for o, wi, li, wm, lm in (("a", dz.wi1, dz.li1, dz.wm1, dz.lm1), ("b", dz.wi2, dz.li2, dz.wm2, dz.lm2)):
            d[f"{o}{t}_p1"] = (wi, li); d[f"{o}{t}_p2"] = (wi, li); d[f"{o}{t}_n3"] = (wm, lm); d[f"{o}{t}_n4"] = (wm, lm)
    return d


def draw(dz: Design, rng, avt: float = C.AVT_MV_UM) -> dict:
    return {n: float(rng.normal(0.0, avt * 1e-3 / np.sqrt(w * l * 1e12))) for n, (w, l) in devices(dz).items()}


def netlist(dz: Design, m: int, pos0: float, ch: Chop, T: float, t0: float = 0.3e-9, dv: dict | None = None, t_rise: float = 20e-12, a: int = C.G_1C, chopped: bool = True, i_thr: float = 0.0,
            temp: float = 27.0, c_mis_p: float = 0.0, ideal: bool = False) -> list[str]:
    dv = dv or {}
    tend = t0 + T + ch.t_tail
    ts = t0 + ch.f_sw * (T + ch.t_tail) if chopped else 1.0
    L = header("b2 channel", temp=temp) + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {dz.vb}", f"Vref vref 0 {V_VG}",
                                           f"Vrow row 0 PULSE({V_VG} {V_VG + C.V_READ} {fmt(t0)} {fmt(t_rise)} {fmt(t_rise)} {fmt(T)} 1)"]
    L += [f"Vph1 ph1 0 PULSE({VDD} 0 {fmt(ts - NOV)} 10p 10p 1 2)", f"Vph1b ph1b 0 PULSE(0 {VDD} {fmt(ts - NOV)} 10p 10p 1 2)",
          f"Vph2 ph2 0 PULSE(0 {VDD} {fmt(ts + NOV)} 10p 10p 1 2)", f"Vph2b ph2b 0 PULSE({VDD} 0 {fmt(ts + NOV)} 10p 10p 1 2)"]
    # the array: BL+ (m matching) and BL- (a - m matching), raw sense nodes rp, rn
    L += P.netlist("p", "row", "rp", m, a - m, pos0, a=a) + P.netlist("n", "row", "rn", a - m, m, pos0, a=a) + ["Crp rp 0 5f", "Crn rn 0 5f"]
    if ideal:
        return L + [f"Vrp rp 0 {V_VG}", f"Vrn rn 0 {V_VG}"]
    for t in "AB":
        node, y, x = f"n{t}", f"y{t}", f"x{t}"
        L += [f"M1{t} {node} g1{t} 0 0 {NM} W={fmt(dz.w1)} L={fmt(L_N)} delvto={dv.get(f'M1{t}', 0.0):.6g}",
              f"M2{t} {y} g1{t} 0 0 {NM} W={fmt(dz.w1 / dz.k)} L={fmt(L_N)} delvto={dv.get(f'M2{t}', 0.0):.6g}",
              f"M3{t} {x} g3{t} {y} 0 {NM} W={fmt(dz.w3m * dz.w1 / dz.k)} L={fmt(L_N)}", f"C{node} {node} 0 5f"]
        L += _ota(f"a{t}", node, "vref", f"g1{t}", dz.wi1, dz.li1, dz.wm1, dz.lm1, dz.wt1, dz.lt, dv)
        L += _ota(f"b{t}", "vref", y, f"g3{t}", dz.wi2, dz.li2, dz.wm2, dz.lm2, dz.wt2, dz.lt, dv)
    # input switches: phase 1: rp -> nA, rn -> nB ; phase 2: rp -> nB, rn -> nA
    L += tgate("i1p", "rp", "nA", "ph1", "ph1b", ch.w_in) + tgate("i1n", "rn", "nB", "ph1", "ph1b", ch.w_in)
    # output switches: phase 1: xA -> S+, xB -> S- ; phase 2: xA -> S-, xB -> S+
    L += tgate("o1a", "xA", "sp", "ph1", "ph1b", ch.w_out) + tgate("o1b", "xB", "sn", "ph1", "ph1b", ch.w_out)
    if chopped:
        L += tgate("i2p", "rp", "nB", "ph2", "ph2b", ch.w_in) + tgate("i2n", "rn", "nA", "ph2", "ph2b", ch.w_in)
        L += tgate("o2a", "xA", "sn", "ph2", "ph2b", ch.w_out) + tgate("o2b", "xB", "sp", "ph2", "ph2b", ch.w_out)
    # integration capacitors (reset level V_S0 held by a 1 Gohm to a reference so the operating point exists), threshold sink on S-
    L += [f"Cp sp 0 {fmt(ch.c_int * (1 + c_mis_p))}", f"Cn sn 0 {fmt(ch.c_int)}", f"Vrs rs 0 {V_S0}", f"Vrst rst 0 PULSE({VDD} 0 {fmt(t0 - 0.1e-9)} 10p 10p 1 2)", ".model SWM SW(Vt=0.55 Vh=0.05 Ron=50 Roff=1e15)",
          "Spr sp rs rst 0 SWM", "Snr sn rs rst 0 SWM"]
    if i_thr:
        L += [f"Ithr sn 0 DC {i_thr}"]
    return L


def run_charges(dz: Design, m: int, pos0: float, ch: Chop, T: float, dv: dict | None = None, t0: float = 0.3e-9, chopped: bool = True, temp: float = 27.0, c_mis_p: float = 0.0) -> tuple[float, float, dict]:
    """Charges Q+ and Q- (C, referred to the array side: x k) integrated over [t0, t0 + T + t_tail], from the final capacitor voltages relative to the reset level."""
    tend = t0 + T + ch.t_tail
    d = run_wrdata(netlist(dz, m, pos0, ch, T, t0, dv, chopped=chopped, temp=temp, c_mis_p=c_mis_p) + [f".tran 2p {fmt(tend)}"], ["v(sp)", "v(sn)", "v(nA)", "v(nB)"])
    qp = (V_S0 - float(d["v(sp)"][-1])) * ch.c_int * (1 + c_mis_p) * dz.k
    qn = (V_S0 - float(d["v(sn)"][-1])) * ch.c_int * dz.k
    return qp, qn, d


def ideal_charges(m: int, pos0: float, ch: Chop, T: float, t0: float = 0.3e-9, a: int = C.G_1C) -> tuple[float, float]:
    tend = t0 + T + ch.t_tail
    dz = Design()
    d = run_wrdata(netlist(dz, m, pos0, ch, T, t0, ideal=True) + [f".tran 2p {fmt(tend)}"], ["i(Vrp)", "i(Vrn)"])
    t = d["time"]
    return float(np.trapezoid(d["i(vrp)"], t)), float(np.trapezoid(d["i(vrn)"], t))
