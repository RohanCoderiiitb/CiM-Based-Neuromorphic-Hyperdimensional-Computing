"""C2(a): supply droop and ground rise of one macro (512 x 32 cells, rows driven from both ends), data dependence, and the budget.

Baseline macro design (from run_rowline): row drivers at both ends, R_DRV = 10 ohm each, row line 0.72 ohm/pitch. Rails: a vertical supply rail feeding every row driver (pad at the
sense end, optionally a second pad at the far end) and a horizontal ground rail returning the 64 sense nodes (pad at the first column), r per pitch swept over
RAIL_R_PER_PITCH_SWEEP. Groups probed across the column, victim = first / middle / last cell, a = 8 (worst current) and a = 4.
Usage: python -m scaleup.run_droop"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import device.constants as C
from scaleup.droop import macro_stats

GROUPS = (0, 8, 16, 24, 32, 40, 48, 56, 63)
VICTIMS = (0, 15, 31)


def job(cfg):
    G, a, v, rho, both_feed = cfg
    s = macro_stats(G, a, v, n_cells=32, n_own=8, n_other=40, r_drv=10.0, r_wl=0.72, drive_both_ends=True, r_rail=rho, r_gnd=rho, feed_both=both_feed)
    return s


def main() -> None:
    RP.MACRO.mkdir(parents=True, exist_ok=True)
    cfgs = [(G, 8, v, rho, fb) for G, v, rho, fb in product(GROUPS, VICTIMS, (None,) + C.RAIL_R_PER_PITCH_SWEEP, (True, False))
            if not (rho is None and not fb)]
    cfgs += [(G, 4, v, rho, True) for G, v, rho in product((0, 32, 63), VICTIMS, (None,) + C.RAIL_R_PER_PITCH_SWEEP)]
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, cfgs, chunksize=2))
    (RP.MACRO / "supply_droop_macro_raw.json").write_text(json.dumps(res))
    print("done", len(res))


if __name__ == "__main__":
    main()
