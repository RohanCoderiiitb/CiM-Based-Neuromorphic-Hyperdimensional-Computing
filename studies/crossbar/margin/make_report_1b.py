"""Assemble results/reports/phase1b_report.md (the consolidated 1B report) from every result artefact.

Usage: python -m margin.make_report_1b [--strategy S1]
"""
from __future__ import annotations

import paths as RP

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

import device.constants as C
from margin import figures as FG
from margin import report_1b_parts as P
from margin import surface as S
from margin.report_1b_parts import SHORT, tbl, ua
from wire import final as WF

ROOT = Path(__file__).resolve().parents[1]
RES = RP.RESULTS
OUT = RP.REPORT_1B
SCORE = (0.05, 0.10, 0.15)
PRIM_R, PRIM_SC = 0.72, "moderate"


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--strategy", default="S1"); args = ap.parse_args()
    st = args.strategy
    prov_rows = S.load(fine=True); pidx = S.index(prov_rows)
    pg = {k: S.g_star(v) for k, v in pidx.items()}
    frows = P.load_final(RP.final_points_csv(st)); fidx = P.index_final(frows)
    fg = {k: P.gstar_final(v) for k, v in fidx.items()}

    # ---------------- recommended point on the FINAL surface ----------------
    cand = []
    for a in C.AREA_SWEEP_F2:
        for rs in C.R_S_SWEEP:
            gs = [fg[(a, rs, s, PRIM_R, PRIM_SC)][0] for s in SCORE]
            ml = np.mean([fidx[(a, rs, s, PRIM_R, PRIM_SC)][max(g, 1)]["margin_frac"] for g, s in zip(gs, SCORE)])
            cand.append((sum(math.log2(max(g, 1)) for g in gs), ml, a, rs, gs))
    cand.sort(reverse=True)
    _, _, A_REC, RS_REC, _ = cand[0]
    g_rec = {s: fg[(A_REC, RS_REC, s, PRIM_R, PRIM_SC)][0] for s in C.SIGMA_FINAL_SWEEP}
    G_FIN = g_rec[0.10]
    row_rec = fidx[(A_REC, RS_REC, 0.10, PRIM_R, PRIM_SC)][max(G_FIN, 1)]
    prov_g = {s: pg[(20, 5.0, s)][0] for s in (0.05, 0.10, 0.15, 0.20)}
    rec_marg = row_rec["margin_frac"]
    fragile = rec_marg < 0.05
    print("recommended", A_REC, RS_REC, g_rec, "margin", rec_marg)

    # ---------------- final surface tables ----------------
    def surf_tab(sg, r, sc):
        rows = [[a] + [f"{fg[(a, rs, sg, r, sc)][0]} ({SHORT.get(fg[(a, rs, sg, r, sc)][1], fg[(a, rs, sg, r, sc)][1])})" for rs in C.R_S_SWEEP] for a in C.AREA_SWEEP_F2]
        return tbl(["cell area (F^2) \\ R_s (ohm)"] + [f"{rs:g}" for rs in C.R_S_SWEEP], rows)
    surf = "\n\n".join(f"**sigma_lnG = {sg}** (g*, limiter of the next g) - wire {PRIM_R:g} ohm/pitch, drift '{PRIM_SC}'\n\n{surf_tab(sg, PRIM_R, PRIM_SC)}" for sg in C.SIGMA_FINAL_SWEEP)
    bm = []
    for sg in C.SIGMA_FINAL_SWEEP:
        c = Counter(SHORT.get(fg[(a, rs, sg, PRIM_R, PRIM_SC)][1], fg[(a, rs, sg, PRIM_R, PRIM_SC)][1]) for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP)
        bm.append((sg, ", ".join(f"{k}: {v}" for k, v in sorted(c.items())) + " (of 24)"))
    bm_counts = {sg: Counter(SHORT.get(fg[(a, rs, sg, PRIM_R, PRIM_SC)][1], fg[(a, rs, sg, PRIM_R, PRIM_SC)][1]) for a in C.AREA_SWEEP_F2 for rs in C.R_S_SWEEP) for sg in C.SIGMA_FINAL_SWEEP}
    # sensitivity: wire r and drift scenario at the recommended cell
    sens_rows = []
    for sc in C.DRIFT_SCENARIOS:
        for r in C.BL_R_PER_PITCH_SWEEP:
            sens_rows.append((sc, f"{C.DRIFT_SCENARIOS[sc][0]:g}", r) + tuple(fg[(A_REC, RS_REC, s, r, sc)][0] for s in C.SIGMA_FINAL_SWEEP))
    sens_tab = tbl(["drift scenario", "nu", "wire ohm/pitch"] + [f"g* at sigma {s}" for s in C.SIGMA_FINAL_SWEEP], sens_rows)
    # how much g moved vs 1B-i, over the whole grid (sigma 0.05..0.20)
    moved = Counter(); n_cells = 0
    mv_rows = []
    for sg in (0.05, 0.10, 0.15, 0.20):
        for a in C.AREA_SWEEP_F2:
            for rs in C.R_S_SWEEP:
                g0, g1 = pg[(a, rs, sg)][0], fg[(a, rs, sg, PRIM_R, PRIM_SC)][0]
                steps = int(round(math.log2(max(g0, 1)) - math.log2(max(g1, 1)))) if g0 else 0
                moved[steps] += 1; n_cells += 1
    for sg in (0.05, 0.10, 0.15, 0.20):
        mv_rows.append((sg, pg[(A_REC, RS_REC, sg)][0], g_rec[sg], f"{'-' if g_rec[sg] == pg[(A_REC, RS_REC, sg)][0] else int(round(math.log2(pg[(A_REC, RS_REC, sg)][0] / max(g_rec[sg], 1))))} step(s)"))
    mv_tab = tbl(["sigma_lnG", f"1B-i provisional g* ({A_REC} F^2, R_s {RS_REC:g})", "final g*", "grid steps down"], mv_rows)
    moved_tab = tbl(["grid steps g fell (1B-i -> final)", "cells (of %d)" % n_cells], [(k, v) for k, v in sorted(moved.items())])

    # ---------------- budget terms at the recommended point ----------------
    tnames = [("t_device spread", "device spread", "random"), ("t_absolute signal (comparator noise)", "comparator noise (absolute signal)", "random"),
              ("t_ReRAM HRS leakage residual", "ReRAM HRS leakage residual", "det"), ("t_wire IR (within group)", "wire IR, within group", "det"),
              ("t_row-driver IR", "row-driver IR (weight dependent)", "random"), ("t_reference-cell spread", "reference-cell spread", "random"), ("t_drift", "drift level shift", "det")]
    term_rows = [(lab, kind, ua(row_rec[k], 2), f"{row_rec[k] / row_rec['delta_a'] * 100:.1f}%") for k, lab, kind in tnames if k in row_rec and row_rec[k] == row_rec[k]]
    rss = np.sqrt(sum(row_rec[k] ** 2 for k, _, kind in tnames if kind == "random" and k in row_rec and row_rec[k] == row_rec[k]))
    det = sum(row_rec[k] for k, _, kind in tnames if kind == "det" and k in row_rec and row_rec[k] == row_rec[k])
    term_tab = tbl(["term", "kind", "value (uA)", "% of worst step Delta"], term_rows)
    FG.fig3_final(row_rec, f"final budget ({st} drift strategy, wire {PRIM_R:g} ohm/pitch, drift '{PRIM_SC}' nu = {C.DRIFT_SCENARIOS[PRIM_SC][0]:g})",
                  f"the final recommended point ({A_REC} F^2, R_s = {RS_REC:g} ohm, g = {G_FIN}, sigma_lnG = 0.10, worst group = {row_rec['worst_group']})")
    FG.write_captions_md()

    # ---------------- wire / drift sections ----------------
    c0_tab, c0 = P.c0_section()
    dt = P.drift_tables()
    trade_tab, trade_raw = P.strategy_tradeoff()
    strat_final_tab, strat_final = P.strategy_final_compare(A_REC, RS_REC)
    lever_tab, lever_res = P.levers_table(A_REC, RS_REC)
    refresh_tab, e_ref_uj, n_dev = P.refresh_cost_table(dt)
    cap = json.loads((RP.FIGURES / "captions.json").read_text())
    fig_md = []
    for key, fn, title in (("fig1", "fig1_gstar_vs_sigma", "Figure 1 - g* versus conductance spread"), ("fig2", "fig2_spread_vs_g", "Figure 2 - 5-sigma spread error versus g"),
                           ("fig3_budget_stack_final", "fig3_budget_stack_final", "Figure 3 - the error budget at the final recommended point"),
                           ("fig4", "fig4_ladder_margin", "Figure 4 - uniform versus non-uniform ladder"), ("fig5", "fig5_wire_ir_vs_g", "Figure 5 - wire IR, contiguous versus interleaved"),
                           ("fig6", "fig6_diff_vs_single_gap", "Figure 6 - differential versus single-column level gap")):
        fig_md.append(f"**{title}**\n\n![{title}](../figures/{fn}.png)\n\n{cap[key]}\n\nVector: `results/figures/{fn}.pdf`, `.svg`; source data `{fn}.csv`.")
    fig3_1bi = cap.get("fig3_budget_stack", "")

    # crossover
    cx = json.loads(RP.CROSSOVER_JSON.read_text())
    cx_rows = [(p["sigma"], p["g_star"], SHORT.get(p["limiter"], p["limiter"]), ua(p["spread5_a"]), ua(p["leak_resid_a"]), ua(p["limit_a"])) for p in cx["per_sigma"]]
    cx_tab = tbl(["sigma_lnG", "g*", "limits the next g", "5-sigma spread at g* (uA)", "HRS-leak residual at g* (uA)", "budget limit (uA)"], cx_rows)
    sx_rows = [(p["g"], f"{p['sigma_x']:.4f}", ua(p["leak_resid_a"], 2)) for p in cx["per_g"]]
    sx_tab = tbl(["g", "sigma at which 5-sigma spread = HRS-leak residual", "HRS-leak residual (uA)"], sx_rows)

    decomp_tab = P.decomposition_section(); groups_tab = P.groups_section(); row_tab = P.rowside_section(); mesh_md = P.mesh_validation_section()
    drift_g_tab = P.drift_gstar_table(dt)

    _a8 = json.loads(RP.decomposition_json('contiguous', 8, 0.72).read_text())['groups'][-1]['alpha']
    _a4 = json.loads(RP.decomposition_json('contiguous', 4, 0.72).read_text())['groups'][-1]['alpha']
    _a16 = json.loads(RP.decomposition_json('contiguous', 16, 0.72).read_text())['groups'][-1]['alpha']
    far_ser_lo, far_ser_hi = c0[8][0]['far_series_ohm'], c0[8][1]['far_series_ohm']
    far_delta = c0[8][1]['delta_far_a']
    # cycle counts
    def cyc(g):
        return (C.ROWS_TOTAL // g, C.BITROW_PAIRS * C.ROWS_TOTAL // g, 11 * C.ROWS_TOTAL // g)
    cy = cyc(G_FIN)
    cyc_tab = tbl(["g", "groups per column", "reads/timestep (88 x 512/g, bit-planes one at a time)", "reads/inference (x100)", "reads/timestep (11 x 512/g, 160 columns at once)", "reads/inference (x100)"],
                  [(g, C.ROWS_TOTAL // g, f"{cyc(g)[1]:,}", f"{cyc(g)[1] * C.TIMESTEPS:,}", f"{cyc(g)[2]:,}", f"{cyc(g)[2] * C.TIMESTEPS:,}") for g in (2, 4, 8, 16)])

    # 1D table: g by sigma and ratio window
    lk = json.loads(RP.HRS_LEAKAGE_JSON.read_text())
    win = {(w["area"], w["g"], w["ratio_design"]): w for w in lk["windows"]}
    win_rows = [(g, f"{win[(A_REC, g, 403.4)]['r_lo']:.0f}", f"{win[(A_REC, g, 270.4)]['r_lo']:.0f} - {win[(A_REC, g, 270.4)]['r_hi']:.0f}",
                 f"{win[(A_REC, g, 181.3)]['r_lo']:.0f} - {win[(A_REC, g, 181.3)]['r_hi']:.0f}") for g in (4, 8, 16, 32)]
    win_tab = tbl(["g", "ladder designed at 403.4: ratio must stay above", "designed at 270.4: window", "designed at 181.3: window"], win_rows)
    sig_buy = tbl(["achievable sigma_lnG (sets g)", "final g* at the recommended cell", "groups per column", "reads/timestep (88 x 512/g)"],
                  [(s, g_rec[s], C.ROWS_TOTAL // max(g_rec[s], 1), f"{C.BITROW_PAIRS * C.ROWS_TOTAL // max(g_rec[s], 1):,}") for s in C.SIGMA_FINAL_SWEEP])
    cm = tbl(["g", "CMRR needed at the worse of the near and far group (dB)", "within the 60 dB assumption?"],
             [(g, f"{fidx[(A_REC, RS_REC, 0.10, PRIM_R, PRIM_SC)][g]['cmrr_db']:.1f}", "yes" if fidx[(A_REC, RS_REC, 0.10, PRIM_R, PRIM_SC)][g]['cmrr_db'] <= C.CMRR_ACHIEVABLE_DB else "no")
              for g in (2, 4, 8, 16) if g in fidx[(A_REC, RS_REC, 0.10, PRIM_R, PRIM_SC)] and fidx[(A_REC, RS_REC, 0.10, PRIM_R, PRIM_SC)][g]['cmrr_db'] == fidx[(A_REC, RS_REC, 0.10, PRIM_R, PRIM_SC)][g]['cmrr_db']])

    md = f"""# Phase 1B report - the margin budget, wire IR, drift, and the final g

Consolidated report for all of sub-phase 1B. The earlier `results/reports/phase1b_provisional_report.md` (1B-i) stays on disk; this is the document to read. Tags: **[SIM]** simulated (ngspice or the validated solvers),
**[MODEL]** analytic in code, **[ASSUM]** assumed/literature, **[CHOICE]** design decision, **[SP]** Stanford-PKU default.

## 0. The answer

- **Final g = {G_FIN} rows per group** at the recommended operating point **{A_REC} F^2 cell (2T2R cell = {2 * A_REC} F^2, pitch {C.PITCH_UM[A_REC]:.3f} um), R_s = {RS_REC:g} ohm (current-mode sense), contiguous groups, 32-column macros**, for
  sigma_lnG = 0.10, wire {PRIM_R:g} ohm/pitch, drift '{PRIM_SC}' (nu = {C.DRIFT_SCENARIOS[PRIM_SC][0]:g}), drift strategy **{st}**. The 1B-i provisional value was {prov_g[0.10]}.
- **g* by sigma** (same cell): {', '.join(f'{g_rec[s]} at {s}' for s in C.SIGMA_FINAL_SWEEP)}. Reads per timestep at g = {G_FIN}: **{cy[1]:,}** (88 x 512/g) or **{cy[2]:,}** (11 x 512/g if all 160 columns sense at once); **{cy[1] * C.TIMESTEPS:,}** per inference in the first case.
- **Margin left at the final point: {rec_marg * 100:.0f}% of the limit ({ua(row_rec['margin_frac'] * row_rec['limit_a'], 1)} uA of {ua(row_rec['limit_a'], 1)})** - **MARGINAL / FRAGILE**: it is inside about twice the 2-3% Monte-Carlo error, so g = {G_FIN} could equally come out as {max(G_FIN // 2, 1)}. The surface is robust to R_s and to moderate drift (sections 1.1-1.2) but not to comparator noise: at 3 uA (1 sigma) g* falls to {lever_res[('comparator 3 uA', 0.10)]} (section 1.3).
- **The recommendation is CONDITIONAL on 1D's SET current**: 20 F^2 passes only ~280 uA of ideal drive (1A). If 1D needs more, the fallback is 40 F^2: g* = {fg[(40, RS_REC, 0.10, PRIM_R, PRIM_SC)][0]} at sigma 0.10 instead of {g_rec[0.10]} (section 1.1).
- **What limits the design** (section 2): device spread at 5 sigma sets g for sigma >= 0.10 ({bm_counts[0.10].get('spread', 0)} of 24 cells at 0.10, {bm_counts[0.15].get('spread', 0)} at 0.15). For sigma <= 0.05 the far group takes over: its bitline is {far_ser_lo:.0f}-{far_ser_hi:.0f} ohm of series resistance, which compresses its step to ~{ua(far_delta, 0)} uA, and the comparator noise (the 'abs.signal' term) then binds ({bm_counts[0.03].get('abs.signal', 0)} of 24 cells at 0.03, {bm_counts[0.05].get('abs.signal', 0)} at 0.05). **The 1B-i claim that spread binds everywhere does not survive the wire**: tightening sigma below ~0.10 buys nothing at g = 8 unless the far-group compression is fixed (sense node in the column middle: g* 16, section 1.3). The row line caps a macro at 32 columns. sigma_lnG still sets g for sigma >= 0.10, and 1D's program-verify is the lever on it.

## 1. The final g surface

### 1.1 Surface over (R_s, cell area, sigma_lnG)

Largest g whose budget closes at BOTH extreme groups (near and far) with wire IR and drift included, and whose CMRR is achievable (60 dB [ASSUM]). Labels: spread = device spread, abs.signal = comparator noise, HRS leak, wire IR (within-group),
row IR (row-driver, weight dependent), ref cells, drift, CMRR, grid = still ok at the top of the evaluated grid.

{surf}

**Binding-term map** (cells of the 24 (area, R_s) whose next-larger g is limited by each term):

{tbl(['sigma_lnG', 'limiter'], bm)}

### 1.2 Sensitivity to the unmeasured wire and drift parameters (recommended cell)

{sens_tab}

### 1.3 Layout and front-end levers (how fragile is the final g?)

On the final budget at the recommended cell (S1, drift 'moderate', 0.72 ohm/pitch): what changes g*.

{lever_tab}

### 1.4 How much g moved from 1B-i

{mv_tab}

Over the whole grid (sigma 0.05-0.20, {n_cells} cells): {moved_tab}

(1B-i values in the first table are the provisional ones: wire IR and drift were not in the budget.)

## 2. What binds, and what the map says about where the design is limited

{tbl(['sigma_lnG', 'limiter'], bm)}

Reading the map: the limiter is **device spread** for every cell at sigma >= 0.10, which is the 1B-i result. Below that the limiter becomes the **absolute signal** (comparator noise against the far group's compressed step), because the far group sits behind
{far_ser_lo:.0f}-{far_ser_hi:.0f} ohm of bitline (0.5-0.72 ohm/pitch): that is exactly a larger sense resistor for that group, so its step is {ua(far_delta, 0)}-{ua(c0[8][0]['delta_far_a'], 0)} uA instead of {ua(c0[8][0]['delta_ideal_a'], 0)} uA at g = 8 (section 7.1/7.3), and the 5 uA (5 sigma) comparator term is a large share of its
{ua(0.5 * (1 - C.HEADROOM) * far_delta, 1)}-{ua(0.5 * (1 - C.HEADROOM) * c0[8][0]['delta_far_a'], 1)} uA limit. **Wire IR as the uncorrectable within-group term (near group) is not the limiter at the recommended point** - it appears as the limiter only when the far-group problem is removed (sense node in the middle: g* 16 limited by 'wire IR', section 1.3) or at larger g.
So the answer to "does spread still bind everywhere, or does wire take over somewhere" is: spread binds for sigma >= 0.10; at tighter sigma the wire takes over, first through the far group's compression (and the comparator), then through the within-group residual.
CMRR does not decide g* anywhere on this surface: the largest requirement over all {len([r for r in frows if r['cmrr_db'] == r['cmrr_db']])} Monte-Carlo-evaluated points is {max(r['cmrr_db'] for r in frows if r['cmrr_db'] == r['cmrr_db']):.1f} dB, below the 60 dB assumed achievable (and {max(r['cmrr_db'] for r in frows if r['cmrr_db'] == r['cmrr_db'] and r['g'] <= 8):.1f} dB for g <= 8).

## 3. Every term of the budget, measured

Final recommended point, worst group = **{row_rec['worst_group']}** ({A_REC} F^2, R_s {RS_REC:g}, g {G_FIN}, sigma 0.10, wire {PRIM_R:g} ohm/pitch, drift '{PRIM_SC}', strategy {st}). Delta = {ua(row_rec['delta_a'])} uA; budget limit (20% headroom) = {ua(row_rec['limit_a'])} uA;
total error = deterministic terms {ua(det, 2)} + random terms in quadrature {ua(rss, 2)} (5 sigma) = {ua(row_rec['total_a'], 2)} uA; remaining {ua(row_rec['margin_frac'] * row_rec['limit_a'], 2)} uA.

{term_tab}

Terms and how they combine are defined in `solver/budget.py` (1B-i report section 1): compression is NOT a term (it is inside Delta); transistor off-leakage is closed (1A: 77x-998x headroom at 125 C); correctable terms enter only through their residual.
Figure 3 (section 11) shows this stack; the 1B-i version (spread, comparator, HRS residual only) is `fig3_budget_stack.png`.

## 4. Part A - where spread takes over from leakage and compression

The 1B-i grid jumped from sigma = 0 (g* = 128) to 0.05 (g* = 32). Adding sigma = 0.01, 0.02, 0.03 (20 F^2, R_s 5):

{cx_tab}

**Device spread overtakes the HRS-leakage residual as the binding term between sigma = 0.02 and 0.03, where g* is 64.** Analytically, spread and leakage residual are equal at the sigma shown for each g (spread is linear in sigma: spread/sigma varies by < 1% from sigma 0.01 to 0.20):

{sx_tab}

Meaning for 1D (ideal array, no wire): tightening the write below ~2-3% spread buys nothing more - g saturates at 64-128 where HRS leakage, compression and CMRR take over; above 3% every halving of sigma quadruples g. **With bitline wire and drift included the plateau comes much earlier: g* is 8 for every sigma <= 0.10 (sections 1.1, 2)**, so the useful range of write tightening in the final design is sigma 0.20 -> 0.10 (g 4 -> 8), unless the layout lever in section 1.3 is adopted.

## 5. Comparator, ladder and CMRR

- **Ladder** (1B-i section 3, `results/margin_budget/comparator_ladder_recommended.csv`): thresholds on the actual compressed levels, sigma-weighted; one table per active count a; levels antisymmetric so half are stored. It is cheap for a binary readout because a threshold only needs its reference in the right place; an analog readout would need a runtime per-column multiply. The non-uniform ladder is NECESSARY above a g x R_s threshold: the uniform ladder mis-decides nominal levels outright at 34 of 192 sigma = 0 grid points (Figure 4) and is indistinguishable from it at the recommended small-g, small-R_s point.
- **Per-group ladder.** Because the far group's bitline is a series resistance, **every group needs its own ladder** (a per-group, per-(a, m) threshold table, section 7): groups differ in level scale by up to a factor {1 / _a4:.1f} (g = 4, farthest group) and {1 / _a16:.1f} (g = 16, farthest group).
- **CMRR (independent bound).** Required CMRR = 20 log10(I_cm / (10% x Delta)) at the worst group. At the recommended point it is {fidx[(A_REC, RS_REC, 0.10, PRIM_R, PRIM_SC)][max(G_FIN,1)]['cmrr_db']:.1f} dB at g = {G_FIN}; the far group's smaller Delta raises it. Achievable CMRR is {C.CMRR_ACHIEVABLE_DB:.0f} dB [ASSUM, textbook range 60-80 dB, not verified for this process].

{cm}

## 6. The current-mode readout conclusion

With a passive sense resistor the step swings Delta x R_s = {row_rec['delta_a'] * RS_REC * 1e3:.3f} mV at the recommended point (Delta {ua(row_rec['delta_a'])} uA, R_s {RS_REC:g} ohm), against an uncalibrated comparator offset of ~{C.COMP_OFFSET_V * 1e3:g} mV (1 sigma) [ASSUM]; 5 sigma is {C.N_SIGMA * C.COMP_OFFSET_V * 1e3:g} mV.
**Passive voltage sensing is not viable.** The readout must be current-mode / virtual-ground (a transimpedance or current-conveyor front end holding the column near 0 V), with input-referred current resolution of ~{C.COMP_SIGMA_I_A * 1e6:g} uA (1 sigma) or better [ASSUM, unsourced]. The "R_s" of the budget is then the effective input resistance of that front end (a few ohms).
Virtual ground also removes the sense-resistor compression, but it does not help the binding terms (spread; wire IR still adds series resistance in the bitline itself).

## 7. Wire resistance

### 7.1 First-order bound (C0), and the regime

Lumped linear estimate (20 F^2, R_s 5; bitline 0.5-0.72 ohm per cell pitch [ASSUM], pitch {C.PITCH_UM[20]:.3f} um at 20 F^2; no mesh):

{c0_tab}

- **(a) between groups:** the far group sits behind 224-366 ohm of bitline. That is the same as a larger sense resistor for that group: a per-group ladder removes the LEVEL shift, but the compression it causes shrinks the step (g = 16: {ua(c0[16][0]['delta_ideal_a'])} -> {ua(c0[16][1]['delta_far_a'])}-{ua(c0[16][0]['delta_far_a'])} uA).
- **(b) within a group:** half the pattern range, which no constant can remove. At g = 16 it is {ua(c0[16][0]['within_halfrange_far_a'], 1)}-{ua(c0[16][1]['within_halfrange_far_a'], 1)} uA against the 2.8 uA that 1B-i left, i.e. **well over: the regime in which g = 8 is already the answer** (g = 8: {ua(c0[8][0]['within_halfrange_far_a'], 1)}-{ua(c0[8][1]['within_halfrange_far_a'], 1)} uA).
  The mesh below confirms this and finds the layout rule; it also shows the first-order estimate is the NEAR-group value (full currents).

### 7.2 The mesh solver and its validation (C1)

`wire/mesh.py`: 2-D mesh (row lines with driver, bitlines with the sense node, sinh cells with the linear R_tx), sparse-LU Newton. Validated against ngspice before use:

{mesh_md}

### 7.3 Decomposition (C2): between-group, within-group, and the contiguity evidence

One 2T2R pair, nominal gaps (spread is a separate term), {C.WIRE_PATTERNS_PER_CELL} random activation patterns per (group, a, m) split 50/50 into fit and held-out, plus the near-packed and far-packed extremes. 'Per-group table' = the ladder's level for each (a, m) set to the
fit mean; 'minimax' = set to the middle of the fit-plus-extremes range (the best constant for the worst case).

{decomp_tab}

Group by group ({'contiguous'}, g = 16, 0.72 ohm/pitch):

{groups_tab}

- **Between groups:** the level shift (`level shift removed by the per-group table`) is up to ~700 uA at g = 16 and is removed by the per-group table to the within-group residual: it is a constant per group, compile-time correctable. What it leaves behind is the compression (Delta_G falls from {ua(json.loads(RP.decomposition_json('contiguous', 16, 0.72).read_text())['groups'][0]['delta_group_a'])} to {ua(json.loads(RP.decomposition_json('contiguous', 16, 0.72).read_text())['groups'][-1]['delta_group_a'])} uA), which enters the budget through Delta of the far group.
- **Within a group:** the residual is bounded by the group's span and grows ~g^3 (up to g = 16): contiguous layout keeps it to 0.1-0.2 uA (g = 4), 1.2-1.8 (g = 8), 9-13 (g = 16). **Only this term enters the budget** (as a deterministic worst-case, because it is activation dependent).
- **Contiguity rule evidence:** interleaving the same groups across the column costs 15x (g = 16) to 100x (g = 4) more within-group error (Figure 5). The rule is not an assertion: rows of one group must be physically adjacent.
- **The near group is the worst for the within-group term** (largest currents), **the far group for the step** (compression); both are monotone in distance, so the budget is closed at both extremes (checked on 5 probed groups).

### 7.4 The held-out test (C3)

The correction is fitted on half the random patterns and tested on the other half. Fit and held-out residuals agree (e.g. g = 16: table fit max {ua(json.loads(RP.decomposition_json('contiguous', 16, 0.5).read_text())['summary']['table_fit']['max'], 2)} uA vs held-out
{ua(json.loads(RP.decomposition_json('contiguous', 16, 0.5).read_text())['summary']['table_held']['max'], 2)} uA; g = 32: 38.7 vs 39.4 uA): the per-group table is not over-fitted, and **the residual after it is genuinely activation dependent** - it is what is left, not a fit artefact.
The extremal patterns (all matches packed at one end) exceed the random-pattern residual by 1.3x (g = 16), 1.7x (g = 32) and 2.3x (g = 64), and are comparable at g <= 8, which is why the budget term uses the worst case rather than a random-pattern statistic.
A single per-group SCALAR gain, the analogue of the related work's per-column scalar correction, leaves 6-18% of the rms wire error and a held-out maximum of 16 uA (g = 4) to 166 uA (g = 32): far too much; a per-(a, m) table is required.
(The related work's 49% surviving residual is for a 128-row array and a different metric; here the table removes ~99.9% of the raw error, but the remaining 0.1% is the whole budget at g >= 16.)

### 7.5 Row line and driver across K columns

The row line carries the current of every cell on the row, so a row's droop depends on the OTHER columns' weights. Measured for the pair at the row's far end of a K-column line (g contiguous, 0.72 ohm/pitch for the row line):

{row_tab}

- The **gain error** is a per-column-position constant (correctable by a per-column ladder scale, but it multiplies Delta): at K = 32 with a 10 ohm driver it is 4-9% for the far group (table) and 17% for the near group (`results/wire_resistance/wire_terms_per_point.json`).
- At **K = 160 on one row line** the middle and far columns lose 48-69% of their signal (10 ohm driver): not viable. **A 160-column array must be five 32-column macros, each with its own row drivers** - which is NeuroHDC's own organisation.
- A 100 ohm driver costs 25-35% gain even at K = 32; **R_DRV <= 10 ohm is a requirement.**
- The uncorrectable part (spread across other columns' weights) is 0.15-0.4 uA (1 sigma) at K = 32, 10 ohm; it enters the budget as a random term (5 sigma).

## 8. Drift

Model: G_i(t) = G_i(t0) (t/t0)^(-nu_i), nu_i ~ N(nu, (kappa nu)^2); t0 = {C.DRIFT_T0_S / 3600:g} h [CHOICE, the first read after program-verify; sigma_lnG is the spread at t0]; every drift number is **[ASSUM] and swept** (nu 0-0.03, kappa 0.25/0.5, life 1 and 10 y).
g* versus drift rate at the recommended cell (no wire; sigma, nu, strategy):

{drift_g_tab}

(S1: ladder fixed at the geometric-mean age, mean drift becomes a level shift; S2: all cells reprogrammed every interval; S3: n reference cells re-derive the ladder scale; 'abs' = references compared with the spec value, so they bring their own t0 spread; 'ratio' = each reference cell's t0 reading is stored.)

### 8.1 The reference-cell trade (strategy 3), both sides

sigma 0.10, nu 0.01, kappa 0.25, 10 y, recommended cell (no wire):

{trade_tab}

- **What it cancels:** essentially all of the common-mode drift shift ({ua(trade_raw[0]['drift_shift_a'])} uA at g = 8 for headroom, ~0.1 uA with references).
- **What it adds:** the references' own spread, a random term proportional to the group's current scale: with 128 'abs' references {ua(trade_raw[3]['ref_a'])} uA at g = 8 even with NO drift (the cost is paid every day, not only when drift happens), and {ua([r for r in trade_raw if r['g'] == 16 and 'S3 128 refs, abs' == r['strategy']][0]['ref_a'])} uA at g = 16 - more than the drift it removes there.
- **Net:** at g = 8 it wins (budget left {[r for r in trade_raw if r['g'] == 8 and r['strategy'] == 'S3 128 refs, abs'][0]['margin'] * 100:.0f}% vs {[r for r in trade_raw if r['g'] == 8 and r['strategy'] == 'S1 headroom'][0]['margin'] * 100:.0f}% for headroom at nu = 0.01); at g = 16 nothing closes. The clever option wins only when drift is large AND g is small; with no drift it LOSES a little
  (budget left {[r for r in trade_raw if r['g'] == 8 and r['strategy'] == 'S3 128 refs, abs'][0]['margin_nodrift'] * 100:.0f}% vs {[r for r in trade_raw if r['g'] == 8 and r['strategy'] == 'S1 headroom'][0]['margin_nodrift'] * 100:.0f}%). 'ratio' references (stored t0 readings) are cheap in error but add a per-device calibration step. Overhead: {C.REF_CELLS_SWEEP[2]} references shared across a 512-row column is {C.REF_CELLS_SWEEP[2] / C.ROWS_TOTAL * 100:.0f}% extra rows; a per-group set is impossible (more references than rows at g = 8).

### 8.2 Refresh (strategy 2): interval versus drift rate, and cost

{refresh_tab}

One refresh reprograms {n_dev:,} devices ({C.ROWS_TOTAL} x {C.FULL_COLS} x 2) at {C.WRITE_RETRIES:g} pulses each x {C.WRITE_ENERGY_PJ:g} pJ [ASSUM, both] = **{e_ref_uj:.1f} uJ** per refresh (programming time is for 1D to measure).

### 8.3 The strategies on the FINAL budget (wire and row terms included)

{strat_final_tab}

### 8.4 Choice

Baseline strategy: **{st} (headroom)**. On the final budget (table 8.3) it holds g = {G_FIN} at sigma 0.10 for drift up to 'moderate' (nu = {C.DRIFT_SCENARIOS['moderate'][0]:g}) without any extra hardware or cycles. At 'strong' drift (nu = {C.DRIFT_SCENARIOS['strong'][0]:g}) headroom alone drops to g = {strat_final[('S1 headroom', 'strong', 0.10)]};
a quarterly refresh (S2, 90 days) or reference cells restore g = {strat_final[('S2 refresh 90 d', 'strong', 0.10)]}. **Recommendation: design for headroom, and require 1D to provide a reprogram service at ~90-day intervals if the measured nu is >= ~0.01.**
Cost of that service: {e_ref_uj:.1f} uJ per refresh [ASSUM], ~{C.DRIFT_LIFE_YEARS[-1] * 365.25 / 90:.0f} refreshes in 10 y = {C.DRIFT_LIFE_YEARS[-1] * 365.25 / 90 * e_ref_uj / 1000:.2f} mJ and {C.DRIFT_LIFE_YEARS[-1] * 365.25 / 90:.0f} of {C.ENDURANCE_CYCLES:.0e} endurance cycles [ASSUM]; programming time is for 1D to measure.
Reference cells are not recommended: they add a permanent random error (section 8.1) that costs a grid step at g = 16 and gains only at large drift; 'ratio' references avoid most of the error but need a stored t0 reading of every reference cell.

## 9. 1D handoff numbers (also section 12)

{sig_buy}

On/off ratio the program-verify loop must hold ({A_REC} F^2, R_s 10, leakage residual <= {C.LEAK_BUDGET_SHARE * 100:.0f}% of the usable margin):

{win_tab}

## 10. Cycle counts

{cyc_tab}

## 11. Figures

{chr(10).join(fig_md)}

(The 1B-i version of Figure 3, without wire and drift, is `results/figures/fig3_budget_stack.png`: {fig3_1bi[:160]}...)

## 12. Handoffs

### Handoff to 1C (array scale-up)
- **Group size g = {G_FIN}**, cell {A_REC} F^2 (2T2R {2 * A_REC} F^2), row/column pitch {C.PITCH_UM[A_REC]:.3f} um; {C.ROWS_TOTAL // G_FIN} groups per 512-row column.
- **Contiguity is mandatory**: the {G_FIN} rows of a group must be physically adjacent (evidence: section 7.3, Figure 5; interleaving costs 15x at g = 16).
- **Per-group ladder**: one threshold table per group, indexed by the active count a and the match count: groups differ in level scale by up to {1 / _a8:.1f}x at g = 8 and the far group's step is {c0[8][0]['delta_near_a'] / c0[8][0]['delta_far_a']:.1f}-{c0[8][0]['delta_near_a'] / c0[8][1]['delta_far_a']:.1f}x smaller than the near group's ({c0[8][0]['delta_near_a'] * 1e6:.0f} -> {c0[8][1]['delta_far_a'] * 1e6:.0f}-{c0[8][0]['delta_far_a'] * 1e6:.0f} uA at g = 8, 0.72-0.5 ohm/pitch).
  The table is compile-time (weights and geometry known); levels are antisymmetric so half is stored.
- **Sense**: current-mode / virtual-ground, not a passive sense resistor (section 6). Placing the sense node in the middle of the column halves the farthest distance; on the final budget it raises g* from 8 to {lever_res[('sense node in the column middle', 0.05)]} at sigma <= 0.05 (limited then by the within-group wire term) and does nothing at sigma 0.10 (section 1.3) - **1C should evaluate a centre-tapped or segmented column**.
- **Row lines**: at most 32 columns per row line and R_DRV <= 10 ohm (section 7.5); the 160 columns are five macros with their own drivers.
- **Open question 1B cannot settle:** do all 160 columns sense simultaneously (**{cy[2]:,} reads/timestep = 11 x 512/g**) or one bit-plane at a time (**{cy[1]:,} reads/timestep = 88 x 512/g**)? That is an 8x cycle difference and turns on multi-column supply droop and crosstalk, which appear only at 1C's 32-column macro.

### Handoff to 1E (RTL)
- **ROWS_PER_GROUP = {G_FIN}**; groups per column {C.ROWS_TOTAL // G_FIN}.
- Reads per timestep **{cy[1]:,}** (88 x 512/g) or **{cy[2]:,}** (11 x 512/g); per inference (x{C.TIMESTEPS}) **{cy[1] * C.TIMESTEPS:,}** or **{cy[2] * C.TIMESTEPS:,}**, before bit-row skipping. The RTL must stay bit-exact for every g (1E's g sweep); the circuit result decides only which g the performance model uses.
- The per-group ladder is not RTL (it is analog); the digital side needs only the group count and the per-group popcount `a` it already computes.

### Handoff to 1D (write path)
- **On/off ratio to hold**, per g: the table in section 9 (ladder designed at the 403 ceiling: the achieved ratio must stay above the first column; at g = {G_FIN}: {win[(A_REC, G_FIN, 403.4)]['r_lo']:.0f}).
- **sigma_lnG sets g only above ~0.10, and verify is the lever on it there.** At the recommended cell g* is 8 for every sigma <= 0.10 (the far group's wire-compressed step and the comparator then bind), so tightening the write below ~0.10 buys nothing unless the layout lever of section 1.3 is adopted (centre-tapped column: g* 16 at sigma <= 0.05); above 0.10 each step costs a grid step (0.15 and 0.20: g* 4). What each achievable sigma buys:

{sig_buy}

- **SET current - the recommendation is conditional on it.** 20 F^2 passes ~280 uA of ideal drive (1A). If 1D needs more, the fallback is 40 F^2 at roughly half the g for the same sigma (final surface: g* = {fg[(40, RS_REC, 0.10, PRIM_R, PRIM_SC)][0]} at sigma 0.10, {fg[(40, RS_REC, 0.05, PRIM_R, PRIM_SC)][0]} at 0.05).
- Program-verify target gaps are the nominal gaps (0.2 / 1.7 nm); the verify window sets sigma_lnG and the ratio window above.
- Refresh (if drift needs it) is a 1D service: {e_ref_uj:.1f} uJ per refresh at the assumed pulse energy and retries; endurance is not binding (section 8.2).
- **Compact model**: `rram.va` is still uncompiled (OpenVAF not installed); 1D needs it first.

## 13. Which findings are paper results

{PAPER}

## 14. TO BE DETERMINED

- **sigma_lnG** [ASSUM, swept]: still the quantity that sets g; needs measured device data.
- **Drift exponent nu and spread kappa** [ASSUM, swept]; the power-law form itself is assumed.
- **Bitline/row resistance per cell pitch (0.5-0.72 ohm) and R_DRV (10 ohm)** [ASSUM]: the source pitch of the related work is unknown; sensitivity is in section 1.2.
- **Comparator input noise (1 uA) and CMRR (60 dB)** [ASSUM, unsourced / textbook].
- **Write energy (10 pJ) and verify retries (3)** [ASSUM]: only the refresh cost depends on them.
- **ReRAM read-current temperature coefficient**: still a limitation of the compact model.
- **SET current** (1D) and the compact-model compilation (OpenVAF).
- **Whether the 160 columns sense simultaneously** (1C).
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(md)
    print("wrote", OUT)


PAPER = """Each candidate assessed against the evidence in this report; "survives" means it holds up as a paper result, with the stated qualification.

| finding | verdict | why |
|---|---|---|
| **Device spread binds, via sqrt(g), giving g* ~ sigma^-2 and a leakage-to-spread crossover at sigma ~ 2-3%** | **Survives for sigma >= 0.10; superseded below it** | The mechanism (errors of g independent cells add as sqrt(g) against a fixed step) is textbook. The measured law for the ideal 512-row binary 2T2R array (g* 32/16/8/4 for sigma 0.05-0.20) holds, and compression is NOT binding. But with the bitline wire the far group's compressed step and the comparator noise cap g at 8 for sigma <= 0.10, so 'spread binds everywhere' is NOT a final result. Contingent on sigma [ASSUM]; the Gaussian 5-sigma estimate is optimistic at g <= 4. |
| **Ballast: the access transistor divides conductance spread, so smaller cells are better** | **Survives, as a design rule with a floor** | Verified by Monte Carlo and by the closed form spread/Delta ~ (5 sigma sqrt(g)/2) x R_LRS/(R_LRS+R_tx). It is series current regulation (classical) and its use is bounded below by the SET-current floor on cell area, so it is a condition on the recommendation rather than a headline claim. |
| **Differential read is less compressed, worst case in the middle** | **Weaker than it looked: supporting observation** | Robust in the solver and mesh (Figure 6), but it holds only for the MINIMUM over m (1.5-1.9x at g = 32-64); below m/g ~ 0.5 the single column is the less compressed. The far group's wire compression (a factor 3-5 in Delta) is much larger than this effect, so on its own it does not decide a design. |
| **Non-uniform ladder necessary above a g x R_s threshold** | **Survives, in a stronger form** | At the recommended near group (small g, R_s 5) the uniform ladder works equally well; but wire resistance makes the far group behave as R_s ~ 250-370 ohm, which crosses the threshold even at g = 8 (uniform margin factor 0.70 vs 2.48; at g = 16 -4.6 vs 0.79, i.e. the uniform ladder mis-decides nominal levels). The necessity is therefore a consequence of the wire, not of the sense resistor. |
| **Contiguous grouping (between-group constant vs within-group g^3)** | **Survives** | Quantified on a validated mesh (worst disagreement with ngspice 4.8e-11): contiguity cuts the uncorrectable error 15x at g = 16 and 100x at g = 4; the per-group table removes ~99.9% of the raw error and generalises to held-out patterns. The layout rule itself is standard practice; the contribution is the split, its scaling and the evidence. |
| **Write tightness buys read speed** | **Weaker than hoped: holds only over a narrow range** | For the ideal array every halving of sigma above ~3% quadruples g; in the final design the benefit stops at sigma ~ 0.10 (g = 8) because the far group's wire-compressed step and the comparator noise take over, unless the column is centre-tapped (g* 16, section 1.3). It depends on the unmeasured sigma, and 'program-verify is the only lever' ignores the ballast and layout levers. |

Additional results worth a paper section: (i) a far group's bitline series resistance is equivalent to a larger sense resistor for that group (mesh vs lumped: 23.7 vs 24.0 uA step at g = 16), which is what makes a per-group ladder sufficient for the level shift while the compression stays in the budget;
(ii) 160 columns on one row line are infeasible (middle and far columns lose 48-69% of their signal), so the NeuroHDC macro structure is required, with R_DRV <= 10 ohm; (iii) an honest negative result: reference-cell drift compensation costs a permanent random error that exceeds the drift it cancels above g ~ 8, so headroom or refresh wins unless drift is large."""

if __name__ == "__main__":
    main()
