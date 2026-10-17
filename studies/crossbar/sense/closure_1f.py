"""F3 + F6: the budget re-closed for every front-end operating point (OTA bias vb, read pulse T, integration tail) at every group size g and sigma_lnG, with the energy of that point; the minimum-energy point
that closes is the answer to 'what pulse length does the front-end need' (derived, not chosen), and the closed/not-closed map is the g surface.
Usage: python -m sense.closure_1f"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from sense import budget_1f as B, energy_1f as E

GS = (4, 8, 16)
SIGMAS = (0.03, 0.05, 0.07, 0.10, 0.15)
D_T = (0.0, 5.0, 10.0)


def _one(a):
    row, g, s, dt, droop = a
    sn = float(np.hypot(row["sigma_thermal_ref_uA"], row["comparator_uA"])) * 1e-6
    terms = B.fe_terms(dict(far=sn, near=sn), dict(far=row["cal_sigma_far_uA"] * 1e-6, near=row["cal_sigma_near_uA"] * 1e-6), d_t_k=dt)
    b = B.closure(g, s, terms, gain_factor=1.0 - droop / 0.1, n=1000)
    return dict(vb=row["vb"], T=row["T"], tail=row["tail"], g=g, sigma=s, d_t=dt, droop=droop, margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"], closes=bool(b["closes"]), worst=b["worst_group"],
                far_margin_a=b["groups"]["far"]["margin_left_a"], near_margin_a=b["groups"]["near"]["margin_left_a"], binding=b["groups"][b["worst_group"]]["binding"],
                far_breakdown=b["groups"]["far"]["breakdown"], sigma_noise_a=sn)


def main() -> None:
    rows = json.loads((RP.SENSE / "pareto_raw.json").read_text())["rows"]
    jobs = [(r, g, s, dt, 0.0) for r in rows for g in GS for s in SIGMAS for dt in D_T] + [(r, g, s, 5.0, 8e-3) for r in rows for g in GS for s in SIGMAS]
    with Pool(10) as p:
        res = p.map(_one, jobs, chunksize=8)
    for r in res:
        r["droop_mV"] = r.pop("droop") * 1e3
        r["energy_J"] = E.energy(r["vb"], r["T"], r["tail"], min(r["g"], 8) if r["g"] in (4, 8) else 8, "per_position_digital")["total_J"] if r["g"] in (4, 8) else None
    (RP.SENSE / "closure_map.json").write_text(json.dumps(res, indent=1, default=float))
    print("minimum-energy closing point per (g, sigma_lnG, dT):")
    for g, s, dt in itertools.product(GS, SIGMAS, D_T):
        ok = [r for r in res if r["g"] == g and r["sigma"] == s and r["d_t"] == dt and r["droop_mV"] == 0.0 and r["closes"] and r["energy_J"] is not None]
        if not ok:
            best = max([r for r in res if r["g"] == g and r["sigma"] == s and r["d_t"] == dt and r["droop_mV"] == 0.0], key=lambda r: r["margin_left_a"])
            print(f" g={g} sigma={s} dT={dt}: NO point closes (best margin {best['margin_left_a']*1e6:+.2f} uA at vb {best['vb']} T {best['T']*1e9:g} tail {best['tail']*1e9:g})")
        else:
            m = min(ok, key=lambda r: r["energy_J"])
            print(f" g={g} sigma={s} dT={dt}: vb {m['vb']} T {m['T']*1e9:g} ns tail {m['tail']*1e9:g} ns margin {m['margin_left_a']*1e6:+.2f} uA energy {m['energy_J']*1e6:.2f} uJ")


def g16_variants() -> dict:
    """g = 16 with the C4 readout variants (the only way 1C found it opens), at the most accurate front-end point (vb 0.46, T 2 ns, tail 1 ns), dT 5 K, no droop."""
    rows = json.loads((RP.SENSE / "pareto_raw.json").read_text())["rows"]
    row = [r for r in rows if r["vb"] == 0.46 and abs(r["T"] - 2e-9) < 1e-15 and abs(r["tail"] - 1e-9) < 1e-15][0]
    sn = float(np.hypot(row["sigma_thermal_ref_uA"], row["comparator_uA"])) * 1e-6
    terms = B.fe_terms(dict(far=sn, near=sn), dict(far=row["cal_sigma_far_uA"] * 1e-6, near=row["cal_sigma_near_uA"] * 1e-6), d_t_k=5.0)
    out = {}
    for v in ("end", "centre", "seg2_mid", "seg4_mid", "seg8_mid"):
        for s in (0.02, 0.03, 0.04, 0.048, 0.05, 0.07):
            b = B.closure_variant(v, 16, s, terms, n=2000)
            b0 = B.closure_variant(v, 16, s, None, n=2000)
            out[f"{v}|{s}"] = dict(margin_1f_a=b["margin_left_a"], margin_1c_without_comparator_a=b0["margin_left_a"], worst=b["worst_group"])
    (RP.SENSE / "g16_variants.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
    for k, v in g16_variants().items():
        print("g=16", k, f"margin with 1F {v['margin_1f_a']*1e6:+.2f} uA (1C terms only, no comparator noise {v['margin_1c_without_comparator_a']*1e6:+.2f}), worst {v['worst']}")
