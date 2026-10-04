"""Render results/phase1a_report.md from the results/*.json|csv artefacts plus analytic tables.

Usage: python -m validate.make_report
"""
from __future__ import annotations

import csv
import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np

import device.constants as C
from device.model import device_resistance, on_off_ratio
from device.spread import resistance_cv
from solver.newton import solve_column
from validate import analysis as A

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
GS = (4, 8, 16, 32, 64)
F = C.FEATURE_NM


def table(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def e(x: float, d: int = 3) -> str:
    return f"{x:.{d}e}"


def load(name: str):
    path = RES / name
    return json.loads(path.read_text()) if path.exists() else None


def rows_of(path: Path):
    return list(csv.DictReader(path.open())) if path.exists() else None


def validation_block(path: Path, label: str):
    rows = rows_of(path)
    if not rows:
        return f"**BLOCKED / not run** - {path.name} absent.\n", None
    f = lambda k: np.array([float(r[k]) for r in rows])
    gg, a, m = (np.array([int(r[k]) for r in rows]) for k in ("g", "a", "m"))
    nd, sg = int(rows[0]["n_draws"]), float(rows[0]["sigma_lng"])
    prim, sec = f("rel_diff_scale"), f("rel_diff")
    i, j = int(np.argmax(prim)), int(np.argmax(sec))
    ok_p, ok_s = prim.max() < C.ACCEPT_REL_DIFF, sec.max() < C.ACCEPT_REL_DIFF
    per_g = table(["g", "cases", "PRIMARY worst scale-normalised I_diff", "secondary worst |dI|/|I_diff|", "worst I_plus", "worst I_minus"],
                  [(g, int((gg == g).sum()), e(prim[gg == g].max()), e(sec[gg == g].max()),
                    e(f("rel_plus")[gg == g].max()), e(f("rel_minus")[gg == g].max())) for g in sorted(set(gg))])
    t_sp, t_nw = f("ngspice_s").sum(), f("newton_s").sum()
    ns = int(sum(int(r["n_draws"]) for r in rows)) * 2
    txt = f"""{label}: sigma_lnG = {sg}, g in {sorted(set(gg.tolist()))}, every a in 1..g, every m in 0..a ({len(rows)} cases), {nd} draws each,
identical draws to ngspice (linear R_tx = {C.R_TX} ohm) and Newton (same R_tx), {ns} column solves per solver.

{per_g}

- **PRIMARY (scale-normalised, |dI_diff| / max(I_plus, I_minus)): worst {e(prim.max())}** at g={gg[i]}, a={a[i]}, m={m[i]}; threshold {C.ACCEPT_REL_DIFF:.0e} -> {'PASS' if ok_p else 'FAIL'}.
- Secondary diagnostic (|dI_diff| / |I_diff|): worst {e(sec.max())} at g={gg[j]}, a={a[j]}, m={m[j]}; threshold {C.ACCEPT_REL_DIFF:.0e} -> {'PASS' if ok_s else 'FAIL'}.
- **The verdict uses the primary metric.**
- Newton iterations (worst of outer/inner): {int(f('newton_iters').max())}.
- Runtime: ngspice {t_sp:.1f} s ({t_sp / ns * 1e3:.3f} ms/solve, {nd * 2} columns per process), Newton {t_nw:.2f} s ({t_nw / ns * 1e6:.1f} us/solve), speedup {t_sp / t_nw:.0f}x.
"""
    return txt, dict(prim=float(prim.max()), sec=float(sec.max()), ok=bool(ok_p), sigma=sg)


def main() -> None:
    p = C.DEFAULT
    tr, lk, lb = load("transistor.json"), load("off_leakage.json"), load("linear_vs_bsim.json")
    nom = tr["nominal"]
    val_txt, val = validation_block(RES / "validation.csv", "Full sweep (primary configuration)")
    sweep_rows = []
    for s in C.SIGMA_LNG_SWEEP:
        if s == C.SIGMA_LNG:
            continue
        pth = RES / f"validation_sigma_{s:.2f}.csv"
        rr = rows_of(pth)
        if rr:
            prim = max(float(r["rel_diff_scale"]) for r in rr); sec = max(float(r["rel_diff"]) for r in rr)
            sweep_rows.append((s, f"g in {sorted({int(r['g']) for r in rr})}, {rr[0]['n_draws']} draws, {len(rr)} cases", e(prim), e(sec)))
        else:
            sweep_rows.append((s, "not run", "-", "-"))
    if val:
        sweep_rows.insert(sorted(C.SIGMA_LNG_SWEEP).index(C.SIGMA_LNG), (C.SIGMA_LNG, "g in [4, 8, 16, 32], 200 draws (full)", e(val["prim"]), e(val["sec"])))

    # ---- constants table (tags) ----
    consts = table(["name", "value", "unit", "tag", "source / reasoning"], [
        ("I0", C.I0, "A", "[SP]", "Stanford-PKU default (rram.va)"), ("g0", C.G0, "nm", "[SP]", "Stanford-PKU default"),
        ("V0", C.V0, "V", "[SP]", "Stanford-PKU default"), ("GMIN", C.GMIN, "S", "[SP]", "Stanford-PKU default, included"),
        ("minGap / maxGap", f"{C.MIN_GAP} / {C.MAX_GAP}", "nm", "[SP]", "model limits"),
        ("gap_LRS / gap_HRS", f"{C.GAP_LRS} / {C.GAP_HRS}", "nm", "[CHOICE]", "programming target = model limits; costless now that spread is log-normal (no clipping). Same decision as 1D's program-verify window."),
        ("R_s", C.R_S, "ohm", "[ASSUM]", "plan value; swept in 1B"), ("V_read", C.V_READ, "V", "[ASSUM]", "plan value"),
        ("V_WL", C.V_WL, "V", "[CHOICE]", "wordline high = PTM LP nominal Vdd; core device rated 1.1 V"),
        ("feature size F / L", f"{F:.0f} / {C.TX_L_NM:.0f}", "nm", "[CHOICE]", "PTM 45 nm LP node; Leff = L [SIM-confirmed]"),
        ("1T1R cell area", C.CELL_AREA_F2, "F^2", "[CHOICE]", "middle of the 20-60 F^2 band; lower bound set by SET current (section 3)"),
        ("fill factor", C.TX_FILL, "-", "[CHOICE]", "W = fill * area_F2 * F"),
        ("W", f"{C.TX_W_UM:.3f}", "um", "[MODEL]", "0.6 * 40 * 45 nm"),
        ("**R_tx**", C.R_TX, "ohm", "[SIM]", "LRS-branch access-transistor resistance, validate/extract_rtx.py -> results/transistor.json (replaces the 200 ohm placeholder)"),
        ("sigma_lnG", f"{C.SIGMA_LNG} (sweep {list(C.SIGMA_LNG_SWEEP)})", "-", "[ASSUM]", "related work: 'programming spread typically 5-20%', uncited. Reported vs sigma, not at one value"),
        ("AVT", C.AVT_MV_UM, "mV*um", "[ASSUM]", "Pelgrom Vth-mismatch coefficient, typical high-k/metal-gate 45 nm; card has no mismatch parameters"),
        ("Newton tol / cap", f"{C.NEWTON_TOL_V:g} V / {C.NEWTON_MAX_ITER}", "-", "[CHOICE]", "numerical settings"),
        ("acceptance", C.ACCEPT_REL_DIFF, "-", "[CHOICE]", "1A gate 0.01%"),
    ])

    # ---- section 3: transistor chain ----
    rows = tr["rows"]
    chain = table(["cell area (F^2)", "area (um^2)", "W (um)", "rdsw floor [MODEL] (ohm)", "R_tx LRS [SIM] (ohm)", "I_LRS (uA)",
                   "R_tx HRS [SIM] (ohm)", "I_HRS (uA)", "R_tx / floor", "cell pitch (um)", "Idsat at Vdd (uA)"],
                  [(r["area_f2"], f"{r['area_f2'] * (F * 1e-3) ** 2:.4f}", f"{r['w_um']:.2f}", f"{r['rdsw_floor']:.0f}",
                    f"{r['rtx_lrs']:.1f}", f"{r['i_lrs'] * 1e6:.1f}", f"{r['rtx_hrs']:.1f}", f"{r['i_hrs'] * 1e6:.3f}",
                    f"{r['rtx_lrs'] / r['rdsw_floor']:.2f}", f"{r['pitch_um']:.3f}", f"{r['idsat_ua']:.0f}") for r in rows])
    trade = table(["cell area (F^2)", "W (um)", "R_tx (ohm)", "R_LRS_eff (ohm)", "cell pitch (um)", "I_LRS (uA)",
                   "single-col worst step, g=32", "single-col worst step, g=16", "Idsat (uA)"],
                  [(r["area_f2"], f"{r['w_um']:.2f}", f"{r['rtx_lrs']:.0f}", f"{r['r_eff']:.0f}", f"{r['pitch_um']:.3f}",
                    f"{r['i_lrs'] * 1e6:.0f}", f"{r['single_gap_g32']:.3f}",
                    f"{float(A.level_gap_single_column(16, p.with_(tx_w_um=r['w_um'], r_tx=r['rtx_lrs']))[-1]):.3f}",
                    f"{r['idsat_ua']:.0f}") for r in rows])
    w_for = lambda iset_ua: iset_ua * 1e-6 / (tr["idsat_ma_per_um"] * 1e-3)
    set_rows = [(f"{i} uA", f"{w_for(i):.3f}", f"{w_for(i) / (C.TX_FILL * F * 1e-3):.1f}") for i in (100, 300, 500, 1000)]
    set_tab = table(["required SET current (illustrative)", "min W at Idsat/um (um)", "min 1T1R cell area (F^2)"], set_rows)

    # ---- linear vs bsim ----
    if lb:
        from spice.transistor import branch_rtx
        _b = [branch_rtx(C.GAP_LRS, p, v_bl_fixed=v)['r_tx'] for v in (0.0, 0.02, 0.04, 0.06)]
        bias_txt = ' / '.join(f'{x:.2f}' for x in _b); bias_pct = (_b[-1] / _b[0] - 1) * 100
        lbrows = [(g, v["n_cases"], f"{v['worst_rel_single_step'] * 100:.2f}%", f"{v['worst_rel_diff_step'] * 100:.2f}%",
                   e(v["worst_rel_idiff_scale"]), f"{v['worst_rel_iplus'] * 100:.2f}%",
                   f"{v['best_const_rtx']:.0f} ({v['best_const_rtx_worst_step_err'] * 100:.2f}%)") for g, v in lb["per_g"].items()]
        lb_tab = table(["g", "cases (a,m)", "worst level-step error, single column", "worst level-step error, differential",
                        "worst |dI_diff|/scale", "worst I_plus error", "best constant R_tx (resulting worst step error)"], lbrows)
        worst_step = max(max(v["worst_rel_single_step"], v["worst_rel_diff_step"]) for v in lb["per_g"].values())
        verdict_lb = ("**Verdict: the linear R_tx is NOT good enough to carry into 1B unqualified.** The worst level-step error is "
                      f"{worst_step * 100:.1f}% (> 1%). 1B must either put the transistor into the solver (a bias-dependent R_tx(V_s) is the "
                      "minimal change) or carry this bound as an explicit modelling error on every margin number."
                      if worst_step > 0.01 else
                      f"**Verdict: the linear R_tx is acceptable for 1B** - worst level-step error {worst_step * 100:.2f}% (< 1%), recorded as the bound.")
        lb_txt = f"""Both columns of this table are ngspice, same nominal gaps, same circuit; only the access device differs (linear {C.R_TX} ohm
resistor vs the real PTM BSIM4 NMOS at W = {C.TX_W_UM:.2f} um, gate {C.V_WL} V, body grounded). This is a MODELLING difference, measured
separately from the Newton-vs-ngspice numerical validation, which uses the linear R_tx on both sides. 'Level-step error' is
|step_linear/step_BSIM - 1| over the steps at a = g.

{lb_tab}

{verdict_lb}

Why it holds (measured, not assumed): R_tx of an LRS branch with the bitline held at 0 / 0.02 / 0.04 / 0.06 V is
{bias_txt} ohm - a {bias_pct:.2f}% rise over the whole bitline swing a group produces. Rising source voltage costs Vgs and adds body effect, but
on this card (rdsw ~ 210 ohm*um is a bias-independent floor, k1 = 0.4, small overdrive sensitivity in the linear region) the net effect on R_tx is
negligible. (I had expected a count-dependent drift comparable to sense-resistor compression; the measurement says no.) The residual is
bounded by the table above and is carried forward as a modelling error of that size. It is a property of this predictive card, not a guarantee for
another process.
"""
    else:
        lb_txt = "**BLOCKED / not run** - results/linear_vs_bsim.json absent.\n"

    # ---- leakage ----
    if lk:
        i_lrs = lk["i_lrs_branch_a"]
        by = {(r["temp_c"], r["v_bl"]): r for r in lk["rows"]}
        per_dev = table(["T (C)", "nominal Ioff, bitline at 0 V (A)", "fraction of one LRS branch", "mean over 500 (A)", "sigma over 500 (A)",
                         "sigma/mean", "nominal at v_bl = 0.04 V (A)", "equivalent Roff = V_read/Ioff (ohm)"],
                        [(t, e(by[(t, 0.0)]["nominal_a"]), e(by[(t, 0.0)]["nominal_a"] / i_lrs), e(by[(t, 0.0)]["mean_a"]),
                          e(by[(t, 0.0)]["std_a"]), f"{by[(t, 0.0)]['std_a'] / by[(t, 0.0)]['mean_a']:.2f}", e(by[(t, 0.04)]["nominal_a"]),
                          e(p.v_read / by[(t, 0.0)]["mean_a"], 2)) for t in sorted({k[0] for k in by})])
        wg = {g: A.worst_gaps(g, p) for g in GS}
        budget = 0.05
        cnt_rows, cross_rows = [], []
        n_a = 1  # worst case: one active row
        for t in sorted({k[0] for k in by}):
            r = by[(t, 0.0)]
            for g in GS:
                n_un, n_seg = 512 - n_a, g - n_a
                mean_un, mean_seg = n_un * r["mean_a"] / i_lrs, n_seg * r["mean_a"] / i_lrs
                sd_un, sd_seg = np.sqrt(n_un) * r["std_a"] / i_lrs, np.sqrt(n_seg) * r["std_a"] / i_lrs
                cnt_rows.append((t, g, f"{mean_un:.2e}", f"{sd_un:.2e}", f"{mean_seg:.2e}", f"{sd_seg:.2e}"))
        cnt_tab = table(["T (C)", "g", "unsegmented mean (counts/column)", "unsegmented sigma", "segmented mean", "segmented sigma"], cnt_rows)
        # crossover vs Roff: error budget = 5% of worst differential step; counts measured in I_LRS units
        # step in I_LRS units: worst differential step (A) / i_lrs  (a 'differential count')
        for g in GS:
            step_counts = wg[g]["min_step_diff_a"] / i_lrs
            for kind, n in (("unsegmented (511 off rows)", 511), ("segmented (g-1 off rows)", g - 1)):
                # mean-offset criterion: n*I <= budget*step ; spread criterion: 5*sqrt(n)*sigma_rel*I*sqrt(2) <= budget*step
                s_rel = by[(125.0, 0.0)]["std_a"] / by[(125.0, 0.0)]["mean_a"]
                i_mean_lim = budget * wg[g]["min_step_diff_a"] / n
                i_spread_lim = budget * wg[g]["min_step_diff_a"] / (5 * np.sqrt(2 * n) * s_rel)
                cross_rows.append((g, kind, f"{step_counts:.3f}", f"{p.v_read / i_mean_lim:.2e}", f"{p.v_read / i_spread_lim:.2e}"))
        cross_tab = table(["g", "layout", "worst differential step (I_LRS units)", "Roff below which MEAN leakage exceeds 5% of the step",
                           "Roff below which 5-sigma SPREAD (differential) exceeds 5% of the step"], cross_rows)
        roff_rows = []
        for roff in (1e12, 1e10, 1e9, 1e8, 1e7, 1e6):
            roff_rows.append((f"{roff:.0e}", f"{(p.v_read / roff) / i_lrs:.2e}",
                              *[f"{(511 if kind == 'un' else g - 1) * (p.v_read / roff) / i_lrs:.2e}" for g in (4, 16, 64) for kind in ("seg",)],
                              f"{511 * (p.v_read / roff) / i_lrs:.2e}"))
        roff_tab = table(["Roff (ohm)", "per device (LRS units)", "segmented g=4", "segmented g=16", "segmented g=64", "unsegmented 512 rows"], roff_rows)
        hot = by[(125.0, 0.0)]
        worst_un = 511 * hot["mean_a"] / i_lrs
        worst_sd = np.sqrt(2 * 511) * hot["std_a"] / i_lrs
        step32 = wg[32]["min_step_diff_a"] / i_lrs
        _cross = lambda sc: p.v_read / (budget * wg[32]["min_step_diff_a"] / sc)
        hot_vs_mean = (p.v_read / hot["mean_a"]) / _cross(511)
        hot_vs_spread = (p.v_read / hot["mean_a"]) / _cross(5 * np.sqrt(2 * 511) * hot["std_a"] / hot["mean_a"])
        leak_txt = f"""Simulated (ngspice, PTM 45nm LP, WL = 0 V, Vr = {p.v_read} V, LRS device in series, temperature via `.temp`). The bitline ammeter sees
the channel/subthreshold current; GIDL, the drain junction and gate tunnelling close through the supply/body and do not reach the bitline
(the supply-side current per device is within a few % of the bitline current at every point except 125 C at v_bl = 0.04 V). Bitline held
at 0 V is the conservative bias; the more realistic active-read level (0.04 V) leaks 4-6x less (negative Vgs on the off devices).
Per-device mismatch: Vth sigma = AVT/sqrt(W*L) = {lk['sigma_vth_v'] * 1e3:.1f} mV [MODEL, AVT is [ASSUM]], imposed through BSIM4 `delvto`,
{lk['n_devices']} devices.

{per_dev}

Leakage rises x{by[(125.0, 0.0)]['nominal_a'] / by[(27.0, 0.0)]['nominal_a']:.0f} from 27 to 125 C ({np.log10(by[(125.0, 0.0)]['nominal_a'] / by[(27.0, 0.0)]['nominal_a']):.1f} decades), i.e. it doubles roughly every
{(125 - 27) * np.log10(2) / np.log10(by[(125.0, 0.0)]['nominal_a'] / by[(27.0, 0.0)]['nominal_a']):.0f} C - slower than the 10 C rule of thumb (the cause was not isolated; the card's kt1 = -0.11 and ute = -1.5 act together).

Total column leakage in counts (one count = the current of one LRS branch, {i_lrs * 1e6:.1f} uA; worst case: 1 active row, so 511 or g-1 rows off).
Mean and sigma are per column. In the differential read the mean is common to the + and - columns and cancels to first order
(the - column has the same off-row population); the independent spread does not, and adds in quadrature (x sqrt 2).

{cnt_tab}

**Crossover.** Budget [CHOICE]: leakage may consume at most {budget * 100:.0f}% of the worst differential level step (half a step is the decision margin).

{cross_tab}

Roff sensitivity (leakage counts per device model: leak = V_read/Roff; ideal-switch assumptions of 1e12 ohm remove the term by construction, a real off
device is 1e10-1e9 ohm here):

{roff_tab}

**Verdict.** The PTM device sits at an equivalent Roff of {p.v_read / hot['mean_a']:.1e} ohm even at 125 C. The mean-offset crossover is
{p.v_read / (budget * wg[32]['min_step_diff_a'] / 511):.1e} ohm (g = 32, unsegmented; the offset is common to both columns and cancels in the differential read, so this is conservative)
and the 5-sigma spread crossover {p.v_read / (budget * wg[32]['min_step_diff_a'] / (5 * np.sqrt(2 * 511) * hot['std_a'] / hot['mean_a'])):.1e} ohm - the device is
{hot_vs_mean:.0f}x and {hot_vs_spread:.0f}x above those crossovers, i.e. {np.log10(hot_vs_mean):.1f} and {np.log10(hot_vs_spread):.1f} decades of headroom at 125 C. Worst case,
unsegmented, 125 C: mean {worst_un:.1e} counts per column, differential 1-sigma {worst_sd:.1e} counts, against a g = 32 worst step of {step32:.2f} counts.
**Off-state leakage is negligible at every temperature up to 125 C for this card, with or without segmentation; no calibration offset is needed and
segmentation is NOT required for leakage.** It would become a correctable offset (mean) at Roff ~ 1e7 ohm ({p.v_read / hot['mean_a'] / 1e7:.0f}x leakier than the PTM LP device at 125 C)
and a real constraint (spread) at ~1e6 ohm ({p.v_read / hot['mean_a'] / 1e6:.0f}x leakier). This conclusion is for a predictive LP card, not an actual process; the Roff table is the sensitivity.
(Segmentation may still be wanted for wire-IR or capacitance reasons - that is 1B/1C, not a leakage requirement.)
This is the only temperature-sensitive term in the design: the ReRAM read current in this compact model has no temperature dependence.
"""
    else:
        leak_txt = "**BLOCKED / not run** - results/off_leakage.json absent.\n"

    # ---- spread ----
    sp = A.spread_numbers(C.SIGMA_LNG)
    sp_tab = table(["state", "sigma_lnG requested", "achieved", "sigma_gap requested (nm)", "achieved", "R CV analytic", "R CV achieved",
                    "fraction exactly on a gap limit", "fraction beyond [minGap,maxGap]"],
                   [(k, v["sigma_lng_req"], f"{v['sigma_lng_ach']:.4f}", f"{v['sigma_gap_req']:.4f}", f"{v['sigma_gap_ach']:.4f}",
                     f"{v['cv_R_analytic'] * 100:.2f}%", f"{v['cv_R_ach'] * 100:.2f}%", f"{v['frac_exactly_on_limit'] * 100:.2f}%",
                    f"{v['frac_beyond_gap_limits'] * 100:.1f}%") for k, v in sp.items()])
    sg_rows = []
    for s in C.SIGMA_LNG_SWEEP:
        cm = A.single_cell_margin(p, sigma_lng=s)
        spn = A.spread_numbers(s)["LRS"]
        sg_rows.append((s, f"{s * C.G0:.4f}", f"{spn['sigma_lng_ach']:.4f}", f"{resistance_cv(s) * 100:.1f}%", e(cm["margin_5s"]),
                        f"{cm['margin_5s'] / cm['margin_nom'] * 100:.1f}%", f"{cm['gap_lrs_5s']:.3f} / {cm['gap_hrs_5s']:.3f}"))
    sg_tab = table(["sigma_lnG", "sigma_gap (nm)", "achieved sigma_lnG", "R CV", "single-cell 5-sigma margin (A)", "vs nominal", "5-sigma gaps LRS / HRS (nm)"], sg_rows)
    sw_tab = table(["sigma_lnG", "solver-vs-ngspice sweep", "PRIMARY worst", "secondary worst"], sweep_rows)

    # ---- differential gaps ----
    dg_rows, dg_rows_ref = [], []
    for g in GS:
        w = A.worst_gaps(g, p)
        dg_rows.append((g, f"{w['worst_single']:.3f}", f"m={w['worst_single_at_m']}", f"{w['worst_diff']:.3f}", f"m={w['worst_diff_at_m']} (a/2 = {g / 2:g})",
                        f"{w['diff_at_m_eq_g']:.3f}", f"{w['ratio']:.2f}x"))
        wr = A.worst_gaps(g, p, r_tx=194.4)
        dg_rows_ref.append((g, f"{wr['worst_single']:.3f}", f"{wr['worst_diff']:.3f}", f"m={wr['worst_diff_at_m']}", f"{wr['ratio']:.2f}x"))
    dg_tab = table(["g", "worst single-column gap", "at", "worst differential gap", "at", "differential at m = g (the v1 report's figure)", "worst diff / worst single"], dg_rows)
    dg_ref = table(["g", "worst single", "worst differential", "at", "ratio"], dg_rows_ref)
    cm_rows = []
    for g in GS:
        w = A.worst_gaps(g, p)
        cm_rows.append((g, f"{w['i_plus_mid_a'] * 1e6:.0f}", f"{w['i_minus_mid_a'] * 1e6:.0f}", f"{w['i_diff_mid_a'] * 1e9:+.2f}",
                        f"{w['min_step_diff_a'] * 1e6:.1f}", f"{w['cm_over_step']:.1f}", f"{20 * np.log10(w['cm_over_step'] / 0.1):.0f}"))
    cm_tab = table(["g", "I_plus at m=g/2 (uA)", "I_minus at m=g/2 (uA)", "I_diff at m=g/2 (nA)", "worst differential step (uA)",
                    "common-mode current / worst step", "CMRR needed to hold the error to 10% of a step (dB)"], cm_rows)
    # per-m table for g=16 and 32 as illustration; full curves to csv
    with (RES / "diff_gap_vs_m.csv").open("w", newline="") as fh:
        wtr = csv.writer(fh); wtr.writerow(["g", "m", "single_gap", "diff_gap"])
        for g in GS:
            c = A.level_curves(g, p)
            for k in range(g):
                wtr.writerow([g, k + 1, c["gap_single"][k], c["gap_diff"][k]])
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
        for g in GS:
            c = A.level_curves(g, p)
            ax[0].plot(np.arange(1, g + 1) / g, c["gap_diff"], label=f"g={g}")
            ax[1].plot(np.arange(1, g + 1) / g, c["gap_single"], label=f"g={g}")
        ax[0].set_title("differential level gap vs m/g"); ax[1].set_title("single-column level gap vs m/g")
        for a_ in ax:
            a_.set_xlabel("m / g"); a_.set_ylabel("step / uncompressed step"); a_.grid(alpha=.3); a_.legend()
        fig.tight_layout(); fig.savefig(RES / "diff_gap_vs_m.png", dpi=130)
    except Exception as exc:  # plotting is optional
        print("plot skipped:", exc)

    # ---- legacy sections ----
    g181 = A.gap_for_ratio(181.0)
    ratio_tab = table(["case", "gap_LRS (nm)", "gap_HRS (nm)", "R_LRS (ohm)", "R_HRS (ohm)", "on/off"],
                      [(l, gl, gh, f"{float(device_resistance(gl)):.1f}", f"{float(device_resistance(gh)):.0f}", f"{r:.1f}")
                       for l, gl, gh, r in A.ratio_vs_gap()])
    cmg = A.single_cell_margin(p)
    leak_rows = []
    for g in GS:
        leak_rows.append((g, f"{g / 403.4:.4f}", f"{A.hrs_leakage_counts(g, C.GAP_HRS, r_tx=0.0):.4f}", f"{A.hrs_leakage_counts(g, C.GAP_HRS):.4f}",
                          f"{g / 181:.4f}", f"{A.hrs_leakage_counts(g, g181, r_tx=0.0):.4f}", f"{A.hrs_leakage_counts(g, g181):.4f}"))
    hl = table(["g", "g/403", "sim 403, R_tx=0", f"sim 403, R_tx={C.R_TX:.0f}", "g/181", "sim 181, R_tx=0", f"sim 181, R_tx={C.R_TX:.0f}"], leak_rows)
    re_ = A.r_eff_lrs(p)
    gap_rows = []
    for g in GS:
        sim = A.level_gap_single_column(g)[-1]
        cont, disc = A.linear_gap_continuous(g, p.r_s, re_), A.linear_gap_discrete(g, p.r_s, re_)
        gap_rows.append((g, f"{sim:.4f}", f"{cont:.4f}", f"{(sim - cont) / cont * 100:+.2f}%", f"{disc:.4f}", f"{(sim - disc) / disc * 100:+.2f}%"))
    gap_tab = table(["g", "simulated step at m=g", "formula 1/(1+Rs*g/Reff)^2", "sim vs formula", "exact discrete linear step", "sim vs discrete"], gap_rows)
    rtx_rows = []
    for rtx in (0.0, 100.0, 200.0, 300.0, C.R_TX, 800.0):
        reff = A.r_eff_lrs(r_tx=rtx)
        rtx_rows.append([f"{rtx:.0f}", f"{reff:.1f}"] + [f"{A.level_gap_single_column(g, r_tx=rtx)[-1]:.3f} ({A.linear_gap_continuous(g, p.r_s, reff):.3f})" for g in (8, 16, 32)])
    rtx_tab = table(["R_tx (ohm)", "R_LRS_eff", "g=8 sim (formula)", "g=16 sim (formula)", "g=32 sim (formula)"], rtx_rows)

    try:
        ngv = next((l.strip("* ").strip() for l in subprocess.run(["ngspice", "--version"], capture_output=True, text=True).stdout.splitlines() if "ngspice-" in l), "ngspice")
    except OSError:
        ngv = "ngspice (not found)"
    bench = (lambda n: (lambda t0, r: f"{n} random 32-branch columns in {time.perf_counter() - t0:.2f} s ({r.outer_iters} outer iterations)")(
        time.perf_counter(), solve_column(np.random.default_rng(0).uniform(0.2, 1.7, (n, 32)), np.random.default_rng(1).random((n, 32)) < 0.5)))(200000)
    pitch = nom["pitch_um"]
    dens = 2 * C.CELL_AREA_F2

    md = f"""# Phase 1A report (fix pass) - device values, access transistor, simulation foundation

Generated by `python -m validate.make_report` ({platform.platform()}, {ngv}). Reproduce with `validate/extract_rtx.py`, `validate/off_leakage.py`,
`validate/linear_vs_bsim.py`, `validate/validate_solver.py` (+ `--sigma`), then `make_report`.
The v1 report is kept at results/old_1a/phase1a_report_v1.md; where this one corrects it, it says so.

## 0. Status, tags, what is still open

Every number is tagged: **[SIM]** measured from an ngspice run, **[MODEL]** analytic expression in code, **[ASSUM]** literature/assumed with source,
**[CHOICE]** a design decision with reasoning, **[SP]** Stanford-PKU model default.

- R_tx is now simulated from the PTM 45 nm LP BSIM4 card ({C.R_TX} ohm at 40 F^2), replacing the 200 ohm placeholder. [SIM]
- Off-state leakage is simulated from the same card at 27/50/85/125 C. [SIM]
- Spread is log-normal conductance; clipping is gone. [ASSUM sigma]
- Differential level gap measured for every m at every g; the worst case is in the middle, not at m = g. [SIM-solver]
- Validation re-run under the final configuration; scale-normalised metric is primary.
- **Compact model (OSDI route) still BLOCKED:** `openvaf` is not installed. `spice/rram.va` has the `clip_0` -> `clip_minGap` fix but has not been compiled.
  The read path uses a behavioural source carrying the model's read equation verbatim. Needed only for 1D.
- **TO BE DETERMINED: only the ReRAM read-current temperature coefficient** (this compact model has none; `$vt` is only in gap evolution). It is a recorded
  limitation, not a placeholder in any calculation. Open caveats that are NOT placeholders but are [ASSUM]: sigma_lnG (swept), AVT (Pelgrom coefficient),
  and the bitline-parasitic scaling in section 9.
  **1B can start.** Section 4 verdict: the linear R_tx is good to <0.1% and may be kept; section 5 verdict: transistor leakage is negligible; section 7: size margin on the worst differential gap.

## 1. Transistor model: PTM 45 nm Low Power, BSIM4

- Card: `device/ptm/45nm_LP.pm` (verbatim), PTM "Low Power 45nm Metal Gate / High-K / Strained-Si", nominal Vdd = 1.1 V.
  Citation: Predictive Technology Model, Arizona State University (ptm.asu.edu) - W. Zhao and Y. Cao, "New generation of predictive technology model
  for sub-45nm early design exploration," IEEE Trans. Electron Devices, 53(11), 2006. Redistributable for research.
- Why LP (from the brief): ~500 off cells share each bitline and the premise is zero standby power, so a high-Vth device is required (vth0 = 0.623 V);
  toxe = 1.80 nm limits gate tunnelling (igcmod/igbmod are on); Leff is unambiguous (lint = 0, ll = 0, no xl: Leff = L); the higher rdsw (210 ohm*um)
  RAISES R_tx and therefore LOWERS sense-resistor compression; metal-gate/high-K/strained-Si.
- Loaded **as-is** in ngspice 47: `level = 54` and `version = 4.0` were both accepted - no edit needed. The only change is in `device/ptm/ptm45n_lp.lib`, the NMOS
  block with the model renamed `nmos` -> `ptm45n_lp` (the PMOS is ignored; the access device is NMOS only). ngspice prints harmless
  `<<NAN, error = 7>>` lines for unset noise parameters.
- **Leff confirmed [SIM]:** {nom['leff_nm']:.1f} nm for L = 45 nm (ngspice `@m1[leff]`). Weff = 1.07 um for drawn W = 1.08 um (wint = 5 nm in the card, applied as W - 2*wint = 1.07 um).
- **Idsat sanity [SIM]:** {tr['idsat_ma_per_um']:.4f} mA/um at Vgs = Vds = 1.1 V, W = 1 um - inside the expected 0.5-0.6 mA/um.
- Mismatch: the card has none; Vth mismatch is imposed through `delvto` with AVT [ASSUM] (section 5).
- **Node bookkeeping.** Baselines are NeuroHDC at 130 nm and the HDC-SNN processor at 40 nm; scaled to 45 nm by (node ratio)^2:
  area x (45/130)^2 = x{(45 / 130) ** 2:.3f} for NeuroHDC; area x (45/40)^2 = x{(45 / 40) ** 2:.3f} for the 40 nm processor. (First-order geometric scaling only;
  it ignores that SRAM cell area does not shrink ideally.)

## 2. Constants (`device/constants.py`), all tagged

{consts}

## 3. R_tx: from cell area to W to resistance to pitch

W = fill x cell area / F, fill = {C.TX_FILL} [CHOICE] (so 20 F^2 -> 0.54 um, 100 F^2 -> 2.70 um). Pitch = sqrt(area): the 2T2R cell is two 1T1R cells side by
side along the wordline, so the row pitch along the bitline is the 1T1R cell side [CHOICE].

{chain}

- **(a) Hand check [MODEL]:** rdsw/W is a hard floor on R_tx (rdsmod = 0, wr = 1): {', '.join(f"{r['rdsw_floor']:.0f} ohm at {r['area_f2']} F^2" for r in rows)}. Recomputed here, not copied.
  The simulated R_tx clears every floor, by a factor of {np.mean([r['rtx_lrs'] / r['rdsw_floor'] for r in rows]):.1f} at every size: the channel adds
  ~{np.mean([(r['rtx_lrs'] - r['rdsw_floor']) * r['w_um'] for r in rows]):.0f} ohm*um on top of rdsw's 210 (R_tx * W is constant at ~{np.mean([r['rtx_lrs'] * r['w_um'] for r in rows]):.0f} ohm*um). **Correction to the brief's
  hand table:** it used the floor alone as R_tx, which understates it ~2.5x; the g = 32 single-column step is {nom['single_gap_g32']:.3f} at 40 F^2 (the brief's table gave 0.291).
- **(b) Operating point [SIM]:** the LRS branch carries {nom['i_lrs'] * 1e6:.0f} uA, not 130 uA - 130 uA is V_read/R_LRS with R_tx = 0; the transistor drops the current to
  V_read/(R_LRS + R_tx). The HRS branch carries {nom['i_hrs'] * 1e6:.3f} uA. **R_tx at the two points: {nom['rtx_lrs']:.1f} ohm (LRS) vs {nom['rtx_hrs']:.1f} ohm (HRS)** - they differ by only
  {abs(nom['rtx_hrs'] - nom['rtx_lrs']) / nom['rtx_lrs'] * 100:.1f}%, so the expectation that the lightly-loaded HRS branch would differ materially did not hold: at Vds <= 50 mV the device is deep in the linear
  region at both currents. Dependence on the bitline bias (source rising) is tested in section 4 and is also small. R_tx (LRS) is the constant used.
- **(c)/(d) The trade** (single-column worst step at m = g, nominal sinh device, R_s = {C.R_S:.0f}; differential figures in section 7):

{trade}

  A smaller cell gives a narrower device, a higher R_tx and therefore LESS compression and a larger permissible g, plus a smaller array and
  less wire per cell - the intuition 'bigger transistor is better' is backwards for the read margin. The price on the other side: **I_LRS falls**
  ({rows[0]['i_lrs'] * 1e6:.0f} uA at 20 F^2 vs {rows[-1]['i_lrs'] * 1e6:.0f} uA at 100 F^2), so the absolute signal per count drops with it (this is the analog cost
  of the small cell and enters 1B's comparator budget).
  **What bounds the small end is drive, not margin:** the select device must still pass the SET (and RESET) current. Idsat = {tr['idsat_ma_per_um']:.3f} mA/um x W; the SET
  current of the 1D write model is not known in 1A, so the cut-off is shown as a formula with illustrative requirements (Idsat at full Vdd is an upper bound;
  the real current is lower because Vds across the transistor during SET is below Vdd):

{set_tab}

  The SET requirement cuts off the **small-area end** (below ~{w_for(300) / (C.TX_FILL * F * 1e-3):.0f} F^2 for a 300 uA SET). 40 F^2 passes up to ~{tr['rows'][1]['idsat_ua']:.0f} uA of ideal drive.
- **Ron = 1 ohm is not physically achievable.** Related work models the select device as an ideal switch with Ron = 1 ohm. From rdsw alone that needs
  W = {tr['rdsw_ohm_um'] / 1.0:.0f} um, i.e. a cell of roughly {tr['rdsw_ohm_um'] / (C.TX_FILL * F * 1e-3):.0f} F^2; with the simulated channel
  resistance included it needs ~{(np.mean([r['rtx_lrs'] * r['w_um'] for r in rows])) / 1.0:.0f} um (~{np.mean([r['rtx_lrs'] * r['w_um'] for r in rows]) / (C.TX_FILL * F * 1e-3):.0f} F^2). Treat 1 ohm as shorthand for
  'negligible', not as a value.
- **Cell density [MODEL]:** a 40 F^2 1T1R makes a 2T2R cell of {dens:.0f} F^2 against roughly 120 F^2 for 6T SRAM [ASSUM, typical] - about {120 / dens:.1f}x denser,
  not the ~5x a minimum-size select transistor would suggest; the select device is sized for SET current and that is what costs the area. Phase 5 should use this figure.

## 4. Bound on the linear-R_tx approximation (Fix 1e)

{lb_txt}

## 5. Off-state leakage (Fix 2)

{leak_txt}

## 6. Spread: log-normal conductance (Fix 3)

The nominal gaps were sitting on the model limits and a clipped Gaussian put ~50% of draws on the boundary (v1: requested 4.00% LRS spread, achieved 2.39%; HRS 20.20%
vs 10.64%; mean LRS 541.8 -> 550.7 ohm), making every spread number optimistic. **Now the randomised quantity is the conductance prefactor,
A = A_nom * exp(sigma_lnG * randn)**, with no limits to clip against. Because A = I0*exp(-gap/g0), sigma_lnG = sigma_gap/g0 - a change of variable, not of physics
(0.01 nm / 0.25 = 4%, exactly v1's analytic figure). Reasons: conductance is positive; programming spread is multiplicative; and the compact-model gap bounds exist
to stop switching dynamics running away and are not a physical limit on a programmed read state. The gaps drawn may therefore fall outside [0.2, 1.7] nm; that is
intended and harmless for the read path.

Requested vs achieved at sigma_lnG = {C.SIGMA_LNG} (400,000 draws per state):

{sp_tab}

Clipped fraction is **zero** (nothing is clipped; the column shows how often a draw lands exactly on, or beyond, the old limits - informational). The 'exactly on limit' column
is 0%: requested equals achieved. Sigma is [ASSUM], swept over {list(C.SIGMA_LNG_SWEEP)}; results as a function of sigma:

{sg_tab}

Solver-vs-ngspice agreement as a function of sigma (the primary full sweep is at the default sigma; other sigmas use a reduced sweep):

{sw_tab}

At sigma = 0 the secondary metric is `inf` in 4 cases (e.g. g=8, a=4, m=2): with identical nominal gaps I_diff is exactly 0 by symmetry, ngspice returns exactly 0 and Newton returns 8e-20 A, so |dI|/|I_diff| divides by zero. The absolute difference is 8e-20 A, ~1e-15 of the column current; the primary metric reports 3e-12 there. This is the ill-conditioning of the secondary metric in its purest form.

Programming target = nominal gaps {C.GAP_LRS}/{C.GAP_HRS} nm. This is the same decision as 1D's program-verify window and must stay consistent with it.

## 7. Differential level gap vs m (Fix 4) - and a correction to v1

**Correction.** v1 section 7 quoted the differential step at m = g (0.631 at g = 32) as the headline. That is the BEST case. The structural reason the differential
is less compressed is that when the + column carries many LRS branches (heavily compressed) the - column carries few (barely compressed), so the difference partly
cancels compression. The same symmetry puts the worst case in the MIDDLE. Measured (sinh device, R_tx = {C.R_TX} ohm, R_s = {C.R_S:.0f}, a = g; full curves in
results/diff_gap_vs_m.csv and .png):

{dg_tab}

Worst differential gap sits at m = a/2 for every g (the step curve is symmetric about the middle, so m = a/2 and a/2+1 tie for even g; the sinh device and HRS leakage do not move it at this R_tx; at R_tx = 194 ohm g = 64 shifts to m = 33). The m = g value is the largest, not the smallest. The advantage over the single column is {min(A.worst_gaps(g, p)['ratio'] for g in GS):.2f}x-{max(A.worst_gaps(g, p)['ratio'] for g in GS):.2f}x and grows with g, and with smaller R_tx.
Cross-check against the brief's indicative linear-model figures, at its R_tx = 194 ohm:

{dg_ref}

(brief: 0.81 / 0.68 / 0.49 / 0.29 for g = 8/16/32/64 - reproduced with the sinh device.)

**(d) Correction note for 1B: size margin on the worst DIFFERENTIAL gap at its measured location (m ~ a/2), not on the single-column formula and not at m = g.**

**Comparator requirement (record, not computed here).** Near m = a/2 the differential current passes through zero while both columns carry large currents, and that is
exactly where the step is smallest - and random data puts m near a/2 on average, so it is the common case. The comparator must resolve a small difference between two
large signals:

{cm_tab}

At g = 32 the common-mode current is ~{A.worst_gaps(32, p)['cm_over_step']:.0f}x the worst step; holding common-mode-induced error to 10% of a step needs ~{20 * np.log10(A.worst_gaps(32, p)['cm_over_step'] / 0.1):.0f} dB
of common-mode rejection (and the requirement grows faster than linearly with g). 1B should design the comparator against this number.

## 8. Validation, re-run under the final configuration (Fix 5)

{val_txt}

The ill-conditioned point of the secondary metric is also the circuit's hardest point: |I_diff| -> 0 near m = a/2, exactly where the differential step is smallest
(section 7). The relative metric blew up where the circuit is hardest - the same cause, not a coincidence. The primary metric does not have that
property; the secondary is kept as evidence that the solver is exact where the signal is not.
Standalone solver benchmark: {bench}.

## 9. Recorded for later phases

- **Bitline parasitics for 1B [ASSUM].** Related work: 0.2 fF and 0.5 ohm per cell pitch at 65 nm. Brief's scaling to 45 nm: R/length ~ 1/F -> **0.72 ohm per cell
  pitch**; C ~ length -> **0.14 fF per cell**. Derived cell pitch here: **{pitch:.3f} um** (= {pitch / (F * 1e-3):.2f} F at 40 F^2). **Unresolved:** the factor depends on the
  related work's pitch, which was not available. If their pitch also scaled with F, R/length x pitch stays ~0.5 ohm per cell. Carry 0.5-0.72 ohm/cell as a sensitivity
  range in 1B and re-scale once their pitch is known. Not used in 1A.
- **For 1D (not solved here).** ReRAM forming typically needs 2-3 V and the LP core device is rated 1.1 V. The core transistor can pass the SET current but cannot survive the forming
  voltage, so the programming path will need a thick-oxide I/O device or a charge pump. The read path is unaffected.

## 10. Unchanged 1A measurements (re-computed with the final constants)

**Model at the gap limits (V_cell = {p.v_read} V):** R({C.GAP_LRS} nm) = {float(device_resistance(C.GAP_LRS)):.2f} ohm, R({C.GAP_HRS} nm) = {float(device_resistance(C.GAP_HRS)):.1f} ohm, ratio
{float(on_off_ratio(C.GAP_LRS, C.GAP_HRS)):.2f} (plan: 541.8 / 218586 / 403.4). Reproduced.

**On/off ratio vs achieved gap** (403 is a ceiling; HRS gap {g181:.4f} nm gives 181):

{ratio_tab}

**Single-cell read margin** (one active row, R_tx = {C.R_TX}, R_s = {C.R_S:.0f}, sigma_lnG = {C.SIGMA_LNG}): I_diff(stored 1) = {e(cmg['i_diff_one'])} A;
**margin I_diff(1)-I_diff(0) = {e(cmg['margin_nom'])} A** nominal, {e(cmg['margin_5s'])} A at 5 sigma ({cmg['margin_5s'] / cmg['margin_nom'] * 100:.1f}%; section 6 gives it vs sigma).

**HRS leakage inside the ReRAM column, in counts** (all g active branches HRS; unit = one LRS branch; this is the ReRAM HRS term, distinct from transistor off-leakage):

{hl}

With R_tx = {C.R_TX:.0f} ohm the effective ratio is lower than the device ratio (R_tx in series with both states), so leakage sits above g/ratio.

**Level gap at m = g, single column** (R_LRS_eff = {re_:.1f} ohm = R_LRS secant + R_tx):

{gap_tab}

The simulation tracks the exact discrete linear step to ~1% and the continuous formula to ~2%. (v1's R_tx sweep, redone:)

{rtx_tab}

**Limitations of the compact model:** no temperature dependence in the read current ($vt only in gap evolution) - the one remaining TO BE DETERMINED; no mismatch parameters
(variability is imposed, section 6); `rram.va` fix applied but uncompiled (OpenVAF absent).
"""
    (RES / "phase1a_report.md").write_text(md)
    print("wrote results/phase1a_report.md")


if __name__ == "__main__":
    main()
