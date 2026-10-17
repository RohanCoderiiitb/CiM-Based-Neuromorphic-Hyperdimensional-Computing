"""C4: end-sensed baseline vs centre-tapped vs segmented columns. For every variant, g in {4, 8, 16, 32} and sigma_lnG the 1B budget (S1, drift 'moderate', 20 F^2, R_s 1 ohm) is
evaluated at the far and the near group using mesh-measured terms at their true positions; g* = the largest g that closes (CMRR included). Usage: python -m scaleup.run_variants"""
from __future__ import annotations

import paths as RP

import json
from concurrent.futures import ProcessPoolExecutor
from itertools import product

import device.constants as C
from scaleup.variants import evaluate_variant, group_terms

VARIANTS = ("end", "centre", "seg2_end", "seg2_mid", "seg4_end", "seg4_mid", "seg8_mid")
GS = (4, 8, 16, 32)
SIGMAS = (0.03, 0.05, 0.07, 0.10, 0.15)


def terms_job(a):
    v, g, w, r = a
    return (v, g, w, r), group_terms(v, g, w, r)


def eval_job(a):
    v, g, s, r, terms = a
    return evaluate_variant(v, g, s, r, terms=terms)


def main() -> None:
    RP.READOUT_VARIANTS.mkdir(parents=True, exist_ok=True)
    tj = [(v, g, w, r) for v in VARIANTS for g in GS for w in ("far", "near") for r in ((0.72, 0.5) if v in ("end", "centre") else (0.72,))]
    with ProcessPoolExecutor(9) as ex:
        terms = dict(ex.map(terms_job, tj, chunksize=1))
    (RP.READOUT_VARIANTS / "group_terms.json").write_text(json.dumps({"|".join(map(str, k)): v for k, v in terms.items()}, indent=1))
    ej = []
    for (v, g, w, r) in tj:
        if w != "far":
            continue
        for s in SIGMAS:
            ej.append((v, g, s, r, {"far": terms[(v, g, "far", r)], "near": terms[(v, g, "near", r)]}))
    with ProcessPoolExecutor(9) as ex:
        res = list(ex.map(eval_job, ej, chunksize=2))
    (RP.READOUT_VARIANTS / "g_surface_variants.json").write_text(json.dumps(res, indent=1, default=float))
    gs = {}
    for v, r in sorted({(x["variant"], x["r"]) for x in res}):
        row = []
        for s in SIGMAS:
            ok = [x["g"] for x in res if x["variant"] == v and x["r"] == r and x["sigma"] == s and x["ok"]]
            row.append(max(ok) if ok else 0)
        gs[f"{v}|{r}"] = row
        print(f"{v:9s} r={r}: g* by sigma {dict(zip(SIGMAS, row))}", flush=True)
    (RP.READOUT_VARIANTS / "gstar_summary.json").write_text(json.dumps(dict(sigmas=SIGMAS, gstar=gs), indent=1))


if __name__ == "__main__":
    main()
