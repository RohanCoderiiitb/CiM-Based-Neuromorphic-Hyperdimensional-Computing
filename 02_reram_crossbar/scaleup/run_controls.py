"""C1 (b) negative controls: does the accumulation test have the power to catch a sequencer fault? (i) table of the wrong group, offset by k groups: tolerance of the table
indexing; (ii) active count a off by one; (iii) activation vector shifted by one row against the weights (a group-boundary off-by-one): pure digital, caught by the sum check.
Usage: python -m scaleup.run_controls"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.accumulate import read_column

R = 0.72


def job(a):
    kind, val, seed = a
    tabs = json.loads(RP.full_column_tables(R).read_text()); p = params_for(C.AREA_1C, C.RS_1C)
    rng = np.random.default_rng(seed); wrong = dec = bad_sum = 0
    for _ in range(18):
        w = rng.random(512) < 0.5; x = rng.random(512) < (1.0 if kind == "table" else 0.51)   # table control at full activity; the a control needs a < g so a + 1 is not clipped
        if kind == "shift":
            m_true_pairs = int(np.sum(w & x)); x2 = np.roll(x, val)       # the sequencer feeds the activations one row late
            mt, mh, wr = read_column(tabs, 8, w, x2, 0.10, rng, R, p)
            bad_sum += int(int(np.sum(w & x)) != mh)
        else:
            mt, mh, wr = read_column(tabs, 8, w, x, 0.10, rng, R, p, table_offset=val if kind == "table" else 0, a_bias=val if kind == "a" else 0)
            bad_sum += int(mt != mh)
        wrong += wr; dec += 64
    return kind, val, bad_sum, wrong, dec


def main() -> None:
    jobs = [("table", k, s) for k in (0, 1, 2, 4, 8, 16, 32, 63) for s in range(4)] + [("a", b, s) for b in (-1, 1) for s in range(4)] + [("shift", 1, s) for s in range(4)]
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, jobs))
    agg = {}
    for kind, val, bs, wr, dec in res:
        d = agg.setdefault(f"{kind}:{val}", dict(kind=kind, value=val, reads=0, sum_errors=0, wrong_decisions=0, decisions=0))
        d["reads"] += 18; d["sum_errors"] += bs; d["wrong_decisions"] += wr; d["decisions"] += dec
    (RP.FULL_COLUMN / "accumulation_negative_controls.json").write_text(json.dumps(list(agg.values()), indent=1))
    for d in agg.values():
        print(d, flush=True)


if __name__ == "__main__":
    main()
