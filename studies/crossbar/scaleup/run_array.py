"""C3 / C5 DC part: five macros (160 cells = 81,920 bits) on shared supply rails, and the electrical cost of sensing N columns at once.

Array = 5 macros of 32 cells, each with its own row drivers (both ends) and its own sense periphery / ground pad; the supply rail of a row is shared by the drivers of all five
macros. Modes: first m macros sensing (m = 1..5, contiguous: the supply current scales with m), and the 'bit-plane' mode (one weight bit-plane of 20 neurons = 20 cells
spaced by 8 across the five macros). Un-sensed bitlines float (their cells carry no DC current). Victim: last / middle cell of the last sensing macro.
Usage: python -m scaleup.run_array"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np

import device.constants as C
from scaleup.droop import macro_stats

RHOS = (0.0072, 0.00072)


def job(cfg):
    mode, G, rho, victim, feed = cfg
    en = np.zeros(160, bool)
    if mode.startswith("macros="):
        m = int(mode.split("=")[1]); en[:32 * m] = True
    else:
        en[7::8] = True                                           # bit-plane 7 of every neuron: cells 7, 15, ..., 159
    s = macro_stats(G, 8, victim, n_cells=160, blocks_cells=(32,) * 5, r_drv=10.0, r_wl=0.72, drive_both_ends=True, r_rail=rho, r_gnd=rho, feed_both=feed, enabled_cells=en,
                    n_own=6, n_other=24)
    s["mode"] = mode; s["n_sense_cells"] = int(en.sum())
    return s


def main() -> None:
    RP.FULL_ARRAY.mkdir(parents=True, exist_ok=True)
    cfgs = []
    for G, rho in product((0, 63), RHOS):
        for m in range(1, 6):
            for v in (32 * m - 1, 32 * (m - 1) + 15):
                cfgs.append((f"macros={m}", G, rho, v, True))
        for v in (31, 79, 159):
            cfgs.append(("bitplane", G, rho, v, True))
        cfgs.append(("macros=5", G, rho, 159, False))             # single-ended supply feed, whole array
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, cfgs, chunksize=1))
    (RP.FULL_ARRAY / "five_macro_dc_raw.json").write_text(json.dumps(res))
    print("done", len(res))


if __name__ == "__main__":
    main()
