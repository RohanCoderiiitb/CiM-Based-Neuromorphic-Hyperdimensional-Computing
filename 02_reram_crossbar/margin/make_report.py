"""Render results/reports/phase1b_provisional_report.md from results/margin_budget/* plus targeted re-evaluations.

Usage: python -m margin.make_report
"""
from __future__ import annotations

import paths as RP

import json
import math
from pathlib import Path

import numpy as np

import device.constants as C
from margin import ladder as LD
from margin import surface as S
from margin.core import draw_z, levels, mc_levels, params_for
from margin.point import BUDGET_TERMS, evaluate_point

ROOT = Path(__file__).resolve().parents[1]
RES = RP.RESULTS
SIGMAS_NZ = tuple(s for s in C.SIGMA_LNG_SWEEP if s > 0)
SCORE_SIGMAS = (0.05, 0.10, 0.15)       # [CHOICE] the middle of the assumed 5-20% range scores the recommended point
SHORT = {"device spread": "spread", "absolute signal (comparator noise)": "abs.signal", "ReRAM HRS leakage residual": "HRS leak",
         "CMRR": "CMRR", "grid-limited": "grid"}


def tbl(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def ua(x: float, d: int = 1) -> str:
    return f"{x * 1e6:.{d}f}"


def gstar_search(area, r_s, sigma, **kw):
    """Ascending search over G_SWEEP; stops at the first failure (ok is monotone in g - checked on the full surface). Returns (g*, limiter)."""
    best, lim = 0, "-"
    for g in C.G_SWEEP:
        r = evaluate_point(g, area, r_s, sigma, n=C.MC_DRAWS, **kw)
        if r["ok"]:
            best = g
        else:
            return best, S.limiting(r)
    return best, "grid-limited"


def main() -> None:
    rows = S.load(fine=False); idx = S.index(rows)      # the 1B-i report stays on the original sigma grid
    lk = json.loads(RP.HRS_LEAKAGE_JSON.read_text())
    G = C.G_SWEEP

    # ---------------- surface + recommendation ----------------
    gtab, mono_bad = {}, 0
    for k, by_g in idx.items():
        gs, lim, mono = S.g_star(by_g)
        gtab[k] = (gs, lim)
        mono_bad += (not mono)
    cand = []
    for area in C.AREA_SWEEP_F2:
        for rs in C.R_S_SWEEP:
            gs = [gtab[(area, rs, sg)][0] for sg in SCORE_SIGMAS]
            ml = np.mean([idx[(area, rs, sg)][max(g, 1)]["margin_left_frac"] for g, sg in zip(gs, SCORE_SIGMAS)])
            cand.append((sum(math.log2(max(g, 1)) for g in gs), ml, area, rs, gs))
    cand.sort(reverse=True)
    _, _, A_REC, RS_REC, gs_rec = cand[0]
    A_ALT = 40
    g_rec = {sg: gtab[(A_REC, RS_REC, sg)][0] for sg in C.SIGMA_LNG_SWEEP}
    G_HAND = g_rec[0.10]                         # [CHOICE] handoff g: the middle sigma
    rec_left10 = idx[(A_REC, RS_REC, 0.10)][max(g_rec[0.10], 1)]["margin_left_frac"]
    rec_left15 = idx[(A_REC, RS_REC, 0.15)][max(g_rec[0.15], 1)]["margin_left_frac"]
    def fragile(a, rs, sg):
        """True if g* closes with < 5% of the limit to spare, or the next g fails by < 5%: inside the ~2-3% sampling error, so the grid step is not robust."""
        by = idx[(a, rs, sg)]
        gs_ = gtab[(a, rs, sg)][0]
        nxt = [g for g in G if g > gs_]
        return (gs_ > 0 and by[gs_]["margin_left_frac"] < 0.05) or (nxt and by[nxt[0]]["margin_left_frac"] > -0.05 and not by[nxt[0]]["ok"] and by[nxt[0]]["cmrr_ok"])
    surf_tabs = []
    for sg in C.SIGMA_LNG_SWEEP:
        r = [[a] + [f"{gtab[(a, rs, sg)][0]}{'*' if fragile(a, rs, sg) else ''} ({SHORT.get(gtab[(a, rs, sg)][1], gtab[(a, rs, sg)][1])})" for rs in C.R_S_SWEEP] for a in C.AREA_SWEEP_F2]
        surf_tabs.append(f"**sigma_lnG = {sg}** (g*, limiter of the next g)\n\n" + tbl(["cell area (F^2) \\ R_s (ohm)"] + [f"{rs:g}" for rs in C.R_S_SWEEP], r))
    # binding map summary
    from collections import Counter
    bm = []
    for sg in C.SIGMA_LNG_SWEEP:
        c = Counter(SHORT.get(gtab[(a, rs, sg)][1], gtab[(a, rs, sg)][1]) for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP)
        bm.append((sg, ", ".join(f"{k}: {v}" for k, v in sorted(c.items())) + " (of 24)"))
    n_frag = sum(1 for k in gtab if fragile(*k)); n_frag_nz = sum(1 for k in gtab if k[2] > 0 and fragile(*k))
    # R_s dependence for sigma > 0
    rs_var = [(a, sg) for a in C.AREA_SWEEP_F2 for sg in SIGMAS_NZ if len({gtab[(a, rs, sg)][0] for rs in C.R_S_SWEEP}) > 1]
    rs_var_nonfragile = [(a, sg) for (a, sg) in rs_var if not all(fragile(a, rs, sg) for rs in C.R_S_SWEEP if gtab[(a, rs, sg)][0] != max(gtab[(a, r2, sg)][0] for r2 in C.R_S_SWEEP))]
    # g* distribution
    gspan = {sg: (min(gtab[(a, rs, sg)][0] for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP),
                  max(gtab[(a, rs, sg)][0] for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP)) for sg in C.SIGMA_LNG_SWEEP}

    # ---------------- term 1: spread ----------------
    sp_rows = []
    for g in G:
        sp_rows.append([g] + [f"{idx[(A_REC, RS_REC, sg)][g]['spread5_a'] / idx[(A_REC, RS_REC, sg)][g]['delta_a']:.3f}" for sg in SIGMAS_NZ])
    sp_tab = tbl(["g"] + [f"sigma {sg}: 5-sigma spread / Delta" for sg in SIGMAS_NZ], sp_rows)
    lim_rows = [[g] + [f"{idx[(A_REC, RS_REC, sg)][g]['limit_a'] / idx[(A_REC, RS_REC, sg)][g]['delta_a']:.3f}" for sg in SIGMAS_NZ[:1]] for g in G[:1]]
    ball_rows = []
    for a in C.AREA_SWEEP_F2:
        p = params_for(a, RS_REC)
        rl = float(__import__("device.model", fromlist=["x"]).device_resistance(C.GAP_LRS))
        r = idx[(a, 5.0, 0.10)][16]
        ball_rows.append((a, f"{C.RTX_BY_AREA[a]:.0f}", f"{rl / (rl + C.RTX_BY_AREA[a]):.2f}", ua(r["delta_a"]), f"{r['spread5_a'] / r['delta_a']:.3f}",
                          gtab[(a, 5.0, 0.10)][0]))
    ball_tab = tbl(["cell area (F^2)", "R_tx (ohm)", "ballast factor R_LRS/(R_LRS+R_tx) [MODEL]", "Delta at g=16, R_s=5 (uA)", "5-sigma spread / Delta (g=16, sigma 0.10)", "g* (R_s=5, sigma 0.10)"], ball_rows)
    z0 = [r for r in rows if r["sigma"] == 0 and r["g"] >= 2]
    loc_in = sum(1 for r in z0 if r["delta_loc"] in (r["g"] // 2, r["g"] // 2 + 1))
    loc_out = [r for r in z0 if r["delta_loc"] not in (r["g"] // 2, r["g"] // 2 + 1)]
    loc_out_txt = "none" if not loc_out else ", ".join(f"(g {r['g']}, {r['area']} F^2, R_s {r['r_s']:g}: m = {r['delta_loc']})" for r in loc_out[:4])
    skew_rec = max(idx[(A_REC, RS_REC, sg)][g]["max_abs_skew"] for sg in SIGMAS_NZ for g in G if g >= 8)
    skew_all = max(r["max_abs_skew"] for r in rows if r["g"] >= 8)

    # ---------------- term 2: compression, ladder, CMRR, absolute ----------------
    cmp_rows = [[g] + [f"{idx[(A_REC, rs, 0.0)][g]['delta_norm']:.3f}" for rs in C.R_S_SWEEP] for g in G]
    cmp_tab = tbl(["g"] + [f"R_s {rs:g}" for rs in C.R_S_SWEEP], cmp_rows)
    cmp40 = [[g] + [f"{idx[(40, rs, 0.0)][g]['delta_norm']:.3f}" for rs in C.R_S_SWEEP] for g in G]
    cmp40_tab = tbl(["g"] + [f"R_s {rs:g}" for rs in C.R_S_SWEEP], cmp40)
    mu_rows = []
    for a in C.AREA_SWEEP_F2:
        for rs in (1.0, 5.0, 20.0, 50.0):
            r = idx[(a, rs, 0.0)][64]
            mu_rows.append((a, rs, f"{r['mu_uniform_min']:.2f}", f"{r['mu_nonuniform_min']:.2f}",
                            "uniform fails" if r["mu_uniform_min"] <= 0 else f"{r['mu_nonuniform_min'] / r['mu_uniform_min']:.2f}x"))
    mu_tab = tbl(["cell area", "R_s", "min margin factor, uniform ladder", "min margin factor, non-uniform", "gain"], mu_rows)
    pts0 = [idx[(a, rs, 0.0)][g] for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP for g in G]
    n_un_fail = sum(1 for r in pts0 if r["mu_uniform_min"] <= 0)
    n_nu_fail = sum(1 for r in pts0 if r["mu_nonuniform_min"] <= 0)
    n_un_fail_small = sum(1 for r in pts0 if r["mu_uniform_min"] <= 0 and r["g"] <= 16)
    # ladder at recommended point
    g_l = max(G_HAND, 2)
    p_rec = params_for(A_REC, RS_REC)
    z_l = draw_z(g_l, C.MC_DRAWS)
    mcl = mc_levels(g_l, g_l, p_rec, 0.10, z_l)
    Lm, std = mcl["mean_diff"], mcl["std_diff"]
    sig_tot = np.sqrt(std ** 2 + C.COMP_SIGMA_I_A ** 2)
    thr = LD.weighted_thresholds(Lm, sig_tot); thu = LD.uniform_thresholds(Lm)
    resid_rec = idx[(A_REC, RS_REC, 0.10)][g_l]["leak_resid_a"]
    _st = np.abs(np.diff(Lm)); step_flat = (_st[max(g_l // 2 - 1, 0)] / _st.min() - 1) * 100; std_flat = std.max() / std.min()
    mu_nu = LD.margin_factor(Lm, thr, sig_tot, C.N_SIGMA, C.HEADROOM, resid_rec)
    mu_un = LD.margin_factor(Lm, thu, sig_tot, C.N_SIGMA, C.HEADROOM, resid_rec)
    dist = LD.margins(Lm, thr)["dist"]
    lad_rows = [(m, ua(Lm[m], 2), ua(std[m], 2), (ua(thr[m], 2) if m < g_l else "-"), ua(dist[m], 2), f"{mu_nu[m]:.2f}", f"{mu_un[m]:.2f}") for m in range(g_l + 1)]
    lad_tab = tbl(["count m", "mean I_diff (uA)", "spread sigma (uA)", "threshold above (uA)", "distance to nearest threshold (uA)", "margin factor, non-uniform", "margin factor, uniform"], lad_rows)
    ladder_csv = RP.LADDER_CSV
    with ladder_csv.open("w") as fh:
        fh.write("a,k,threshold_a_between_k_and_k_plus_1\n")
        for a in range(1, g_l + 1):
            pa = mc_levels(g_l, a, p_rec, 0.10, z_l)
            sa = np.sqrt(pa["std_diff"] ** 2 + C.COMP_SIGMA_I_A ** 2)
            ta = LD.weighted_thresholds(pa["mean_diff"], sa)
            fh.writelines(f"{a},{k},{t:.9e}\n" for k, t in enumerate(ta))
    # CMRR tables (sigma = 0 rows: deterministic)
    cm_rows = [[a] + [f"{idx[(a, RS_REC, 0.0)][g]['cmrr_req_db']:.1f}" for g in G] for a in C.AREA_SWEEP_F2]
    cm_tab = tbl(["cell area \\ g"] + [str(g) for g in G], cm_rows)
    cm_rng = [[g, f"{min(idx[(a, rs, 0.0)][g]['cmrr_req_db'] for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP):.1f}",
               f"{max(idx[(a, rs, 0.0)][g]['cmrr_req_db'] for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP):.1f}"] for g in G]
    cm_rng_tab = tbl(["g", "min over (area, R_s) (dB)", "max over (area, R_s) (dB)"], cm_rng)
    ruled = []
    for lim_db in C.CMRR_SENS_DB:
        bad = [(a, rs, g) for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP for g in G if idx[(a, rs, 0.0)][g]["cmrr_req_db"] > lim_db]
        gmin = min((b[2] for b in bad), default=None)
        ruled.append((f"{lim_db:.0f} dB" + (" (primary)" if lim_db == C.CMRR_ACHIEVABLE_DB else ""), len(bad),
                      "none" if not bad else f"smallest excluded g = {gmin}; e.g. " + ", ".join(f"({b[0]} F^2, R_s {b[1]:g}, g {b[2]})" for b in bad[:3]),
                      "grid g <= " + str(max(g for g in G if not any(b[2] == g for b in bad)))))
    ruled_tab = tbl(["achievable CMRR [ASSUM]", "excluded (area, R_s, g) points of 192", "which", "largest g with no exclusion"], ruled)
    ab_rows = [[a] + [f"{ua(idx[(a, RS_REC, 0.0)][g]['delta_a'], 0)} ({idx[(a, RS_REC, 0.0)][g]['delta_norm']:.2f})" for g in G] for a in C.AREA_SWEEP_F2]
    ab_tab = tbl(["cell area \\ g: Delta in uA (normalised)"] + [str(g) for g in G], ab_rows)
    vmax = max(r["v_step"] for r in rows if r["sigma"] == 0)
    v_rec = idx[(A_REC, RS_REC, 0.0)][G_HAND]["v_step"]

    # ---------------- term 3 ----------------
    cnt = {(c["area"], c["g"], c["ratio"]): c for c in lk["counts"]}
    cnt_rows = [[g] + [f"{cnt[(40, g, r)]['counts']:.3f}" for r in C.RATIO_SWEEP] + [f"{g / C.RATIO_CEILING:.3f}"] for g in (4, 8, 16, 32, 64, 128)]
    cnt_tab = tbl(["g (40 F^2, R_s 10)"] + [f"ratio {r:g}" for r in C.RATIO_SWEEP] + ["g/403 rule"], cnt_rows)
    cnt20 = [[g] + [f"{cnt[(a, g, 403.4)]['counts']:.3f}" for a in C.AREA_SWEEP_F2] for g in (4, 8, 16, 32, 64, 128)]
    cnt20_tab = tbl(["g (ratio 403)"] + [f"{a} F^2" for a in C.AREA_SWEEP_F2], cnt20)
    win = {(w["area"], w["g"], w["ratio_design"]): w for w in lk["windows"]}
    win_rows = []
    for g in (4, 8, 16, 32, 64, 128):
        row = [g]
        for rd in (403.4, 270.4, 181.3):
            w = win[(A_REC, g, rd)]
            row.append(f"{w['r_lo']:.0f} - {w['r_hi']:.0f}")
        win_rows.append(row)
    win_tab = tbl([f"g ({A_REC} F^2, R_s 10)", "ladder designed at 403.4", "at 270.4", "at 181.3"], win_rows)
    ab = {(a["area"], a["g"], a["ratio_design"]): a for a in lk["absorb"]}
    ab_rows2 = [(g, f"{ab[(A_REC, g, 403.4)]['raw_over_delta']:.3f}", f"{ab[(A_REC, g, 403.4)]['residual_over_delta']:.3f}",
                 f"{ab[(A_REC, g, 403.4)]['absorbed_fraction'] * 100:.0f}%", f"{ab[(A_REC, g, 181.3)]['raw_over_delta']:.3f}",
                 f"{ab[(A_REC, g, 181.3)]['residual_over_delta']:.3f}", f"{ab[(A_REC, g, 181.3)]['absorbed_fraction'] * 100:.0f}%") for g in (4, 8, 16, 32, 64, 128)]
    ab_tab2 = tbl([f"g ({A_REC} F^2)", "raw shift / Delta (ratio 403)", "residual / Delta (+/-25%)", "absorbed", "raw shift / Delta (ratio 181)", "residual / Delta", "absorbed"], ab_rows2)
    leak_frac_rec = idx[(A_REC, RS_REC, 0.10)][G_HAND]["leak_resid_a"] / idx[(A_REC, RS_REC, 0.10)][G_HAND]["limit_a"]

    # ---------------- recommended point ----------------
    rec_rows = []
    for sg in C.SIGMA_LNG_SWEEP:
        gs = g_rec[sg]
        if gs == 0:
            rec_rows.append((sg, "none", "-", "-", "-", "-", gtab[(A_REC, RS_REC, sg)][1])); continue
        r = idx[(A_REC, RS_REC, sg)][gs]
        rec_rows.append((sg, gs, ua(r["delta_a"]), f"{r['total_err_a'] / r['limit_a'] * 100:.0f}%", f"{r['margin_left_a'] * 1e6:.1f}",
                         f"{r['margin_left_frac'] * 100:.0f}%", SHORT.get(gtab[(A_REC, RS_REC, sg)][1], gtab[(A_REC, RS_REC, sg)][1])))
    rec_tab = tbl(["sigma_lnG", "g*", "Delta (uA)", "budget used", "left for 1B-ii (uA)", "left (% of limit)", "limits the next g"], rec_rows)
    alt_rows = []
    for sg in C.SIGMA_LNG_SWEEP:
        alt_rows.append((sg, g_rec[sg], gtab[(40, RS_REC, sg)][0], gtab[(60, RS_REC, sg)][0], gtab[(100, RS_REC, sg)][0]))
    alt_tab = tbl(["sigma_lnG", f"recommended ({A_REC} F^2, R_s {RS_REC:g})", f"40 F^2, R_s {RS_REC:g}", f"60 F^2, R_s {RS_REC:g}", f"100 F^2, R_s {RS_REC:g}"], alt_rows)
    cyc = tbl(["g", "groups per column 512/g", "reads per timestep 88 x 512/g (before bit-row skipping)", "reads per inference (x100 timesteps)",
               "alt. if all 160 columns sense at once: 11 x 512/g per timestep"],
              [(g, C.ROWS_TOTAL // g, f"{C.BITROW_PAIRS * C.ROWS_TOTAL // g:,}", f"{C.BITROW_PAIRS * C.ROWS_TOTAL // g * C.TIMESTEPS:,}",
                f"{11 * C.ROWS_TOTAL // g:,}") for g in G])
    # a-sweep verification at the handoff point
    a_rows, worst_a, worst_ml = [], None, 9
    zg = draw_z(G_HAND, C.MC_DRAWS)
    for a in range(1, G_HAND + 1):
        r = evaluate_point(G_HAND, A_REC, RS_REC, 0.10, a=a, z=zg)
        a_rows.append((a, ua(r["delta_a"]), r["delta_loc"], ua(r["spread5_a"]), f"{r['margin_left_frac'] * 100:.0f}%"))
        if r["margin_left_frac"] < worst_ml:
            worst_ml, worst_a = r["margin_left_frac"], a
    a_tab = tbl(["active rows a", "Delta (uA)", "location m", "5-sigma spread (uA)", "budget left (% of limit)"], a_rows)

    # ---------------- sensitivities ----------------
    def sens(label, kws):
        out = []
        for kv in kws:
            row = [kv[0]]
            for a in (20, 40, 100):
                row.append(" / ".join(str(gstar_search(a, 5.0 if a != A_REC else RS_REC, sg, **kv[1])[0]) for sg in (0.05, 0.10, 0.15)))
            out.append(row)
        return tbl([label, "20 F^2: g* at sigma .05 / .10 / .15", "40 F^2", "100 F^2"], out)
    s_n = sens("N sigma [CHOICE=5]", [(f"{n}", dict(n_sigma=float(n))) for n in (3, 4, 5, 6)])
    s_c = sens("comparator sigma_I [ASSUM=1 uA]", [(f"{c * 1e6:g} uA", dict(comp_sigma=c)) for c in C.COMP_SIGMA_SENS_A])
    s_h = sens("headroom [CHOICE=20%]", [(f"{h * 100:.0f}%", dict(headroom=h)) for h in (0.0, 0.1, 0.2, 0.3)])
    s_t = sens("ratio tolerance [CHOICE=+/-25%]", [(f"{t * 100:.0f}%", dict(ratio_tol=t)) for t in (0.0, 0.25, 0.5)])
    s_r = sens("design ratio [ceiling 403.4]", [(f"{r:g}", dict(ratio=r)) for r in (403.4, 270.4, 181.3)])

    sigma_cross = {}
    for a in C.AREA_SWEEP_F2:
        sigma_cross[a] = {g: None for g in (8, 16, 32)}
    md = f"""# Phase 1B-i report - electrical margin budget and provisional g

Generated by `python -m margin.make_report`. Sweep: `margin/run_sweep.py` (960 points), leakage: `margin/run_leakage.py`. Tags as in 1A:
**[SIM]** ngspice-measured, **[MODEL]** analytic in code, **[ASSUM]** assumed/literature, **[CHOICE]** design decision, **[SP]** Stanford-PKU default.
Everything here is **PROVISIONAL**: wire IR and drift (1B-ii) can only reduce g.

## 0. Headline

1. **At 5 sigma, device spread binds almost everywhere; compression does not.** The plan expected spread not to be the binding term. With the 1A log-normal
   conductance model it is: an active group sums `a` LRS cells whose independent errors add as sqrt(a) while the step to resolve is fixed, so g is capped by
   sigma_lnG, not by R_s. g* spans **{gspan[0.05][0]}-{gspan[0.05][1]} at sigma 0.05, {gspan[0.10][0]}-{gspan[0.10][1]} at 0.10, {gspan[0.15][0]}-{gspan[0.15][1]} at 0.15 and {gspan[0.20][0]}-{gspan[0.20][1]} at 0.20** across the whole
   (R_s, cell area) grid. At sigma = 0 (no spread) the limit is the ReRAM HRS-leakage residual and compression, and g reaches {gspan[0.0][1]} (grid top).
2. **R_s barely matters once spread binds.** For sigma > 0, g* differs across R_s in only {len(rs_var)} of 16 (area, sigma) rows, and in {len(rs_var_nonfragile)} of those the difference is larger than the sampling noise (cells marked * in section 5 close or fail by < 5% of the limit, inside the Monte-Carlo error). The lever is sigma and the access-transistor
   **ballast**: R_tx in series with the cell divides its conductance spread by R_LRS/(R_LRS+R_tx) (section 2), so the **smaller cell wins** on spread as well as on compression.
3. **Recommended operating point (provisional): {A_REC} F^2, R_s = {RS_REC:g} ohm.** g* = {g_rec[0.05]} / {g_rec[0.10]} / {g_rec[0.15]} / {g_rec[0.20]} at sigma = 0.05 / 0.10 / 0.15 / 0.20.
   Handoff value for 1E: **g = {G_HAND}** (sigma 0.10, the middle of the assumed 5-20% range): **{C.ROWS_TOTAL // G_HAND} groups per column, {C.BITROW_PAIRS * C.ROWS_TOTAL // G_HAND:,} reads per timestep, {C.BITROW_PAIRS * C.ROWS_TOTAL // G_HAND * C.TIMESTEPS:,} per inference** (before bit-row skipping).
4. **Sigma is the unknown that sets the cycle count by 8x** ({C.ROWS_TOTAL // g_rec[0.20] if g_rec[0.20] else 'n/a'} vs {C.ROWS_TOTAL // g_rec[0.05]} groups). It is [ASSUM] with no authoritative source; 1D's program-verify is the only lever on it.
5. CMRR is not the binding constraint at the primary 60 dB assumption (it excludes only g = 128 at R_s = 50; section 3). Transistor off-leakage stays closed (1A). The ReRAM HRS residual and comparator noise are small next to spread.
6. **The surface is knife-edge near its closing points** ({n_frag_nz} of {sum(1 for k in gtab if k[2] > 0)} sigma > 0 cells are marked *): at the recommended point g = {g_rec[0.10]} closes at sigma 0.10 with only {rec_left10 * 100:.0f}% of the limit to spare, and g = {g_rec[0.15]} at sigma 0.15 with {rec_left15 * 100:.0f}%. Read g* as 'this grid step or the one below'.

## 1. The budget framework (`solver/budget.py`)

- **Units.** Every term is an error current in amps and is also reported as a fraction of **Delta**, the worst differential step measured at its actual location per
  operating point (never assumed). At sigma = 0 (deterministic) the worst step sits at m = g/2 or g/2 + 1 (the step curve is symmetric, so for even g the two tie) at {loc_in} of {len(z0)} points with g >= 2; exceptions: {loc_out_txt}. At sigma > 0 the minimum is flat and the Monte-Carlo
  noise moves the argmin; the step at m = g/2 exceeds the minimum by {step_flat:.2f}% at the recommended point (g = {g_l}, sigma 0.10), so the location is reported per point in `surface_points.csv` but carries no weight there.
- **Decision margin.** A count is told from its neighbour when the value lands nearer to it: error budget = Delta/2.
- **Rule.** `total = sum(uncorrectable deterministic) + sqrt(sum(random at 5 sigma)^2)`; closes iff `total < (Delta/2)(1 - headroom)`.
  Terms in this build: **{BUDGET_TERMS[0]}** (random), **{BUDGET_TERMS[1]}** (random), **{BUDGET_TERMS[2]}** (deterministic residual). **Compression is not a line**: it is what
  makes Delta smaller than its uncompressed value, so it is already inside Delta; the code refuses a term with 'compression' in its name.
  Transistor off-leakage is not a line (1A: 77x-998x headroom at 125 C). Wire IR and drift are 1B-ii.
- **Headroom = {C.HEADROOM * 100:.0f}% [CHOICE].** Reason: a reserve against MODEL error - the Gaussian-tail extrapolation of the 5-sigma estimate (heavier log-normal tail at small g), the ~2% Monte-Carlo sampling error, and
  second-order effects not modelled. It is NOT the reserve for wire IR and drift: those are explicit terms in 1B-ii and must close inside the limit, so the 'left for 1B-ii' figures below are measured against the limit after headroom.
  The plan names 20% as the starting point; sensitivity in section 5.
- **Correctable vs uncorrectable.** Leakage is deterministic in (a, m) and is absorbed by the ladder (section 3); only its **residual** enters. The mean level of the spread population is also
  absorbed: the ladder and Delta use the Monte-Carlo **population-mean** levels (a mean-conductance shift is not enough - Jensen's inequality on the compressive column moves the mean level by up to 0.11 Delta at sigma 0.2).
- **Tests** (`tests/test_budget.py`, 7 hand-computed cases: Delta=100 uA, headroom 20% -> limit 40; random 9 & 12 -> rss 15; deterministic 3+4=7; total 22 < 40; 30 & 40 random -> 50 not 70;
  strict boundary; no terms; compression refused; input validation; binding = largest standalone) and `tests/test_margin.py` (provenance, antisymmetry, regression to 1A: Delta = 110.5 uA, gap 0.587, CMRR 40.4 dB at g=32).
- **Conventions of the estimate.** Spread: Monte Carlo, {C.MC_DRAWS} draws, common random numbers across sigma/R_s/area, a = g (worst case; section 5 verifies a < g), 5 x the sample standard deviation
  of I_diff at each count, worst over counts (that is a per-count LEVEL error compared with the half-step - the correct comparison for a threshold decision; a step-difference reading would be sqrt 2 more pessimistic).
  The Gaussian 5-sigma extrapolation is approximate: max |skewness| of I_diff is {skew_all:.2f} over all points with g >= 8 ({skew_rec:.2f} at the recommended cell), small, but the tail at g <= 4 is more log-normal
  (upper tail heavier). The standard deviation itself carries ~{100 / math.sqrt(2 * (C.MC_DRAWS - 1)):.1f}% sampling error.

## 2. Term 1 - device spread (a function of sigma throughout)

5-sigma spread error as a fraction of Delta ({A_REC} F^2, R_s {RS_REC:g}); the budget limit is {(1 - C.HEADROOM) / 2:.2f} Delta minus the other terms, so entries above ~0.4 fail:

{sp_tab}

Scaling: error ~ sigma x sqrt(g) with Delta almost independent of g, so g* falls as 1/sigma^2 - a factor 2 in sigma costs a factor 4 in g (observed: g* {g_rec[0.05]} -> {g_rec[0.10]} -> {g_rec[0.15]} -> {g_rec[0.20]}).

**Ballast effect [MODEL, confirmed by the Monte Carlo].** A cell's current responds to a conductance change by a factor R_LRS/(R_LRS+R_tx) < 1, because R_tx in series regulates it.
Smaller cells have a larger R_tx (R_tx x W ~ 547 ohm.um), so they carry less spread per unit of step:

{ball_tab}

Formula check: spread/Delta ~ (N sigma sqrt(g) / 2) x ballast factor = (5 x 0.10 x 4 / 2) x ballast = 1.0 x ballast at g = 16, sigma 0.10 - exactly the last-but-one column against the ballast column.
The spread standard deviation is nearly flat across counts at the recommended point (max/min = {std_flat:.2f}), so the worst-count choice matters little.
Caveat on small g: the Gaussian 5-sigma extrapolation understates the heavier upper tail of a log-normal; at g = 1 the true 5-sigma excursion is larger by (e^(5 sigma) - 1)/(5 sigma) = {(math.exp(0.25) - 1) / 0.25:.2f}x at sigma 0.05, {(math.exp(0.5) - 1) / 0.5:.2f}x at 0.10 and {(math.exp(1.0) - 1) / 1.0:.2f}x at 0.20 (for a sum of many cells this fades; skewness is <= {skew_all:.2f} for g >= 8). Results at g <= 4 are therefore optimistic.
Full per-point values: `results/margin_budget/g_surface_points.csv`.

## 3. Term 2 - compression, the ladder, CMRR, and the absolute signal

**Compression (physics, inside Delta).** Delta / (uncompressed step), sigma = 0, {A_REC} F^2 (40 F^2 below it):

{cmp_tab}

{cmp40_tab}

**Ladder.** Thresholds are placed between adjacent population-mean levels, sigma-weighted so both neighbours keep equal margin in sigma units (equal to midpoints when sigma is flat). The ladder is indexed by `a`
(the digital popcount of the input group, known before the read), so one table per group size; `results/margin_budget/comparator_ladder_recommended.csv` holds every (a, k) threshold for the recommended point.
Levels are antisymmetric, I_diff(a, m) = -I_diff(a, a-m) (verified, exact), so only half the thresholds need storing.
**Why this is cheap for a binary readout:** an analog (multi-level) readout must undo compression on the VALUE, with a per-column runtime multiply; a threshold decision only needs its reference in the right place -
a one-time design of the thresholds, a lookup with no arithmetic at run time. That is a genuine advantage of operating binary.

The differential level curve is S-shaped (steps are smallest in the middle, 1A section 7), so a UNIFORM ladder fails as soon as g x R_s is large: it mis-decides nominal levels outright. Minimum per-count margin factor
(mu > 1 means every count is decided at 5 sigma incl. headroom; negative = a nominal level already sits on the wrong side of a uniform threshold; g = 64, sigma = 0, comparator noise only):

{mu_tab}

Over the 192 sigma = 0 grid points the uniform ladder fails (mis-decides a nominal level) at {n_un_fail}, {n_un_fail_small} of them at g <= 16; the non-uniform ladder has a margin factor <= 0 at {n_nu_fail} (after headroom, comparator noise and the leakage residual - the large-g, large-R_s corner where Delta itself is small). At the recommended point
(g = 16, R_s 5, 20 F^2) the two are indistinguishable (small group, light compression): the ladder matters when g x R_s is large, which is the regime a faster (larger-g) design would need. Per-count margin at the recommended point (g = {g_l}, sigma 0.10, {A_REC} F^2, R_s {RS_REC:g}; margin factor includes headroom, comparator noise and the leakage residual):

{lad_tab}

Worst count: m = {int(np.argmin(mu_nu))} with margin factor {mu_nu.min():.2f} (non-uniform) vs {mu_un.min():.2f} (uniform).

**CMRR - an independent bound on g.** Required CMRR = 20 log10( I_cm / (10% x Delta) ) at the worst-step location (common-mode current I_cm = (I_plus+I_minus)/2). It is a constraint beside the budget, not inside it.
Achievable CMRR is **{C.CMRR_ACHIEVABLE_DB:.0f} dB [ASSUM]**: a practical CMOS differential comparator/sense stage without trimming, textbook range ~60-80 dB (e.g. Razavi, *Design of Analog CMOS Integrated Circuits*); not verified for this
process. Required dB at R_s {RS_REC:g} (sigma = 0):

{cm_tab}

Range over all (area, R_s):

{cm_rng_tab}

Points ruled out at each assumed achievable CMRR:

{ruled_tab}

1A's figures reproduce (40 F^2, R_s 20: 40 dB at g=32). The requirement grows roughly 20 dB per decade of g, a little faster at large g and large R_s (where Delta shrinks). At the primary 60 dB it excludes only the {ruled[1][1]} points shown (g = 128 at R_s = 50);
at a 50 dB comparator it would cap g at 32 for the cells listed. At every g <= 64 the CMRR bound is looser than the spread bound by a wide margin.

**Absolute signal.** Worst differential step in amps (normalised value in brackets), {RS_REC:g} ohm, sigma = 0:

{ab_tab}

A smaller cell gives the best relative margin and the smallest absolute step ({ua(idx[(20, RS_REC, 0.0)][G_HAND]['delta_a'], 0)} uA at 20 F^2 vs {ua(idx[(100, RS_REC, 0.0)][G_HAND]['delta_a'], 0)} uA at 100 F^2, g = {G_HAND}). The comparator noise term
is **{C.COMP_SIGMA_I_A * 1e6:g} uA (1 sigma) [ASSUM, an engineering estimate, not sourced]** entering as a random term at 5 sigma = {C.N_SIGMA * C.COMP_SIGMA_I_A * 1e6:g} uA; it is at most {max(r['comp5_a'] / r['limit_a'] for r in rows) * 100:.0f}% of the limit anywhere on the grid, but at 3 uA it already costs a grid step at some points (section 5 sensitivity). **Voltage-mode caveat:** with a passive sense resistor the step swings only Delta x R_s = {v_rec * 1e3:.2f} mV at the recommended point (max {vmax * 1e3:.2f} mV anywhere on the grid)
against an uncalibrated comparator offset of ~{C.COMP_OFFSET_V * 1e3:g} mV (1 sigma) [ASSUM] - 5 sigma is {C.N_SIGMA * C.COMP_OFFSET_V * 1e3:g} mV, more than the swing anywhere on the grid; passive voltage sensing is not viable without offset cancellation and amplification, so the readout must be **current-mode / virtual-ground** (which also removes the R_s trade).

## 4. Term 3 - ReRAM HRS leakage

Leakage in counts (all g active branches HRS, one count = one LRS branch; R_tx dilutes the ratio, so it sits above the g/ratio rule: g=32, ratio 403 -> {cnt[(40, 32, 403.4)]['counts']:.3f} vs {32 / 403.4:.3f}, matching 1A's 0.157).
R_s dependence is negligible (g=32, 40 F^2, ratio 403: {lk['rs_check'][0]['counts']:.4f} at 1 ohm to {lk['rs_check'][-1]['counts']:.4f} at 50 ohm).

{cnt_tab}

vs cell area (ratio 403; R_tx lowers with area, so leakage falls):

{cnt20_tab}

**Correctable vs residual.** Leakage is deterministic in (a, m), so a ladder designed on the levels AT the array's ratio absorbs it entirely. What survives is the mismatch between the ratio the ladder was
designed for and the ratio the array actually achieved (program-verify window, die-to-die); assumed +/-{C.RATIO_TOL * 100:.0f}% [CHOICE]. Raw shift (a ladder blind to leakage) vs residual, as fractions of Delta ({A_REC} F^2, R_s 10):

{ab_tab2}

About two thirds of the leakage shift is absorbed at +/-25% (the absorbed fraction is set by the tolerance, not by g); the residual is {leak_frac_rec * 100:.0f}% of the usable margin at the recommended point.

**Crossover and the demand on 1D.** The window of achieved ratios over which a ladder designed at the stated ratio keeps the leakage residual below {C.LEAK_BUDGET_SHARE * 100:.0f}% of the usable margin [CHOICE]
({A_REC} F^2, R_s 10):

{win_tab}

Reading it for 1D: for a ladder designed at the 403 ceiling, program-verify must hold the achieved on/off ratio **above the lower edge shown for the chosen g** (e.g. g = {G_HAND}: {win[(A_REC, G_HAND, 403.4)]['r_lo']:.0f}); for a ladder designed
at a realistic 181, the window is {win[(A_REC, G_HAND, 181.3)]['r_lo']:.0f}-{win[(A_REC, G_HAND, 181.3)]['r_hi']:.0f}. The lower edge rises with g (g = 128: {win[(A_REC, 128, 403.4)]['r_lo']:.0f}), so **a tighter write buys a larger g** - the write-path/read-speed coupling.
At the recommended group sizes (g <= {G_HAND * 2}) this is a mild demand (an on/off ratio of ~{win[(A_REC, min(G_HAND * 2, 128), 403.4)]['r_lo']:.0f} or better); it only bites at g >= 64. Because spread binds long before leakage here, the leakage term never decided g* at any sigma > 0.

## 5. The g surface, the binding-term map and the recommendation

Largest g in the grid whose budget closes AND whose CMRR is achievable (primary 60 dB), with the limiter of the next g. 'spread' = device spread, 'abs.signal' = comparator noise, 'HRS leak' = ReRAM
leakage residual, 'grid' = still ok at the top of the grid (g = 128). ok is monotone in g at {len(idx) - mono_bad} of {len(idx)} points{'' if mono_bad == 0 else ' (non-monotone points are listed in surface_points.csv)'}. A '*' marks a cell whose g* closes with < 5% of the limit left, or whose next g fails by < 5%: inside the ~2-3% Monte-Carlo error plus the Gaussian-tail approximation, so the grid step there is not robust.

{chr(10).join(surf_tabs)}

**Binding-term map (count of the 24 (area, R_s) cells whose next-larger g is limited by each term):**

{tbl(['sigma_lnG', 'limiter'], [(a, b) for a, b in bm])}

Reading: for every sigma > 0 the limiter is device spread; at sigma = 0 it is the HRS-leakage residual at R_s 20-50 (where compression has shrunk Delta) and nothing within the grid at R_s <= 10. CMRR and comparator noise never decide g* at the
primary assumptions ('*' = within 5% of the limit, inside the sampling error: {n_frag} of {len(gtab)} cells overall). **The shape of the trade is therefore: the access-transistor ballast (cell area) and sigma set g; R_s and compression are second-order for the differential read.**

**Recommended operating point: {A_REC} F^2, R_s = {RS_REC:g} ohm.** Rule [CHOICE]: maximise sum log2(g*) over sigma in {{0.05, 0.10, 0.15}}, ties broken by remaining margin. Result (a = g):

{rec_tab}

What it costs, and what it risks:
- **{A_REC} F^2 is the smallest cell in the swept band.** 1A section 3 shows 20 F^2 passes ~280 uA of ideal drive; the SET current is unknown until 1D. If 1D needs more, fall back to 40 F^2 (table below), at half the g for the same sigma.
- Smallest absolute signal: Delta = {ua(idx[(A_REC, RS_REC, 0.10)][G_HAND]['delta_a'])} uA at g = {G_HAND} (vs {ua(idx[(100, RS_REC, 0.10)][max(g_rec[0.10], 1)]['delta_a'])} uA at 100 F^2), I_LRS {C.ILRS_BY_AREA_A[A_REC] * 1e6:.0f} uA; comparator must be current-mode (section 3).
- Densest array (the 2T2R cell is 2 x {A_REC} = {2 * A_REC} F^2).
- R_s is nearly a free parameter here: at 20 F^2, g* is the same for R_s 5-20 at every sigma; {RS_REC:g} ohm is the tie-break winner (the largest remaining margin at the g* values). R_s only needs to be >= ~5 for the leakage/CMRR terms to stay loose.

Alternatives (g*):

{alt_tab}

**Sensitivities (g* at sigma 0.05 / 0.10 / 0.15, R_s {RS_REC:g} for the recommended cell, 5 otherwise):**

{s_n}

{s_c}

{s_h}

{s_t}

{s_r}

**Is a = g really the worst case?** Re-evaluating the recommended point ({A_REC} F^2, R_s {RS_REC:g}, g = {G_HAND}, sigma 0.10) for every active count a = 1..g: the least budget is left at a = **{worst_a}**
({worst_ml * 100:.0f}% of the limit left); the sweep's a = g evaluation is {'confirmed as the worst case' if worst_a == G_HAND else 'NOT the worst case - see the table'}.

{a_tab}

**Cycle counts that fall out** (handoff for 1E; bit-row skipping not applied):

{cyc}

At the handoff g = {G_HAND}: {C.ROWS_TOTAL // G_HAND} groups per column, {C.BITROW_PAIRS * C.ROWS_TOTAL // G_HAND:,} crossbar reads per timestep, {C.BITROW_PAIRS * C.ROWS_TOTAL // G_HAND * C.TIMESTEPS:,} per inference. The plan counts one read per (count bit-row, weight bit-column) pair per group,
which assumes one weight bit-plane is sensed at a time; if all 160 columns are sensed simultaneously it is 11 x 512/g (last column), a decision for 1C (it also governs the multi-column droop and crosstalk).

**This g is PROVISIONAL.** Wire IR and drift (1B-ii) can only reduce it. Headroom left for them at the recommended point is the 'left for 1B-ii' column above: at sigma 0.10, g = {G_HAND}, {rec_rows[2][4]} uA ({rec_rows[2][5]} of the limit) - **effectively none**: any wire-IR or drift term above ~{rec_rows[2][4]} uA
pushes g to {max(G_HAND // 2, 1)}. At the neighbouring sigma values the same point has {rec_rows[1][5]} (0.05, g = {g_rec[0.05]}) and {rec_rows[3][5]} (0.15, g = {g_rec[0.15]}) left. (For information: the model-error reserve of {C.HEADROOM * 100:.0f}% is separate; it is not available to 1B-ii by this report's convention.)
The provisional handoff value is therefore g = {G_HAND}, with g = {max(G_HAND // 2, 1)} the likely final value once wire and drift are added if sigma is 0.10.

## 6. Risks and fallbacks (spread-limited regime)

g* is {g_rec[0.10]}, {g_rec[0.15]}, {g_rec[0.20]} at the recommended cell for sigma 0.10, 0.15, 0.20 (and 1-16 across the whole grid) - the 'g comes out small' outcome the plan flagged. Fallbacks, with what the data says:
1. **Tighten sigma** (1D program-verify): the strongest lever - sigma 0.05 gives g* {g_rec[0.05]} at the recommended cell.
2. **Smaller / more ballasted cell**: free in this model (section 2); bounded below by SET current.
3. **Accept the cycle cost**: g = {G_HAND} gives {C.BITROW_PAIRS * C.ROWS_TOTAL // G_HAND:,} reads/timestep.
4. **Relax the criterion**: N sigma = 4 or 3 raises g* (section 5) but gives up bit-exactness guarantees; with ~8 million readouts per inference, 5 sigma (3e-7 per decision) is already not conservative.
5. Active virtual-ground sensing: needed anyway for current-mode readout (section 3); it removes compression but does NOT help the spread term, which binds.

## 7. TO BE DETERMINED / open

- **sigma_lnG** [ASSUM, swept]: it sets g more than any other quantity here; needs measured data from the device group or 1D's verify loop.
- **Comparator input noise ({C.COMP_SIGMA_I_A * 1e6:g} uA) and achievable CMRR ({C.CMRR_ACHIEVABLE_DB:.0f} dB)** [ASSUM, unsourced / textbook]: neither decides g* at these values; at 3 uA / 50 dB each costs a grid step at some points (swept).
- **ReRAM read-current temperature coefficient**: still the compact model's limitation (1A); no temperature dependence is modelled in any 1B-i term.
- **SET current** (1D): bounds the cell area from below; decides 20 vs 40 F^2.
- **Wire IR and drift**: 1B-ii.
- Not done in 1B-i: the 2-D mesh, drift, solver re-validation (1A did that), any write-path work beyond the ratio requirement above, RTL, any macro.
"""
    RP.REPORTS.mkdir(parents=True, exist_ok=True)
    RP.REPORT_1B_PROVISIONAL.write_text(md)
    print("wrote", RP.REPORT_1B_PROVISIONAL)


if __name__ == "__main__":
    main()
