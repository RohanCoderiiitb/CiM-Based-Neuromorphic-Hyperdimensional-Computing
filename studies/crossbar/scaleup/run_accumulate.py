"""Run the C1 accumulation test (g = 8 even partition with the full per-group tables; g = 5, 6, 7 ragged). Usage: python -m scaleup.run_accumulate"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import device.constants as C
from scaleup.accumulate import trial_batch
from scaleup.column import build_group_table, n_groups

R = 0.72
DENS = (0.25, 0.51, 0.75, 1.0)          # 0.51 = Phase 0's measured mean active-address density; 1.0 = worst case (every row active)


def _tab(a):
    g, Gi, nf = a
    return build_group_table(g, Gi, R, n_fit=nf, n_held=nf)


def main() -> None:
    out = []
    with ProcessPoolExecutor(9) as ex:
        tabs8 = json.loads(RP.full_column_tables(R).read_text())
        for g, nf in ((8, None), (5, 16), (6, 16), (7, 16)):
            tabs = tabs8 if g == 8 else list(ex.map(_tab, [(g, Gi, nf) for Gi in range(n_groups(g))], chunksize=4))
            n_per = 36 if g == 8 else 12
            jobs = [(tabs, g, R, C.AREA_1C, C.RS_1C, sg, dn, n_per, 1000 * g + int(100 * dn) + int(sg * 1000) + k) for sg in (0.0, 0.10) for dn in DENS for k in range(9)]
            res = list(ex.map(trial_batch, jobs))
            # merge the 9 seeds of each (sigma, density)
            for sg in (0.0, 0.10):
                for dn in DENS:
                    rr = [x for x in res if x["sigma"] == sg and x["density"] == dn]
                    out.append(dict(g=g, n_groups=n_groups(g), ragged=bool(C.ROWS_TOTAL % g), r=R, sigma=sg, density=dn, reads=sum(x["reads"] for x in rr),
                                    sum_errors=sum(x["sum_errors"] for x in rr), wrong_group_decisions=sum(x["wrong_group_decisions"] for x in rr),
                                    group_decisions=sum(x["group_decisions"] for x in rr), min_margin_uA=min(x["min_margin_uA"] for x in rr),
                                    min_margin_frac_of_halfstep=min(x["min_margin_frac_of_halfstep"] for x in rr),
                                    p01_margin_frac_of_halfstep=min(x["p01_margin_frac_of_halfstep"] for x in rr)))
                    o = out[-1]; print(f"g={g} sigma={sg} density={dn}: {o['reads']} reads, sum errors {o['sum_errors']}, wrong group decisions {o['wrong_group_decisions']}/{o['group_decisions']}, "
                                       f"min margin {o['min_margin_frac_of_halfstep']:.2f} of half-step", flush=True)
    (RP.FULL_COLUMN / "accumulation_test.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
