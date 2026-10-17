"""F1: the four candidate front-end topologies, each as a transistor-level single-bitline channel on the PTM 45 nm LP card, evaluated on the SAME array load: the far group (8 active rows, nearest row
505 pitches from the sense node, 0.72 ohm/pitch; worst differential step 30.49 uA, 1C) and the near group, driven by the same row pulse, with the 1C ReRAM resistor model (sense.port).
Measured per topology: (1) how well the virtual ground holds - the charge the array delivers into the node over the read window, divided by what an ideal virtual ground would draw, minimum over m = 1, 3, 5, 7,
and the sense-node excursion during the pulse; (2) input-referred noise (ngspice .noise, device level) for the integration windows; (3) supply current (bias power) and the bitline voltage the topology forces
(which sets the array's row supply: array energy x (V_node + V_READ)/V_READ); (4) the gate area of the transistors. (a) and (d) are shown with the OTA scaled x1, x4, x16 in current (the single-stage OTA of
the other candidates is the same cell); (d) is also shown with a two-stage Miller OTA (d2); (b) is the differential conveyor of sense.mc. Usage: python -m sense.run_topologies"""
from __future__ import annotations

import json
from multiprocessing import Pool

import numpy as np

import device.constants as C
import paths as RP
from sense import collect as K, mc, port as P, topo_a, topo_c, topo_d, topo_d2
from sense.acnoise import noise_spectrum
from sense.cal import DESIGN
from sense.metrics import sigma_i
from sense.ngs import run, scalars

TS = (0.5e-9, 1e-9)
MS = (1, 3, 5, 7)
SCALES = (1, 4, 16)


def _ota(scale):
    return dict(wi=8e-6 * scale, wt=8e-6 * scale, wm=4e-6 * scale)


def step_eta(fn, pos0, T, **kw):
    """Differential step actually collected / ideal differential step (min over m), mean per-channel collection efficiency, node excursion (mV)."""
    steps, etas, lo_all, hi_all = [], [], 1.0, 0.0
    for m in MS:
        qp, lo1, hi1 = fn(m, pos0, T, side="p", **kw)
        qn, lo2, hi2 = fn(m, pos0, T, side="n", **kw)
        idp = K.ideal_charge(m, 8 - m, pos0, T); idn = K.ideal_charge(8 - m, m, pos0, T)
        steps.append((qp - qn) / (idp - idn)); etas.append(0.5 * (qp / idp + qn / idn)); lo_all, hi_all = min(lo_all, lo1, lo2), max(hi_all, hi1, hi2)
    return dict(step_ratio_min=float(np.min(steps)), eta_mean=float(np.mean(etas)), vn_min_mV=lo_all * 1e3, vn_max_mV=hi_all * 1e3)


def d2_collect(m, pos0, T, side="p", **kw):
    qm, qa, lo, hi, qi = topo_d2.collect(m, pos0, T, side=side, cf=1e-12, vbp=0.4539)
    return qa, lo, hi


def _job(a):
    nm, scale, gname, T = a
    pos0 = P.FAR_POS0 if gname == "far" else P.NEAR_POS0
    if nm == "a":
        r = step_eta(K.collect_a, pos0, T, rf=500.0, ota=_ota(scale))
    elif nm == "d":
        r = step_eta(K.collect_d, pos0, T, cf=1e-12, ota=_ota(scale))
    elif nm == "c":
        r = step_eta(K.collect_c, pos0, T)
    elif nm == "d2":
        r = step_eta(d2_collect, pos0, T)
    else:
        dz = mc.Design(**DESIGN)
        f = mc.fidelity(dz, T, pos0, t_tail=0.3e-9)
        r = dict(step_ratio_min=float(f["step_ratio_min"]), eta_mean=float(np.mean([np.mean(v) for v in f["eta"].values()])), vn_min_mV=f["vn_mV"][0], vn_max_mV=f["vn_mV"][1])
    return dict(topology=nm, ota_scale=scale, group=gname, T=T, **r)


def _supply(nm, scale):
    ip, _ = P.levels(P.FAR_POS0)
    if nm == "a":
        L = topo_a.netlist(4, P.FAR_POS0, 500.0, ip[4], ota=_ota(scale))
    elif nm == "d":
        L = topo_d.netlist(4, P.FAR_POS0, 1e-12, ota=_ota(scale))
    elif nm == "d2":
        L = topo_d2.netlist(4, P.FAR_POS0, 1e-12, vbp=0.4539, row=["Vrow row 0 0.25"])
    elif nm == "c":
        L = topo_c.netlist(4, P.FAR_POS0, w=20e-6, vrow=0.64)
    else:
        L = None
    if L is None:
        return None
    o = scalars(run("\n".join(L + [".op", ".control", "set noaskquit", "run", "print i(Vdd) v(n)", ".endc", ".end"]) + "\n"))
    return float(-o["i(vdd)"] * 1e6), float(o["v(n)"])


def noise_all():
    out = {}
    far = P.FAR_POS0
    ip, _ = P.levels(far)
    for s in SCALES:
        L = topo_a.netlist(4, far, 500.0, ip[4], ota=_ota(s))
        o = noise_spectrum(L, "o", "Iin", fmin=1e6, fmax=2e10); f, sp = o["f"], o["s_in"]
        out[f"a x{s}"] = {f"{T*1e9:g}": sigma_i(f, sp, T) * 1e6 for T in (0.5e-9, 1e-9, 2e-9)}
        L = topo_d.netlist(4, far, 1e-12, ota=_ota(s), rb="1G") + ["Iin 0 n DC 0 AC 1"]
        o = noise_spectrum(L, "o", "Iin", fmin=1e6, fmax=2e10); f, sp = o["f"], o["s_in"]
        out[f"d x{s}"] = {f"{T*1e9:g}": sigma_i(f, sp, T) * 1e6 for T in (0.5e-9, 1e-9, 2e-9)}
    L = topo_c.netlist(4, far, w=20e-6, vrow=0.64)
    o = noise_spectrum(L, "n", "Iin", fmin=1e6, fmax=2e10); f, sp = o["f"], o["s_in"]
    out["c"] = {f"{T*1e9:g}": sigma_i(f, sp, T) * 1e6 for T in (0.5e-9, 1e-9, 2e-9)}
    L = topo_d2.netlist(4, far, 1e-12, vbp=0.4539, row=["Vrow row 0 0.25"], rb="1G") + ["Iin 0 n DC 0 AC 1"]
    o = noise_spectrum(L, "o", "Iin", fmin=1e6, fmax=2e10); f, sp = o["f"], o["s_in"]
    out["d2"] = {f"{T*1e9:g}": sigma_i(f, sp, T) * 1e6 for T in (0.5e-9, 1e-9, 2e-9)}
    n = mc.noise(mc.Design(**DESIGN), windows=(0.5e-9, 1e-9, 2e-9))
    out["b (differential channel)"] = {f"{T*1e9:g}": v * 1e6 for T, v in n["sigma"].items()}
    return out


def main() -> None:
    jobs = [(nm, s, g, T) for nm in ("a", "d") for s in SCALES for g in ("far", "near") for T in TS]
    jobs += [(nm, 1, g, T) for nm in ("b", "c", "d2") for g in ("far", "near") for T in TS]
    with Pool(10) as p:
        rows = p.map(_job, jobs)
    res = dict(rows=rows, noise_sigma_uA=noise_all(), supply={}, zin_b={})
    for nm, s in [("a", 1), ("a", 4), ("a", 16), ("d", 1), ("d", 4), ("d", 16), ("c", 1), ("d2", 1)]:
        res["supply"][f"{nm} x{s}"] = _supply(nm, s)
    dz = mc.Design(**DESIGN)
    res["supply"]["b (per differential channel)"] = (mc.bias_current(dz)["i_vdd_a"] * 1e6, mc.V_VG)
    res["zin_b"] = mc.input_impedance(dz)
    res["gate_area_um2"] = {"b (per differential channel)": mc.gate_area_um2(dz)}
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "topology_comparison.json").write_text(json.dumps(res, indent=1, default=float))
    for r in rows:
        print(f"{r['topology']} x{r['ota_scale']} {r['group']} T {r['T']*1e9:g} ns: step {r['step_ratio_min']:.2f} eta {r['eta_mean']:.2f} node {r['vn_min_mV']:.0f}..{r['vn_max_mV']:.0f} mV")
    print("noise", {k: {t: round(v, 2) for t, v in d.items()} for k, d in res["noise_sigma_uA"].items()})
    print("supply (uA, node V)", res["supply"], "\nZin b", res["zin_b"])


if __name__ == "__main__":
    main()
