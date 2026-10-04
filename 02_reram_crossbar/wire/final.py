"""1B Part E: the final surface with wire IR and drift added. Writes results/final_surface/final_g_surface_<strategy>.csv.

Per (g, cell area, R_s, sigma_lnG, wire r, drift scenario), BOTH extreme contiguous groups (near and far; worst-case closure over the two):
  * the far group sits behind r*(512-g+1) ohm of bitline: this is the same as a larger sense resistor for that group (validated against the mesh), so the budget
    is evaluated at R_s_eff = R_s + r*pos0 (Delta_far, spread and CMRR all compressed accordingly)  -> BETWEEN-group term: level shift removed by a per-group ladder,
    compression stays inside Delta
  * the uncorrectable WITHIN-group bitline error from the mesh enters as a deterministic term (results/wire_resistance/wire_terms_per_point.json)
  * the row-line gain (K = 32, per-column ladder scale) multiplies Delta/spread/leakage; the row-driver spread enters as a random term at 5 sigma
  * drift via the chosen strategy (drift/strategies.py)
Usage: python -m wire.final --strategy S3 [--n-ref 128 --ref-mode abs] [--workers N]
"""
from __future__ import annotations

import paths as RP

import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import device.constants as C
from drift.strategies import evaluate

ROOT = Path(__file__).resolve().parents[1]
TERMS = RP.WIRE_TERMS_JSON
G_F = (1, 2, 4, 8, 16, 32, 64)
_T = None


def terms_lookup() -> dict:
    global _T
    if _T is None:
        _T = {(t["g"], t["area"], t["r_s"], t["r"]): t for t in json.loads(TERMS.read_text())}
    return _T


def far_series(g: int, r: float, sense: str = "end") -> float:
    """Bitline series resistance of the farthest group: sense node at one end of the column (distance 512 - g + 1 pitches) or in the middle (256 - g + 1)."""
    return r * ((C.ROWS_TOTAL if sense == "end" else C.ROWS_TOTAL // 2) - g + 1.0)


def final_point(g, area, r_s, sigma, r, scenario: str, strategy: str, strat_kw: dict, n: int = 500, n_ages: int = 3, with_wire: bool = True, sense: str = "end",
                comp_sigma: float = C.COMP_SIGMA_I_A) -> dict:
    nu, kappa = C.DRIFT_SCENARIOS[scenario]
    extras, r_eff = {}, r_s
    if with_wire:
        tl = terms_lookup()
        t = tl.get((g, area, r_s, r)) or tl[(g, area, 5.0, r)]
    results = []
    for which in (("far", "near") if with_wire else ("none",)):
        if with_wire:
            r_eff = r_s + (far_series(g, r, sense) if which == "far" else r * 1.0)
            extras = dict(wire_within_a=t[f"within_{which}_a"], row5_a=C.N_SIGMA * t[f"row_std_{which}_a"], gain=(t[f"row_gain_{which}"] or 1.0))
        # Exact deterministic pre-check: if the within-group wire term ALONE exceeds the usable limit (0.5 (1 - headroom) x the mesh-measured group step), the budget cannot
        # close whatever the other terms are, so the Monte Carlo is skipped. The record is flagged 'precheck' and carries only the quantities that were computed.
        d_mesh = t[f"delta_{which}_a"] if with_wire else None
        if with_wire and which == "far" and sense == "middle":
            d_mesh = None            # the mesh far-group step was measured with the sense node at the end; do not pre-check against it
        if with_wire and d_mesh and extras["wire_within_a"] >= 0.5 * (1 - C.HEADROOM) * d_mesh * extras["gain"]:
            lim = 0.5 * (1 - C.HEADROOM) * d_mesh * extras["gain"]
            w = dict(margin_left_frac=(lim - extras["wire_within_a"]) / lim, delta_a=d_mesh * extras["gain"], limit_a=lim, total_a=extras["wire_within_a"], cmrr_db=float("nan"),
                     binding="wire IR (within group)", breakdown={"wire IR (within group)": extras["wire_within_a"]})
            ev = dict(ok=False, cmrr_ok=True, ages=[w])
        else:
            ev = evaluate(g, area, r_eff, sigma, nu, kappa, strat_kw.get("life", 10.0), strategy, n_ref=strat_kw.get("n_ref", 0), ref_mode=strat_kw.get("ref_mode", "abs"),
                          refresh_days=strat_kw.get("refresh_days"), extras=extras, n=n, n_ages=n_ages, comp_sigma=comp_sigma)
            w = min(ev["ages"], key=lambda a: a["margin_left_frac"])
        results.append((which, ev, w, r_eff))
    which, ev, w, r_eff = min(results, key=lambda x: x[2]["margin_left_frac"])        # the group with the least margin
    return dict(g=g, area=area, r_s=r_s, sigma=sigma, r=r, scenario=scenario, strategy=strategy, with_wire=with_wire, worst_group=which, r_eff=r_eff,
                ok=all(e["ok"] and e["cmrr_ok"] for _, e, _, _ in results), budget_ok=all(e["ok"] for _, e, _, _ in results), cmrr_ok=all(e["cmrr_ok"] for _, e, _, _ in results),
                margin_frac=w["margin_left_frac"], delta_a=w["delta_a"], limit_a=w["limit_a"], total_a=w["total_a"], cmrr_db=float(np.nanmax([x[2]["cmrr_db"] for x in results])) if not all(x[2]["cmrr_db"] != x[2]["cmrr_db"] for x in results) else float("nan"),
                binding=w["binding"], **{f"t_{k}": v for k, v in w["breakdown"].items()})


def task(args):
    return final_point(*args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="S3"); ap.add_argument("--n-ref", type=int, default=128); ap.add_argument("--ref-mode", default="abs")
    ap.add_argument("--refresh-days", type=float, default=90.0); ap.add_argument("--life", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=8); ap.add_argument("--out", type=Path, default=None, help="default: results/final_surface/final_g_surface_<strategy>.csv")
    ap.add_argument("--no-wire", action="store_true")
    args = ap.parse_args()
    if args.out is None:
        args.out = RP.final_points_csv(args.strategy)
    kw = dict(n_ref=args.n_ref, ref_mode=args.ref_mode, refresh_days=args.refresh_days, life=args.life)
    jobs = [(g, a, rs, sg, r, sc, args.strategy, kw, 500, 3, not args.no_wire) for g in G_F for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP for sg in C.SIGMA_FINAL_SWEEP
            for r in C.BL_R_PER_PITCH_SWEEP for sc in C.DRIFT_SCENARIOS]
    jobs.sort(key=lambda j: -j[0])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(args.workers) as ex:
        res = list(ex.map(task, jobs, chunksize=4))
    fields = list(dict.fromkeys(k for r in res for k in r))        # union of columns: pre-check rows carry fewer term columns than Monte-Carlo rows
    with args.out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fields, restval="")
        w.writeheader(); w.writerows(res)
    print("wrote", args.out, len(jobs))


if __name__ == "__main__":
    main()
