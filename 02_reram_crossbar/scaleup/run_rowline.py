"""C2: the row line of the TRUE macro (32 cells = 64 bitlines on one row line), and the levers that bring the budget back.

1B's 'K = 32 columns' was 32 mesh columns (16 cells); NeuroHDC's macro row (512 x 32-bit) is 32 cells = 64 bitlines, twice as long. This script re-measures the row-line gain and the
data-dependent row-line spread (1B method: fixed own pattern, random weights in every other column) for the worst column of the far and the near group, over
  R_DRV in {1, 2, 5, 10} ohm, r_wl in {0.72, 0.36, 0.18} ohm/pitch (row-line metal 1x/2x/4x better than the bitline), driver at one end or at both ends,
and re-closes the 1B budget (scaleup.budget1c) for each. Usage: python -m scaleup.run_rowline"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import device.constants as C
from scaleup.budget1c import close_1c
from scaleup.droop import macro_stats

VICTIMS = (0, 15, 16, 31)


def job(cfg):
    rd, rwl, both, which, victim, ncells = cfg
    G = 63 if which == "far" else 0
    s = macro_stats(G, 8, victim, n_cells=ncells, n_own=10, n_other=40, r_drv=rd, r_wl=rwl, drive_both_ends=both)
    return dict(r_drv=rd, r_wl=rwl, both_ends=both, group=which, victim=victim, n_cells=ncells, gain=s["gain_row"], row_std_a=s["row_std_a"], row_maxdev_a=s["row_maxdev_a"],
                isup_mean_a=s["isup_mean_a"])


def main() -> None:
    RP.MACRO.mkdir(parents=True, exist_ok=True)
    cfgs = [(rd, rwl, both, w, v, 32) for rd, rwl, both, w, v in product((1.0, 2.0, 5.0, 10.0), (0.72, 0.36, 0.18), (False, True), ("far", "near"), VICTIMS)]
    cfgs += [(10.0, 0.72, False, w, v, 16) for w, v in product(("far", "near"), (0, 7, 8, 15))]        # the 1B geometry (16 cells), as a check on the method
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, cfgs, chunksize=2))
    (RP.MACRO / "row_line_true_macro_raw.json").write_text(json.dumps(res))
    table = []
    for ncells, rd, rwl, both in sorted({(r["n_cells"], r["r_drv"], r["r_wl"], r["both_ends"]) for r in res}):
        rows = [r for r in res if (r["n_cells"], r["r_drv"], r["r_wl"], r["both_ends"]) == (ncells, rd, rwl, both)]
        row = {}
        for w in ("far", "near"):
            rw = [r for r in rows if r["group"] == w]
            gmin = min(rw, key=lambda r: r["gain"])
            row[w] = dict(gain=gmin["gain"], row_std_a=max(r["row_std_a"] for r in rw))        # worst column's gain, worst column's spread (conservative)
        b = close_1c(row)
        table.append(dict(n_cells=ncells, bitlines=2 * ncells, r_drv=rd, r_wl=rwl, both_ends=both, gain_far=row["far"]["gain"], gain_near=row["near"]["gain"],
                          row_std_far_a=row["far"]["row_std_a"], row_std_near_a=row["near"]["row_std_a"], margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"],
                          closes=b["closes"], worst_group=b["worst_group"]))
        t = table[-1]
        print(f"cells {ncells} Rdrv {rd} r_wl {rwl} both {both}: gain far {t['gain_far']:.3f} near {t['gain_near']:.3f} std far {t['row_std_far_a']*1e6:.2f} -> margin {t['margin_left_a']*1e6:.2f} uA ({100*t['margin_frac']:.1f}%) closes {t['closes']}", flush=True)
    (RP.MACRO / "row_line_levers.json").write_text(json.dumps(table, indent=1))


if __name__ == "__main__":
    main()
