"""1D-ii: validate the map composition the program-verify loop uses (program/verify.Maps: linear interpolation in gap and in log width) against the compiled model run
directly, pulse after pulse, in ngspice.

30 devices with random OFF-GRID initial gaps receive the same random train of 10 pulses (random polarity, grid amplitude, OFF-GRID width - the width interpolation is what
the imposed variability uses); each ngspice pulse starts from the previous pulse's final gap. Reported: the largest |gap_maps - gap_ngspice| after every pulse, in nm and in
sigma_lnG units (/ g0).
Usage: python -m program.validate_loop [A|B]"""
from __future__ import annotations

import json
import sys

import numpy as np

import paths as RP
from program import tables as T, verify as V
from program.cell import run_pulse


def main(scen: str = "A") -> None:
    rng = np.random.default_rng(5)
    t = T.main_tables() if scen == "A" else T.design_tables()
    cell = T.CELL if scen == "A" else T.CELL_DESIGN
    M = V.Maps(t["set"], t["reset"])
    g0 = 0.3 + 1.3 * rng.random(30)
    g_map, g_ng = g0.copy(), g0.copy()
    lw = np.log(t["set"]["widths"])
    rec = []
    for k in range(10):
        d = "set" if rng.random() < 0.5 else "reset"
        vg = t[d]["volts"]
        iv = int(rng.integers(len(vg) // 4, len(vg) * 3 // 4))
        width = float(np.exp(rng.uniform(lw[0], lw[-1])))
        g_map, _ = M.step(d, np.full(30, iv), np.full(30, width), g_map)
        r = run_pulse(cell, d, float(vg[iv]), width, g_ng)
        g_ng = r["gap_out"]
        err = float(np.max(np.abs(g_map - g_ng)))
        rec.append(dict(pulse=k, direction=d, v=float(vg[iv]), width=width, max_err_nm=err, max_err_lnG=err / 0.25, mean_move_nm=float(np.mean(np.abs(g_ng - (g_ng if k == 0 else g_ng))))))
        print(f"pulse {k}: {d} {vg[iv]:.2f} V {width:.3g} s -> max |maps - ngspice| {err * 1e3:.3f} pm ({err / 0.25:.2e} in lnG)", flush=True)
    out = dict(scen=scen, pulses=rec, worst_nm=max(r["max_err_nm"] for r in rec), final_gaps_ngspice=g_ng.tolist(), final_gaps_maps=g_map.tolist(), start=g0.tolist())
    RP.PROGRAM.mkdir(parents=True, exist_ok=True)
    (RP.PROGRAM / f"validate_loop_{scen}.json").write_text(json.dumps(out, indent=1))
    print("worst", out["worst_nm"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "A")
