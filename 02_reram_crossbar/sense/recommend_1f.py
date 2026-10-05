"""F6/F7: the candidate honest design points evaluated end to end - budget (with measured front-end terms, the droop of the chosen decoupling, MC error stated), energy per inference, cycles, area.

A candidate = (g, columns sensed per pass, OTA bias vb, pulse T, tail, decoupling C_dec, dT between calibrations). Droop: the minimum rail voltage during the pulse from sense.pdn at the candidate's
peak current (160 columns x a_max rows: scale = (columns/160) x (a_max/8), a_max = g) interpolated in C_dec; it scales the read bias, i.e. the gain of the budget's signal terms by (1 - droop/V_READ).
Margins are printed with the Monte-Carlo scatter of the budget's spread term (re-run with 3 seeds-worth of draws): margins below ~0.15 uA are not distinguishable from zero.
Usage: python -m sense.recommend_1f"""
from __future__ import annotations

import json

import numpy as np

import device.constants as C
import paths as RP
from sense import area_1f, budget_1f as B, energy_1f as E
from sense.closure_1f import GS

CANDS = [
    dict(name="1C baseline architecture + 1F front-end (g = 8, 160 columns at once)", g=8, cols=160, vb=0.50, T=2e-9, tail=0.3e-9, c_dec=20e-9, sigmas=(0.05, 0.07, 0.10)),
    dict(name="g = 8, 20 columns per pass", g=8, cols=20, vb=0.50, T=2e-9, tail=0.3e-9, c_dec=1e-9, sigmas=(0.05, 0.07, 0.10)),
    dict(name="g = 4, 40 columns per pass", g=4, cols=40, vb=0.50, T=1e-9, tail=0.3e-9, c_dec=1e-9, sigmas=(0.05, 0.07, 0.10, 0.15)),
    dict(name="g = 4, 40 columns per pass, larger decoupling", g=4, cols=40, vb=0.50, T=1e-9, tail=0.3e-9, c_dec=2e-9, sigmas=(0.05, 0.07, 0.10, 0.15)),
]


def droop_mV(T: float, scale: float, c_dec: float, r_d: float) -> float:
    rows = json.loads((RP.PDN / "pdn_sweep.json").read_text())
    pts = sorted([(x["c_dec"], x["droop_max_mV"]) for x in rows if x["t_pulse"] == T and abs(x.get("i_scale", 1.0) - scale) < 1e-9 and x["r_d"] == r_d and x["stagger"] == 0.0 and x["c_dec"] > 0])
    if not pts:
        return float("nan")
    c = np.array([p[0] for p in pts]); d = np.array([p[1] for p in pts])
    return float(np.interp(np.log(c_dec), np.log(c), d))


def recovery_ns(T: float, scale: float, c_dec: float, r_d: float) -> float:
    rows = json.loads((RP.PDN / "pdn_sweep.json").read_text())
    pts = sorted([(x["c_dec"], x["recovery_ns"]) for x in rows if x["t_pulse"] == T and abs(x.get("i_scale", 1.0) - scale) < 1e-9 and x["r_d"] == r_d and x["stagger"] == 0.0 and x["c_dec"] > 0])
    c = np.array([p[0] for p in pts]); d = np.array([p[1] for p in pts])
    return float(np.interp(np.log(c_dec), np.log(c), d))


def main() -> None:
    par = json.loads((RP.SENSE / "pareto_raw.json").read_text())["rows"]
    rc = json.loads((RP.SENSE / "read_counts.json").read_text())
    out = []
    for c in CANDS:
        row = [r for r in par if abs(r["vb"] - c["vb"]) < 1e-9 and abs(r["T"] - c["T"]) < 1e-15 and abs(r["tail"] - c["tail"]) < 1e-15][0]
        scale = (c["cols"] / 160.0) * (c["g"] / 8.0)
        r_d = 0.02 if scale == 1.0 else 0.05
        dr = droop_mV(c["T"], scale, c["c_dec"], r_d) if not (scale == 1.0 and c["T"] == 2e-9 and c["c_dec"] == 20e-9) else droop_mV(c["T"], 1.0, 20e-9, 0.02)
        rec = recovery_ns(c["T"], scale, c["c_dec"], r_d)
        passes = int(np.ceil(160 / c["cols"]))
        reads = rc[str(c["g"])]["reads_nonzero"]
        cyc = 409028 + passes * reads
        en = E.energy(c["vb"], c["T"], c["tail"], c["g"], "per_position_digital")
        sn = float(np.hypot(row["sigma_thermal_ref_uA"], row["comparator_uA"])) * 1e-6
        res = dict(c, name=c["name"], droop_mV=dr, recovery_ns=rec, passes=passes, reads_per_inference=passes * reads, cycles_skip_a0=cyc, energy=en, margins={})
        for s in c["sigmas"]:
            terms = B.fe_terms(dict(far=sn, near=sn), dict(far=row["cal_sigma_far_uA"] * 1e-6, near=row["cal_sigma_near_uA"] * 1e-6), d_t_k=5.0)
            ms = [B.closure(c["g"], s, terms, gain_factor=1.0 - dr * 1e-3 / C.V_READ, n=n)["margin_left_a"] for n in (1000, 2000, 4000)]
            b = B.closure(c["g"], s, terms, gain_factor=1.0 - dr * 1e-3 / C.V_READ, n=2000)
            res["margins"][str(s)] = dict(margin_uA=b["margin_left_a"] * 1e6, scatter_uA=(max(ms) - min(ms)) * 1e6, closes=bool(b["closes"]), worst=b["worst_group"], far_breakdown_uA={k: v * 1e6 for k, v in b["groups"]["far"]["breakdown"].items()},
                                         limit_uA=b["groups"]["far"]["limit_a"] * 1e6, total_uA=b["groups"]["far"]["total_a"] * 1e6)
        ar = area_1f.area_table(c["c_dec"], 1)
        res["area_mm2_mid"] = ar["total_mm2"]; res["decap_area_mm2_mid"] = c["c_dec"] * 1e15 / area_1f.DECAP_DENSITY[1] * 1e-6
        out.append(res)
        print(f"{c['name']}: droop {dr:.1f} mV (recovery {rec:.1f} ns), {passes} passes, {cyc:,.0f} cycles, energy {en['total_J']*1e6:.2f} uJ ({en['ratio_to_neurohdc']:.2f}x), area {ar['total_mm2']:.3f} mm2 (decap {res['decap_area_mm2_mid']:.3f})")
        for s, m in res["margins"].items():
            print(f"     sigma_lnG {s}: margin {m['margin_uA']:+.2f} +/- {m['scatter_uA']/2:.2f} uA, closes {m['closes']}, worst {m['worst']}")
    (RP.SENSE / "recommended_designs.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
