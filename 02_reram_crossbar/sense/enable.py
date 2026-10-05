"""Power-up of the front-end (b) from a gated-off state: the OTA tail bias vb steps from VDD (off) to its operating value at t = 0 with the array NOT yet driven; how long until both bitlines sit within 1 mV of their final value
and the cascode nodes have settled (the earliest moment a read pulse may start)? Also the quiescent supply current with the array idle, and the supply current for each read state (to separate bias from signal).
Usage: python -m sense.enable"""
from __future__ import annotations

import json

import numpy as np

import device.constants as C
import paths as RP
from sense import mc, port as P
from sense.cal import DESIGN
from sense.ngs import f as fmt, run_wrdata, scalars, run


def power_up(dz: mc.Design, t_end: float = 6e-9) -> dict:
    L = mc.netlist(dz, 4, P.FAR_POS0, pulse=(50e-9, 1e-9, 20e-12))                       # array idle (pulse far in the future): row at V_VG
    L = [ln if not ln.startswith("Vb ") else f"Vb vb 0 PULSE(1.1 {dz.vb} 0.1n 50p 50p 1 2)" for ln in L]
    d = run_wrdata(L + [f".tran 2p {fmt(t_end)} uic", ".ic v(vdd)=1.1"], ["v(np)", "v(nn)", "v(yp)", "v(g1p)", "i(Vdd)"])
    t = d["time"]
    ok = (abs(d["v(np)"] - d["v(np)"][-1]) < 1e-3) & (abs(d["v(nn)"] - d["v(nn)"][-1]) < 1e-3)
    bad = np.where(~ok)[0]
    t_ok = float(t[bad[-1]] - 0.1e-9) if len(bad) else 0.0
    return dict(t_settle_ns=t_ok * 1e9, i_final_uA=float(-d["i(vdd)"][-1] * 1e6))


def supply_by_state(dz: mc.Design) -> dict:
    out = {}
    for pos, nm in ((P.FAR_POS0, "far"), (P.NEAR_POS0, "near")):
        out[nm] = {}
        for m in range(9):
            o = scalars(run("\n".join(mc.netlist(dz, m, pos) + [".op", ".control", "set noaskquit", "run", "print i(Vdd)", ".endc", ".end"]) + "\n"))
            out[nm][str(m)] = float(-o["i(vdd)"] * 1e6)
        o = scalars(run("\n".join(mc.netlist(dz, 4, pos, row_dc=False) + [".op", ".control", "set noaskquit", "run", "print i(Vdd)", ".endc", ".end"]) + "\n"))
        out[nm]["idle"] = float(-o["i(vdd)"] * 1e6)
    return out


def main() -> None:
    res = {}
    for vb in (0.42, 0.46, 0.50):
        des = dict(DESIGN); des["vb"] = vb
        dz = mc.Design(**des)
        res[str(vb)] = dict(power_up=power_up(dz), supply_uA=supply_by_state(dz))
        print(vb, res[str(vb)]["power_up"], {k: round(v["idle"], 1) for k, v in res[str(vb)]["supply_uA"].items()}, {k: [round(v[str(m)], 1) for m in (0, 4, 8)] for k, v in res[str(vb)]["supply_uA"].items()})
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "enable_and_supply.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
