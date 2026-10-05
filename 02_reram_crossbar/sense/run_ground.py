"""F1: does the 69 mA return current in the ground rails move the front-end? The local ground (the sources of the conveyor sinks M1/M2) is raised by the rail IR drop 1C measured (1.8 mV far-group macro, 3.2 mV near, 5 mV swept)
while the amplifier references stay at the absolute reference: change of each channel's copy current (referred to the array) and of the sense-node voltage, DC. Usage: python -m sense.run_ground"""
from __future__ import annotations

import json

import paths as RP
from sense import mc, port as P
from sense.cal import DESIGN
from sense.ngs import run, scalars


def main() -> None:
    dz = mc.Design(**DESIGN)
    out = {}
    for pos, nm in ((P.FAR_POS0, "far"), (P.NEAR_POS0, "near")):
        out[nm] = {}
        for m in (1, 4, 7):
            res = {}
            for gr in (0.0, 0.003, 0.005):
                o = scalars(run("\n".join(mc.netlist(dz, m, pos, gnd_rise=gr) + [".op", ".control", "set noaskquit", "run", "print i(Vxp) i(Vxn) v(np) v(nn)", ".endc", ".end"]) + "\n"))
                res[gr] = (-o["i(vxp)"] * dz.k, -o["i(vxn)"] * dz.k, o["v(np)"], o["v(nn)"])
            out[nm][str(m)] = {f"{int(gr*1e3)}mV": dict(d_ip_uA=(res[gr][0] - res[0.0][0]) * 1e6, d_in_uA=(res[gr][1] - res[0.0][1]) * 1e6, d_diff_uA=((res[gr][0] - res[0.0][0]) - (res[gr][1] - res[0.0][1])) * 1e6,
                                                         d_node_mV=(res[gr][2] - res[0.0][2]) * 1e3) for gr in (0.003, 0.005)}
    (RP.SENSE / "ground_rise.json").write_text(json.dumps(out, indent=1))
    for nm, d in out.items():
        print(nm, {m: {k: round(v["d_diff_uA"], 2) for k, v in x.items()} for m, x in d.items()})


if __name__ == "__main__":
    main()
