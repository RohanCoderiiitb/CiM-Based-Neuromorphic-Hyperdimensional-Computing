"""1C: gate capacitance of the access transistor (WL load) from the PTM 45 nm LP BSIM4 card, by charging the gate with a ramp (source = drain = bulk = 0,
then with the read bias on drain/source). Writes results/device_characterization/access_transistor_gate_cap.json. Used for the word-line switching energy C_WL * V_WL^2 (C1d).
Usage: python -m validate.gate_cap"""
from __future__ import annotations

import paths as RP

import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

import device.constants as C
from spice.netlist import OPTIONS, PTM_LIB, _f


def gate_cap(w_um: float, vd: float = 0.0, vs: float = 0.0, vdd: float = C.V_WL) -> float:
    deck = "\n".join(["gatecap", OPTIONS.replace("reltol=1e-10", "reltol=1e-6"), f".include {PTM_LIB}", f"Vd d 0 {_f(vd)}", f"Vs s 0 {_f(vs)}",
                      f"Vg g 0 PWL(0 0 1n 0 1.1n {_f(vdd)} 3n {_f(vdd)})",
                      f"M1 d g s 0 ptm45n_lp W={_f(w_um * 1e-6)} L={_f(C.TX_L_NM * 1e-9)}", ".tran 2p 3n", ".control", "set noaskquit", "run",
                      "meas tran q integ i(Vg) from=0.9n to=2.9n", "print q", ".endc", ".end"]) + "\n"
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "d.cir"; f.write_text(deck)
        out = subprocess.run(["ngspice", "-b", str(f)], capture_output=True, text=True).stdout
    q = float(re.search(r"q\s*=\s*([-+0-9.eE]+)", out).group(1))
    return abs(q) / vdd


def main() -> None:
    res = {}
    for area, w in ((20, C.TX_FILL * 20 * C.FEATURE_NM * 1e-3), (40, C.TX_W_UM)):
        res[str(area)] = dict(w_um=w, c_gate_f_vds0=gate_cap(w), c_gate_f_read_bias=gate_cap(w, vd=0.1, vs=0.06), c_per_um_f=gate_cap(1.0))
        print(area, res[str(area)])
    RP.DEVICE.mkdir(parents=True, exist_ok=True)
    (RP.DEVICE / "access_transistor_gate_cap.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
