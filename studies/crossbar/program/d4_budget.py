"""1D-ii D4: the budget re-closed with the MEASURED (model) spread, g restated, and the program-effort versus inference-energy trade.

(a) 1F's closure machinery unchanged (sense.budget_1f.closure -> scaleup.budget1c.close_1c -> drift.strategies.evaluate; S1, drift 'moderate', 5-sigma random terms in
    quadrature, 20% headroom; the 18 front-end points of 1F's pareto_raw; recalibration window 5 K; with and without 8 mV droop), the device-spread term now driven by the
    program-verify surface of D2: sigma_LRS and sigma_HRS separately (drift.model.mc_levels_drift(sigma_hrs=...), backwards compatible).
    The spread is a RELATIVE (ln G) quantity measured at the design-adjacent states (0.35 / 1.55 nm); the budget is closed at 1A's design states (541.8 / 218,586 ohm) as
    1B-1F were [MODEL approximation, flagged: the design states sit on the model's clamps and cannot be programmed by the 20 F^2 cell - D1].
(b) Program effort vs inference energy: energy and time of a full-array program at each effort point (D2, the 1D-i parallelism) against 1F's energy per inference at the g the
    point supports (g = 4: 5.29 uJ at T = 1 ns; g = 8: 4.65 uJ at T = 2 ns); and the refresh the model's read disturb (D3) imposes, amortised per inference.
(c) Which of 1F's conditions the device reaches: g = 8 needs sigma_lnG <= 0.07 and a halved calibration residual; g = 16 needs <= 0.045 with seg4/seg8 columns.
Usage: python -m program.d4_budget"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from sense import budget_1f as B

E_INF = {4: 5.29e-6, 8: 4.65e-6}            # J per inference [SIM, 1F section 4 / 9]
T_PULSE = {4: "1ns", 8: "2ns"}              # the verify read is the same read as the inference read at that g


def pareto_rows() -> list:
    return json.loads((RP.SENSE / "pareto_raw.json").read_text())["rows"]


def _closure(a):
    row, g, s_l, s_h, dt, droop, cal_scale = a
    sn = float(np.hypot(row["sigma_thermal_ref_uA"], row["comparator_uA"])) * 1e-6
    terms = B.fe_terms(dict(far=sn, near=sn), dict(far=cal_scale * row["cal_sigma_far_uA"] * 1e-6, near=cal_scale * row["cal_sigma_near_uA"] * 1e-6), d_t_k=dt)
    b = B.closure(g, s_l, terms, gain_factor=1.0 - droop / 0.1, n=1000, sigma_hrs=s_h)
    return dict(vb=row["vb"], T=row["T"], tail=row["tail"], g=g, sigma_lrs=s_l, sigma_hrs=s_h, d_t=dt, droop_mV=droop * 1e3, cal_scale=cal_scale,
                margin_a=b["margin_left_a"], closes=bool(b["closes"]), worst=b["worst_group"])


def _variant(a):
    v, s_l, s_h = a
    rows = pareto_rows()
    row = [r for r in rows if r["vb"] == 0.46 and abs(r["T"] - 2e-9) < 1e-15 and abs(r["tail"] - 1e-9) < 1e-15][0]
    sn = float(np.hypot(row["sigma_thermal_ref_uA"], row["comparator_uA"])) * 1e-6
    terms = B.fe_terms(dict(far=sn, near=sn), dict(far=row["cal_sigma_far_uA"] * 1e-6, near=row["cal_sigma_near_uA"] * 1e-6), d_t_k=5.0)
    b = B.closure_variant(v, 16, s_l, terms, n=2000, sigma_hrs=s_h)
    return dict(variant=v, sigma_lrs=s_l, sigma_hrs=s_h, margin_a=b["margin_left_a"], closes=bool(b["closes"]))


def effort_points() -> list:
    """Program-effort points from the D2 surface (scenario A = the in-envelope array): for each verify accuracy (read T, n_avg), the cheapest LRS configuration whose
    yield is >= 99.9% and the cheapest one-sided HRS configuration, with and without the imposed variability [ASSUM]."""
    d = json.loads((RP.PROGRAM / "d2_surface.json").read_text())
    out = []
    for scen in [s for s in ("A", "B") if s in d]:
        R = d[scen]
        # only runs WITH imposed switching variability: without it a long compliance-limited pulse is a deterministic attractor (every device lands on the same gap),
        # so a zero spread there is a property of a deterministic model, not a placement result (D2)
        for rd, na, var in itertools.product(("1ns", "2ns"), (1, 4, 16, 64), ((0.1, 0.0), (0.3, 0.3))):
            lr = [r for r in R if r["state"] == "lrs" and r["read"] == rd and r["n_avg"] == na and (r["c2c"], r["d2d"]) == var and r["yield_"] >= 0.999]
            hr = [r for r in R if r["state"] == "hrs" and r.get("one_sided") and r["read"] == rd and r["n_avg"] == na and (r["c2c"], r["d2d"]) == (0.3, 0.3)
                  and r["yield_"] >= 0.999 and r["w"] == 0.5]
            if not lr or not hr:
                continue
            # the best spread reachable at this verify accuracy, then the cheapest configuration within 10% of it
            s_best = min(r["sigma_lnG"] for r in lr)
            l = min([r for r in lr if r["sigma_lnG"] <= 1.1 * s_best], key=lambda r: r["energy_mean_j"] * 1e3 + r["time_row_s"])
            h = min(hr, key=lambda r: r["energy_mean_j"] * 1e3 + r["time_row_s"])
            n_dev = 81_920
            out.append(dict(scen=scen, read=rd, n_avg=na, c2c=var[0], d2d=var[1], sigma_lrs=l["sigma_lnG"], bias_lrs=l["bias_lnG"], sigma_hrs=h["sigma_lnG"],
                            lrs_cfg=dict(t_w=l["t_w"], w=l["w"], n_max=l["n_max"], dv=l["dv"]), hrs_cfg=dict(t_w=h["t_w"], w=h["w"], n_max=h["n_max"]),
                            pulses_lrs=l["pulses_mean"], pulses_hrs=h["pulses_mean"], e_dev_lrs_j=l["energy_mean_j"], e_dev_hrs_j=h["energy_mean_j"],
                            t_row_lrs_s=l["time_row_s"], t_row_hrs_s=h["time_row_s"],
                            e_full_j=n_dev * (l["energy_mean_j"] + h["energy_mean_j"]), t_full_s=512 * (l["time_row_s"] + h["time_row_s"]),
                            pulses_full=n_dev * (l["pulses_mean"] + h["pulses_mean"])))
    return out


def read_disturb_refresh() -> dict:
    """D3's read disturb as a level shift: inferences until the far group's top differential level moves by the 1F drift allotment (0.27 uA). Each read closes every active
    gap at the physical rate; mean read stress per row per inference from 1E's pattern (g = 8: 205 ns; g = 4: 116 ns)."""
    rd = json.loads((RP.PROGRAM / "d3_retention.json").read_text())
    rc = json.loads((RP.PROGRAM / "read_conditions.json").read_text())["read_table"]
    gg, ii = np.array(rc["gaps"]), np.array(rc["bl|27.0"])
    didg = lambda g: float((np.interp(g + 1e-3, gg, ii) - np.interp(g - 1e-3, gg, ii)) / 2e-3)   # A per nm (negative)
    out = {}
    for rec in rd["read_disturb"]:
        T = rec["temp_c"]
        rate = {round(x["gap"], 3): x["rate_nm_per_s"] for x in rec["rows"] if "rate_nm_per_s" in x}
        for g, stress in ((8, rd["stress_per_inference"]["g8_s"]), (4, rd["stress_per_inference"]["g4_s"])):
            d_il = didg(0.35) * rate[0.35] * stress            # A per inference, LRS branch (rate < 0: gap closes, current rises)
            d_ih = didg(1.55) * rate[1.55] * stress
            shift = g * 0.89 * abs(d_il - d_ih)                  # top differential level of the far group (gain 0.89, 1C)
            out[f"{T}|{g}"] = dict(d_i_lrs_a=d_il, d_i_hrs_a=d_ih, level_shift_per_inference_a=shift, inferences_to_027uA=0.27e-6 / shift,
                                   dlnG_hrs_per_inference=abs(rate[1.55]) * stress / 0.25, dlnG_lrs_per_inference=abs(rate[0.35]) * stress / 0.25)
    return out


def main() -> None:
    pts = effort_points()
    rows = pareto_rows()
    jobs = []
    pairs = sorted({(round(p["sigma_lrs"], 4), round(p["sigma_hrs"], 4)) for p in pts})
    ref = [(s, s) for s in (0.03, 0.05, 0.07, 0.10)]                       # 1F's own surface, for the check
    for (s_l, s_h), row, g in itertools.product(pairs + ref, rows, (4, 8, 16)):
        jobs.append((row, g, s_l, s_h, 5.0, 0.0, 1.0))
        jobs.append((row, g, s_l, s_h, 5.0, 8e-3, 1.0))
        if g == 8:
            jobs.append((row, g, s_l, s_h, 5.0, 8e-3, 0.5))
    with Pool(30) as p:
        res = p.map(_closure, jobs, chunksize=4)
        var = p.map(_variant, [(v, s_l, s_h) for v in ("end", "seg4_mid", "seg8_mid") for (s_l, s_h) in pairs])
    best = {}
    for r in res:
        k = f"{r['g']}|{r['sigma_lrs']}|{r['sigma_hrs']}|{r['droop_mV']:g}|{r['cal_scale']}"
        if k not in best or r["margin_a"] > best[k]["margin_a"]:
            best[k] = r
    out = dict(effort=pts, closure_best=best, g16_variants=var, read_disturb=read_disturb_refresh(), e_inf_1f=E_INF,
               note="budget closed at 1A's design states with the spread measured at the design-adjacent states [MODEL]; the 20 F^2 array cannot program 1A's states (D1)")
    (RP.PROGRAM / "d4_budget.json").write_text(json.dumps(out, indent=1, default=float))
    def k(g, sl, sh, droop=8, cal=1.0):
        return f"{g}|{round(sl, 4)}|{round(sh, 4)}|{droop}|{cal}"
    for p in pts:
        m = {g: best[k(g, p["sigma_lrs"], p["sigma_hrs"])]["margin_a"] for g in (4, 8, 16)}
        g_ok = [g for g in (4, 8, 16) if m[g] > 0.15e-6]
        print(f"{p['scen']} read {p['read']} x{p['n_avg']:2d} var {p['c2c']}/{p['d2d']}: sigma L {p['sigma_lrs']:.3f} H {p['sigma_hrs']:.3f} -> "
              + " ".join(f"g{g}:{m[g] * 1e6:+.2f}" for g in (4, 8, 16)) + f"  g* {max(g_ok) if g_ok else '-'}; program {p['e_full_j']:.3g} J, {p['t_full_s']:.3g} s")
    for s in (0.03, 0.05, 0.07, 0.10):
        print("1F check sigma", s, " ".join(f"g{g}:{best[k(g, s, s)]['margin_a'] * 1e6:+.2f}" for g in (4, 8, 16)))
    print(json.dumps(out["read_disturb"], indent=0)[:1500])


if __name__ == "__main__":
    main()
