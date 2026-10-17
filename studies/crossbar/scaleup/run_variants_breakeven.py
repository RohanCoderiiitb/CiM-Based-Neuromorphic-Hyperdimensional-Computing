"""C4: the sigma_lnG at which g = 16 stops closing, per variant (finer sigma grid than run_variants, g = 16 and g = 8 margins; terms from results/readout_variants/group_terms.json).
Margin is interpolated to zero for the break-even sigma. Usage: python -m scaleup.run_variants_breakeven"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from scaleup.variants import evaluate_variant

SIG = (0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10)
CASES = [("end", 0.72), ("end", 0.5), ("centre", 0.72), ("centre", 0.5), ("seg2_mid", 0.72), ("seg4_mid", 0.72), ("seg8_mid", 0.72), ("seg4_end", 0.72)]


def job(a):
    v, r, g, s = a
    t = json.loads((RP.READOUT_VARIANTS / "group_terms.json").read_text())
    terms = {w: t[f"{v}|{g}|{w}|{r}"] for w in ("far", "near")}
    x = evaluate_variant(v, g, s, r, terms=terms, n=600)
    return dict(variant=v, r=r, g=g, sigma=s, margin_frac=float(x["margin_frac"]), margin_left_a=float(x["margin_left_a"]), worst=x["worst"], binding=x["binding"], ok=bool(x["ok"]))


def main() -> None:
    jobs = [(v, r, g, s) for v, r in CASES for g in (8, 16) for s in SIG]
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(job, jobs, chunksize=2))
    (RP.READOUT_VARIANTS / "breakeven_margins.json").write_text(json.dumps(res, indent=1))
    summ = {}
    for v, r in CASES:
        for g in (16,):
            m = [(x["sigma"], x["margin_frac"]) for x in res if x["variant"] == v and x["r"] == r and x["g"] == g]
            m.sort()
            sig_be = None
            for (s0, m0), (s1, m1) in zip(m[:-1], m[1:]):
                if m0 >= 0 > m1:
                    sig_be = s0 + (s1 - s0) * m0 / (m0 - m1)
            if m[0][1] < 0:
                sig_be = 0.0                       # never closes even at the smallest sigma on the grid
            summ[f"{v}|{r}"] = dict(sigma_break_even_g16=sig_be, margins=m)
            print(f"{v:9s} r={r}: g=16 closes up to sigma ~ {sig_be if sig_be is None else round(sig_be, 3)}; margins " + " ".join(f"{s}:{100*mm:+.0f}%" for s, mm in m), flush=True)
    (RP.READOUT_VARIANTS / "breakeven_summary.json").write_text(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
