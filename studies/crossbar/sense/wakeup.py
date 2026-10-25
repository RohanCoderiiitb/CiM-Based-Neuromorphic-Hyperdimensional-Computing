"""Optimisation item 8: the front-end wake-up. 61 % of the sense bias is the power-up ramp (3.2 ns at vb 0.50) before a 1 ns pulse. Two fixes, simulated on the 1F front-end (ngspice, same netlist as sense.enable):
  (a) BOOST: during the ramp the OTA tail bias is driven harder (vb_boost < vb: more tail current) for t_boost, then drops to the standing vb (0.50, 99 uA idle). Settling is measured as in
      sense.enable (both bitline nodes within 1 mV of their final value); the energy is the integral of the supply current x 1.1 V from the enable to the settle instant.
  (b) KEEP POWERED across consecutive sensing windows instead of restarting: the cost of staying on for a gap is VDD x I_idle x gap; of restarting it is the ramp energy of (a). Break-even gap = E_ramp/(VDD I_idle).
Usage: python -m sense.wakeup"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from sense import mc, port as P
from sense.cal import DESIGN
from sense.ngs import f as fmt, run_wrdata

VDD = 1.1


def ramp(dz: mc.Design, vb_final: float, boost: float | None, t_boost: float, t_end: float = 8e-9) -> dict:
    L = mc.netlist(dz, 4, P.FAR_POS0, pulse=(50e-9, 1e-9, 20e-12))
    src = f"PULSE(1.1 {vb_final} 0.1n 50p 50p 1 2)" if boost is None else f"PWL(0 1.1 0.1n 1.1 0.15n {boost} {fmt(0.1e-9 + t_boost)} {boost} {fmt(0.15e-9 + t_boost)} {vb_final} 1 {vb_final})"
    L = [ln if not ln.startswith("Vb ") else f"Vb vb 0 {src}" for ln in L]
    d = run_wrdata(L + [f".tran 2p {fmt(t_end)} uic", ".ic v(vdd)=1.1"], ["v(np)", "v(nn)", "i(Vdd)"])
    t = d["time"]
    ok = (abs(d["v(np)"] - d["v(np)"][-1]) < 1e-3) & (abs(d["v(nn)"] - d["v(nn)"][-1]) < 1e-3)
    bad = np.where(~ok)[0]
    t_ok = float(t[bad[-1]] - 0.1e-9) if len(bad) else 0.0
    i = -d["i(vdd)"]
    m = (t >= 0.1e-9) & (t <= 0.1e-9 + t_ok)
    e_ramp = float(np.trapezoid(i[m], t[m]) * VDD) if m.sum() > 1 else 0.0
    return dict(t_settle_ns=t_ok * 1e9, e_ramp_pJ_per_channel=e_ramp * 1e12, i_final_uA=float(i[-1] * 1e6), i_peak_uA=float(i[m].max() * 1e6) if m.sum() else 0.0)


def main() -> None:
    des = dict(DESIGN); des["vb"] = 0.50
    dz = mc.Design(**des)
    base = ramp(dz, 0.50, None, 0)
    print("baseline vb 0.50:", base, flush=True)
    rows = []
    for vbb in (0.46, 0.42, 0.38, 0.34):
        for tb in (0.3e-9, 0.6e-9, 1.0e-9, 1.5e-9):
            r = ramp(dz, 0.50, vbb, tb)
            r.update(vb_boost=vbb, t_boost_ns=tb * 1e9)
            rows.append(r)
            print(r, flush=True)
    i_idle = base["i_final_uA"] * 1e-6
    out = dict(baseline=base, boost=rows, breakeven_gap_ns_baseline=base["e_ramp_pJ_per_channel"] * 1e-12 / (VDD * i_idle) * 1e9)
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "wakeup.json").write_text(json.dumps(out, indent=1))




def recovery() -> dict:
    """KEEP-POWERED check: after a read pulse (T = 1 ns, m matching rows) how long until both bitline nodes are back within 1 mV (and 3 mV) of their pre-pulse value, i.e. when the next
    pass may start on the same powered channel. Far and near group, m = 1, 4, 8."""
    des = dict(DESIGN); des["vb"] = 0.50
    dz = mc.Design(**des)
    out = {}
    for pos, nm in ((P.FAR_POS0, "far"), (P.NEAR_POS0, "near")):
        for m in (1, 4, 8):
            L = mc.netlist(dz, m, pos, pulse=(3e-9, 1e-9, 20e-12))
            d = run_wrdata(L + [".tran 2p 12n uic", ".ic v(vdd)=1.1"], ["v(np)", "v(nn)", "i(Vdd)"])
            t = d["time"]
            pre = (t > 2.5e-9) & (t < 2.95e-9)
            base_p, base_n = d["v(np)"][pre].mean(), d["v(nn)"][pre].mean()
            dev = np.maximum(abs(d["v(np)"] - base_p), abs(d["v(nn)"] - base_n))
            end = 3e-9 + 1e-9
            rec = {}
            for tol in (1e-3, 3e-3):
                bad = np.where((t > end) & (dev > tol))[0]
                rec[f"t_recover_{int(tol*1e3)}mV_ns"] = float((t[bad[-1]] - end) * 1e9) if len(bad) else 0.0
            rec["peak_dev_mV"] = float(dev[(t > 3e-9)].max() * 1e3)
            out[f"{nm}_m{m}"] = rec
            print(nm, m, rec, flush=True)
    return out




if __name__ == "__main__":
    import sys
    main() if "--recovery" not in sys.argv else RP.SENSE.joinpath("wakeup_recovery.json").write_text(json.dumps(recovery(), indent=1))
