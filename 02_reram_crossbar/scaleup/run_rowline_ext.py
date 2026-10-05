"""C2/C3: how weak may the row drivers be? Both-end drive, 32 cells, R_DRV in {10, 20, 30, 50, 100} ohm x r_wl in {0.72, 0.36}; same method and budget as run_rowline.
Usage: python -m scaleup.run_rowline_ext"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

from scaleup.budget1c import close_1c
from scaleup.run_rowline import VICTIMS, job


def main() -> None:
    cfgs = [(rd, rwl, True, w, v, 32) for rd, rwl, w, v in product((10.0, 20.0, 30.0, 50.0, 100.0), (0.72, 0.36), ("far", "near"), VICTIMS)]
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, cfgs, chunksize=2))
    table = []
    for rd, rwl in sorted({(r["r_drv"], r["r_wl"]) for r in res}):
        row = {}
        for w in ("far", "near"):
            rw = [r for r in res if (r["r_drv"], r["r_wl"], r["group"]) == (rd, rwl, w)]
            row[w] = dict(gain=min(r["gain"] for r in rw), row_std_a=max(r["row_std_a"] for r in rw))
        b = close_1c(row)
        table.append(dict(r_drv=rd, r_wl=rwl, gain_far=row["far"]["gain"], gain_near=row["near"]["gain"], row_std_far_a=row["far"]["row_std_a"], margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"], closes=b["closes"]))
        t = table[-1]; print(f"both ends R_DRV {rd} r_wl {rwl}: gain far {t['gain_far']:.3f} -> margin {t['margin_left_a']*1e6:+.2f} uA ({100*t['margin_frac']:+.1f}%) closes {t['closes']}", flush=True)
    (RP.MACRO / "row_line_levers_weak_drivers.json").write_text(json.dumps(table, indent=1))


if __name__ == "__main__":
    main()
