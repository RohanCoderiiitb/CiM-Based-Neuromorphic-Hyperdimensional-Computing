"""Mismatch Monte-Carlo of the chosen differential front-end (b): Pelgrom Vth mismatch (sigma = AVT/sqrt(W L), AVT [ASSUM] from 1A) imposed per device through BSIM4 `delvto`, DC operating point of the whole
channel (two regulated conveyors, copies 1:k, PMOS mirror, summing node S held by a 1 kohm / 0.6 V reference). Outputs the differential copy current referred to the array side (x k) so that
error = I_d(sample) - I_d(nominal) is in the budget's units (the ladder thresholds are calibrated on the nominal levels). Also CMRR: equal current added to both bitlines."""
from __future__ import annotations

from multiprocessing import Pool

import numpy as np

import device.constants as C
from sense import port as P
from sense.cells import NM, PM
from sense.ngs import VDD, f as fmt, header, run, run_wrdata, scalars

V_VG = 0.25
V_S = 0.60
L_N = 45e-9


class Design:
    """Sizes of the (b) front-end; every field is swept in F2."""
    def __init__(self, k=4.0, w1=15e-6, vb=0.47, wi1=8e-6, li1=90e-9, wm1=4e-6, lm1=180e-9, wt1=8e-6, wi2=8e-6, li2=90e-9, wm2=4e-6, lm2=180e-9, wt2=8e-6, wp=4e-6, lp=90e-9, w3m=2.0, lt=90e-9, vs=0.60):
        self.__dict__.update(locals())
        del self.__dict__["self"]

    def devices(self) -> dict:
        """name -> (W, L) of every device that can mismatch."""
        k, d = self.k, {}
        for t in "pn":
            d[f"M1{t}"] = (self.w1, L_N); d[f"M2{t}"] = (self.w1 / k, L_N)
            for o, wi, li, wm, lm in (("a", self.wi1, self.li1, self.wm1, self.lm1), ("b", self.wi2, self.li2, self.wm2, self.lm2)):
                d[f"{o}{t}_p1"] = (wi, li); d[f"{o}{t}_p2"] = (wi, li); d[f"{o}{t}_n3"] = (wm, lm); d[f"{o}{t}_n4"] = (wm, lm)
        d["Mp1"] = (self.wp, self.lp); d["Mp2"] = (self.wp, self.lp)
        return d


def _ota(tag: str, inp: str, inn: str, out: str, wi, li, wm, lm, wt, lt, dv: dict, vb="vb") -> list[str]:
    g = lambda n: f" delvto={dv.get(n, 0.0):.6g}"
    return [f"Mt{tag} nt{tag} {vb} vdd vdd {PM} W={fmt(wt)} L={fmt(lt)}",
            f"Mp1{tag} n1{tag} {inp} nt{tag} vdd {PM} W={fmt(wi)} L={fmt(li)}" + g(f"{tag}_p1"), f"Mp2{tag} {out} {inn} nt{tag} vdd {PM} W={fmt(wi)} L={fmt(li)}" + g(f"{tag}_p2"),
            f"Mn3{tag} n1{tag} n1{tag} 0 0 {NM} W={fmt(wm)} L={fmt(lm)}" + g(f"{tag}_n3"), f"Mn4{tag} {out} n1{tag} 0 0 {NM} W={fmt(wm)} L={fmt(lm)}" + g(f"{tag}_n4")]


def netlist(dz: Design, m: int, pos0: float, dv: dict | None = None, icm: float = 0.0, row_dc: bool = True, a: int = C.G_1C, i_thr: float = 0.0, extra: list[str] | None = None, pulse: tuple | None = None, ideal: bool = False, temp: float = 27.0, array: bool = True, gnd_rise: float = 0.0) -> list[str]:
    """pulse = (t0, T, t_rise): row drive is a pulse instead of DC. ideal=True replaces both conveyors by ideal voltage sources at V_VG (the reference virtual ground); the currents are then i(Vnp), i(Vnn)."""
    dv = dv or {}
    L = header("b flat channel", temp=temp) + [f"Vgl gl 0 {gnd_rise}", f"Vdd vdd 0 {VDD}", f"Vb vb 0 {dz.vb}", f"Vref vref 0 {V_VG}", (f"Vrow row 0 {V_VG + (C.V_READ if row_dc else 0.0)}" if pulse is None else f"Vrow row 0 PULSE({V_VG} {V_VG + C.V_READ} {fmt(pulse[0])} {fmt(pulse[2])} {fmt(pulse[2])} {fmt(pulse[1])} 1)"), f"Vs sref 0 {dz.vs}", "RL s sref 1000 noisy=0"]
    for t, (nl, nh) in (("p", (m, a - m)), ("n", (a - m, m))):
        node, y, x = f"n{t}", f"y{t}", f"x{t}" if t == "p" else "xnd"
        L += [f"M1{t} {node} g1{t} gl 0 {NM} W={fmt(dz.w1)} L={fmt(L_N)} delvto={dv.get(f'M1{t}', 0.0):.6g}",
              f"M2{t} {y} g1{t} gl 0 {NM} W={fmt(dz.w1 / dz.k)} L={fmt(L_N)} delvto={dv.get(f'M2{t}', 0.0):.6g}",
              f"M3{t} {x} g3{t} {y} 0 {NM} W={fmt(dz.w3m * dz.w1 / dz.k)} L={fmt(L_N)}"]
        if ideal:
            L = L[:-3] + [f"V{node} {node} 0 {V_VG}"]
        else:
            L += _ota(f"a{t}", node, "vref", f"g1{t}", dz.wi1, dz.li1, dz.wm1, dz.lm1, dz.wt1, dz.lt, dv)
            L += _ota(f"b{t}", "vref", y, f"g3{t}", dz.wi2, dz.li2, dz.wm2, dz.lm2, dz.wt2, dz.lt, dv)
        L += (P.netlist(t, "row", node, nl, nh, pos0, a=a) if array else []) + [f"C{node} {node} 0 5f"]
        if icm:
            L += [f"Icm{t} 0 {node} DC {icm}"]
    if ideal:
        return L + (extra or [])
    L += [f"Mp1 xn xn vdd vdd {PM} W={fmt(dz.wp)} L={fmt(dz.lp)} delvto={dv.get('Mp1', 0.0):.6g}", f"Mp2 s xn vdd vdd {PM} W={fmt(dz.wp)} L={fmt(dz.lp)} delvto={dv.get('Mp2', 0.0):.6g}", "Vxp xp s 0", "Vxn xnd xn 0"]
    if i_thr:
        L += [f"Ithr s 0 DC {i_thr}"]
    return L + (extra or [])


def i_channels(dz: Design, m: int, pos0: float, dv: dict | None = None, icm: float = 0.0, temp: float = 27.0):
    """(I_p, I_n) copy currents x k referred to the array side (A, each positive for a current sunk from the sense node): Vxp carries the BL+ copy, Vxn the BL- copy."""
    o = scalars(run("\n".join(netlist(dz, m, pos0, dv, icm, temp=temp) + [".op", ".control", "set noaskquit", "run", "print i(Vxp) i(Vxn) i(Vs)", ".endc", ".end"]) + "\n"))
    return -o["i(vxp)"] * dz.k, -o["i(vxn)"] * dz.k


def i_diff(dz: Design, m: int, pos0: float, dv: dict | None = None, icm: float = 0.0) -> float:
    """Differential current referred to the array side (A): current the BL+ copy sinks from S minus the BL- copy mirrored in, times k. i(Vs): positive = into the source."""
    o = scalars(run("\n".join(netlist(dz, m, pos0, dv, icm) + [".op", ".control", "set noaskquit", "run", "print i(Vs) v(np) v(nn) v(s)", ".endc", ".end"]) + "\n"))
    return o["i(vs)"] * dz.k


def draw(dz: Design, rng, avt_mv_um: float = C.AVT_MV_UM) -> dict:
    return {n: float(rng.normal(0.0, avt_mv_um * 1e-3 / np.sqrt(w * l * 1e12))) for n, (w, l) in dz.devices().items()}


def _one(args):
    dz, m, pos0, dv, icm = args
    try:
        return i_diff(dz, m, pos0, dv, icm)
    except Exception:
        return float("nan")


def monte_carlo(dz: Design, pos0: float, ms=(1, 4, 7), n: int = 60, seed: int = 1, avt: float = C.AVT_MV_UM, pool: Pool | None = None) -> dict:
    """Error (sample - nominal) of the differential input-referred current, per level m, over n device draws; sigma and the split by group of devices."""
    rng = np.random.default_rng(seed)
    draws = [draw(dz, rng, avt) for _ in range(n)]
    own = pool is None
    pool = pool or Pool(10)
    try:
        nom = pool.map(_one, [(dz, m, pos0, None, 0.0) for m in ms])
        res = {m: np.array(pool.map(_one, [(dz, m, pos0, d, 0.0) for d in draws])) - nom[i] for i, m in enumerate(ms)}
    finally:
        if own:
            pool.close()
    return dict(nominal={m: nom[i] for i, m in enumerate(ms)}, err=res, sigma={m: float(np.nanstd(v)) for m, v in res.items()}, draws=draws)


def cmrr(dz: Design, pos0: float, m: int = 4, icm: float = 20e-6, dv: dict | None = None) -> float:
    """Differential error per unit of common-mode current (equal extra current into both bitlines)."""
    return (i_diff(dz, m, pos0, dv, icm) - i_diff(dz, m, pos0, dv, 0.0)) / icm


# ------------------------------------------------------------------------------------------------ noise, bias power, area
def noise(dz: Design, m: int = 4, pos0: float = P.FAR_POS0, windows=(0.25e-9, 0.5e-9, 1e-9, 2e-9)) -> dict:
    """Device-level noise of the whole differential channel (both conveyors, mirror, S node; array resistors noisy): input-referred (array side) current noise, windowed by an ideal integrate-over-T
    (sinc^2) of the OUTPUT noise at S, normalised by the DC transimpedance of the BL+ input (see sense.metrics.sigma_i_out)."""
    from sense.acnoise import noise_spectrum
    from sense.metrics import sigma_i_out
    L = netlist(dz, m, pos0, extra=["Iin 0 np DC 0 AC 1"])
    o = noise_spectrum(L, "s", "Iin", fmin=1e6, fmax=2e10)
    h0 = float(np.sqrt(o["s_out"][0] / o["s_in"][0]))
    return dict(f=o["f"], s_out=o["s_out"], contrib=o["contrib"], h0=h0, sigma={T: sigma_i_out(o["f"], o["s_out"], h0, T) for T in windows})


def bias_current(dz: Design, m: int = 4, pos0: float = P.FAR_POS0) -> dict:
    """DC supply current of one differential channel (two conveyors, each two OTAs + copy branch, plus the mirror): sense bias power = VDD x this."""
    o = scalars(run("\n".join(netlist(dz, m, pos0) + [".op", ".control", "set noaskquit", "run", "print i(Vdd) i(Vb)", ".endc", ".end"]) + "\n"))
    return dict(i_vdd_a=-o["i(vdd)"])


def gate_area_um2(dz: Design) -> float:
    """Sum of W x L of every transistor of one channel (BL+ and BL-): OTA tails, pairs, mirrors, M1, M2, M3, PMOS mirror."""
    a = 0.0
    for t in "pn":
        a += dz.w1 * L_N + dz.w1 / dz.k * L_N + dz.w3m * dz.w1 / dz.k * L_N
        for wi, li, wm, lm, wt in ((dz.wi1, dz.li1, dz.wm1, dz.lm1, dz.wt1), (dz.wi2, dz.li2, dz.wm2, dz.lm2, dz.wt2)):
            a += 2 * wi * li + 2 * wm * lm + wt * dz.lt
    a += 2 * dz.wp * dz.lp
    return a * 1e12


def fidelity(dz: Design, T: float, pos0: float = P.FAR_POS0, ms=(1, 3, 5, 7), t0: float = 0.3e-9, t_rise: float = 20e-12, t_tail: float = 0.3e-9, a: int = C.G_1C) -> dict:
    """Differential charge collected by the front-end (copy currents x k, integrated from the pulse start to T + t_tail) divided by the same charge with an ideal virtual ground at V_VG (same array
    transient). min over m of the ratio of the DIFFERENTIAL (BL+ minus BL-) charges; per-channel collection efficiency also returned; V_N excursion of the sense nodes during the pulse."""
    out = dict(step_ratio={}, eta={}, vn_mV=[1e9, -1e9])
    for m in ms:
        pulse = (t0, T, t_rise)
        tend = t0 + T + t_tail
        d = run_wrdata(netlist(dz, m, pos0, pulse=pulse) + [f".tran 2p {fmt(tend)}"], ["i(Vxp)", "i(Vxn)", "v(np)", "v(nn)"])
        r = run_wrdata(netlist(dz, m, pos0, pulse=pulse, ideal=True) + [f".tran 2p {fmt(tend)}"], ["i(Vnp)", "i(Vnn)"])
        t = d["time"]; s_ = t >= t0 - 1e-12
        qp = float(np.trapezoid(-d["i(vxp)"][s_], t[s_])) * dz.k; qn = float(np.trapezoid(-d["i(vxn)"][s_], t[s_])) * dz.k
        tr = r["time"]; sr = tr >= t0 - 1e-12
        ip = float(np.trapezoid(r["i(vnp)"][sr], tr[sr])); inn = float(np.trapezoid(r["i(vnn)"][sr], tr[sr]))
        out["step_ratio"][m] = (qp - qn) / (ip - inn); out["eta"][m] = (qp / ip, qn / inn)
        sel = (t > t0 + 0.05e-9) & (t < t0 + T)
        out["vn_mV"] = [min(out["vn_mV"][0], 1e3 * min(d["v(np)"][sel].min(), d["v(nn)"][sel].min())), max(out["vn_mV"][1], 1e3 * max(d["v(np)"][sel].max(), d["v(nn)"][sel].max()))]
    out["step_ratio_min"] = min(abs(v) for v in out["step_ratio"].values())
    return out


def charges(dz: Design, m: int, pos0: float, dv: dict | None, T: float, t0: float = 0.3e-9, t_rise: float = 20e-12, t_tail: float = 0.3e-9, temp: float = 27.0) -> tuple[float, float]:
    """(Q_p, Q_n): charge of the BL+ / BL- copies x k (referred to the array side) collected over [t0, T + t_tail + t0] for a row pulse of length T, with the mismatch draw dv."""
    d = run_wrdata(netlist(dz, m, pos0, dv, pulse=(t0, T, t_rise), temp=temp) + [f".tran 2p {fmt(t0 + T + t_tail)}"], ["i(Vxp)", "i(Vxn)"])
    t = d["time"]; s_ = t >= t0 - 1e-12
    return float(np.trapezoid(-d["i(vxp)"][s_], t[s_])) * dz.k, float(np.trapezoid(-d["i(vxn)"][s_], t[s_])) * dz.k


def input_impedance(dz: Design, freqs=(1e8, 5e8, 1e9, 2e9), i_bias: float = 100e-6) -> dict:
    """Small-signal impedance seen by the array at the BL+ sense node (|v(np)| for 1 A of AC current), array removed, the conveyor biased by a DC current i_bias (a typical array current): the resistance the
    sense node adds in series with the bitline (the virtual ground holds if it is small against the ~195 ohm of 8 LRS branches in parallel)."""
    import re
    L = netlist(dz, 4, P.FAR_POS0, array=False, extra=[f"Ibias 0 np DC {i_bias}", "Iac 0 np DC 0 AC 1"])
    out = {}
    for fr in freqs:
        o = run("\n".join(L + [f".ac lin 1 {fr:g} {fr:g}", ".control", "set noaskquit", "run", "print mag(v(np))", ".endc", ".end"]) + "\n")
        m = re.search(r"mag\(v\(np\)\)\s*=\s*([-+0-9.e]+)", o)
        out[f"{fr:g}"] = float(m.group(1)) if m else float("nan")
    return out
