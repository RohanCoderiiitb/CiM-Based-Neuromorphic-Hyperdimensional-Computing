"""Paper figures for 1B. Each writes <name>.{pdf,svg,png}, <name>.csv, and its caption goes into captions.md.

Usage: python -m margin.figures [fig1 fig2 fig3 fig4 fig5 fig6]   (default: all that have their data)
"""
from __future__ import annotations

import paths as RP

import json
import sys
from pathlib import Path

import numpy as np

import device.constants as C
from margin import figstyle as FS
from margin import surface as S
from margin.core import params_for
from validate import analysis as A

REC_AREA, REC_RS, REC_G, REC_SIGMA = 20, 5.0, 16, 0.10
CAPS = FS.OUT / "captions.json"


def _caption(key: str, text: str) -> None:
    FS.OUT.mkdir(parents=True, exist_ok=True)
    d = json.loads(CAPS.read_text()) if CAPS.exists() else {}
    d[key] = text
    CAPS.write_text(json.dumps(d, indent=1))


def _idx():
    rows = S.load()
    return rows, S.index(rows)


def fig1() -> None:
    rows, idx = _idx()
    sigmas = [s for s in sorted({r["sigma"] for r in rows}) if s > 0]
    f, ax = FS.fig(2.7)
    out = []
    gtab = {k: S.g_star(v) for k, v in idx.items()}
    for i, area in enumerate(C.AREA_SWEEP_F2):
        st = FS.SERIES[i]
        xs, ys, cap = [], [], []
        for sg in sigmas:
            g, lim, _ = gtab[(area, REC_RS, sg)]
            xs.append(sg); ys.append(max(g, 0.5)); cap.append(lim == "grid-limited")
            out.append([area, sg, g, lim])
        ax.plot(xs, ys, label=f"{area} F$^2$", color=st["color"], marker=st["marker"], ls=st["ls"])
        for x, y, c in zip(xs, ys, cap):
            if c:
                ax.annotate("", xy=(x, y * 1.5), xytext=(x, y), arrowprops=dict(arrowstyle="->", color=st["color"], lw=0.7))
    xx = np.array([0.03, 0.2]); ax.plot(xx, 64 * (0.03 / xx) ** 2 * 1.0, color="0.45", lw=0.7, ls=(0, (1, 1)))
    ax.text(0.115, 14, "slope $-2$\n($g^{*}\\propto\\sigma^{-2}$)", fontsize=5.8, color="0.3", rotation=-34)
    gr = gtab[(REC_AREA, REC_RS, REC_SIGMA)][0]          # ideal array (1B-i): the provisional g
    fin = RP.final_points_csv("S1")
    gfin = None
    if fin.exists():
        from margin.report_1b_parts import gstar_final, index_final, load_final
        fidx = index_final(load_final(fin))
        fx = [0.03, 0.05, 0.10, 0.15, 0.20]
        fy = [gstar_final(fidx[(REC_AREA, REC_RS, sg, 0.72, "moderate")])[0] for sg in fx]
        ax.plot(fx, fy, color="black", lw=1.5, marker="X", ms=4.5, ls="-", label=f"{REC_AREA} F$^2$ final (wire + drift)", zorder=4)
        out += [["final_wire_drift", sg, g_, ""] for sg, g_ in zip(fx, fy)]
        gfin = fy[fx.index(REC_SIGMA)]
    ax.plot([REC_SIGMA], [gfin if gfin else gr], marker="*", ms=11, mfc="none", mec="black", mew=1.0, ls="none", zorder=5, label="recommended (final)")
    lo, hi = gtab[(REC_AREA, REC_RS, 0.20)][0], gtab[(REC_AREA, REC_RS, 0.05)][0]
    ax.annotate("", xy=(0.235, hi), xytext=(0.235, lo), arrowprops=dict(arrowstyle="<->", lw=0.6))
    ax.text(0.26, np.sqrt(lo * hi), f"{hi // lo}$\\times$\n(ideal\narray)", va="center", fontsize=6)
    ax.axvspan(0.05, 0.20, color="0.92", zorder=0); ax.text(0.088, 1.15, "assumed typical\nspread (5-20%)", fontsize=5.6, ha="center", color="0.3")
    ax.set_xscale("log"); ax.set_yscale("log", base=2); ax.set_xlim(0.0085, 0.33)
    ax.set_xticks([0.01, 0.02, 0.05, 0.1, 0.2]); ax.set_xticklabels(["0.01", "0.02", "0.05", "0.1", "0.2"])
    ax.set_yticks([1, 2, 4, 8, 16, 32, 64, 128]); ax.set_yticklabels(["1", "2", "4", "8", "16", "32", "64", "128"]); ax.set_ylim(0.38, 220)
    ax.set_xlabel(r"conductance spread $\sigma_{\ln G}$ (log-normal, dimensionless)")
    ax.set_ylabel("largest group size $g^{*}$ (rows)")
    ax.legend(title=f"1T1R cell area ($R_s$ = {REC_RS:g} $\\Omega$)", loc="lower left", ncol=2, title_fontsize=6.0, bbox_to_anchor=(0.0, 0.0), fontsize=5.3, columnspacing=0.8, handlelength=2.0)
    FS.write_csv("fig1_gstar_vs_sigma", ["cell_area_F2", "sigma_lnG", "g_star", "limiter_of_next_g"], out)
    FS.save(f, "fig1_gstar_vs_sigma")
    _caption("fig1", (f"Largest group size g* whose error budget closes versus the log-normal conductance spread sigma_lnG (log-log axes), for four 1T1R cell areas at a sense resistance of {REC_RS:g} ohm "
                      f"(5-sigma random error, 20% headroom, comparator and HRS-leakage terms included). Arrows mark points still closing at the top of the grid (g = 128; lower bounds). "
                      f"Above about 3% spread g* falls as sigma^-2, the straight dotted slope, because the error of a sum of g cells grows as sqrt(g); across the assumed 5-20% range the ideal-array g* drops {hi // lo}x (so the number of reads per timestep rises {hi // lo}x), while the final design's drops only 2x (8 to 4). "
                      f"Below about 2% spread g* of the ideal array stops improving: HRS leakage, compression and comparator limits take over. Smaller cells sit higher at every sigma: the access transistor, larger at small area, acts as a series ballast that divides the cell's conductance spread. "
                      f"The black line is the FINAL g* for the 20 F^2 cell once bitline wire resistance (0.72 ohm per pitch, far group behind ~360 ohm), row-driver IR and moderate drift are added: it is capped at 8 by the far group's compressed step and the comparator noise, so the leakage-limited plateau of the ideal array does not survive. "
                      f"The star marks the final recommended operating point (20 F^2, sigma 0.10, g = {gfin}); the ideal-array value there was {gr}. The 60 and 100 F^2 curves coincide. Points within 5% of the budget limit are sensitive to Monte-Carlo noise, and g moves on a factor-2 grid."))


def fig2() -> None:
    rows, idx = _idx()
    sigmas = [0.02, 0.05, 0.10, 0.15, 0.20]
    gs = list(C.G_SWEEP)
    f, ax = FS.fig(2.6)
    out = []
    lim = [idx[(REC_AREA, REC_RS, 0.05)][g]["limit_a"] for g in gs]
    for i, sg in enumerate(sigmas):
        st = FS.SERIES[i % len(FS.SERIES)]
        y = [idx[(REC_AREA, REC_RS, sg)][g]["spread5_a"] * 1e6 for g in gs]
        ax.plot(gs, y, color=st["color"], marker=st["marker"], ls=st["ls"], label=f"{sg:g}")
        out += [[sg, g, yy, l * 1e6] for g, yy, l in zip(gs, y, lim)]
    ax.plot(gs, np.array(lim) * 1e6, color="black", lw=1.6, ls="-", label="budget limit", zorder=1)
    ax.set_xscale("log", base=2); ax.set_yscale("log")
    ax.set_xticks(gs); ax.set_xticklabels([str(g) for g in gs])
    ax.set_xlabel("active rows per group $g$"); ax.set_ylabel("5$\\sigma$ spread error of $I_{diff}$ ($\\mu$A)")
    ax.legend(title="$\\sigma_{\\ln G}$", ncol=2, loc="lower right", title_fontsize=6.2)
    FS.write_csv("fig2_spread_vs_g", ["sigma_lnG", "g", "spread_5sigma_uA", "budget_limit_uA"], out)
    FS.save(f, "fig2_spread_vs_g")
    _caption("fig2", (f"Five-sigma device-spread error of the differential column current versus group size g, one line per conductance spread sigma_lnG ({REC_AREA} F^2 cell, R_s = {REC_RS:g} ohm), "
                      "against the usable error budget (thick line: half the worst differential step, less 20% headroom). Independent cell errors add as sqrt(g), so every line rises with slope 1/2 on these log axes "
                      "while the budget stays nearly flat; each line's crossing of the budget is the largest group size that can be read exactly. This crossing, not sense-resistor compression, sets g."))


def _terms_at_rec(extra: dict | None = None) -> list:
    rows, idx = _idx()
    r = idx[(REC_AREA, REC_RS, REC_SIGMA)][REC_G]
    return r


def _fig3_draw(terms: list, delta: float, name: str, caption_key: str, tag: str, title_pt: str) -> None:
    """Stacked budget bar. terms: [(label, 'random'|'det', value_a)]. Random terms combine in quadrature, so their segments are the RSS split in proportion to
    squares; deterministic terms stack linearly."""
    rss = float(np.sqrt(sum(v * v for _, k, v in terms if k == "random")))
    seg = [(lab, (v * v / rss ** 2 * rss) if kind == "random" and rss > 0 else v) for lab, kind, v in terms]
    total = sum(v for _, v in seg)
    half = 0.5 * delta
    limit = half * (1 - C.HEADROOM)
    seg += [("remaining", max(limit - total, 0.0)), ("headroom (model-error reserve)", half - limit)]
    f, ax = FS.fig(3.5)
    cmap = {"device spread": (FS.OI["blue"], None), "comparator noise": (FS.OI["orange"], None), "HRS leakage residual": (FS.OI["green"], ".."),
            "wire IR (within group)": (FS.OI["purple"], "xx"), "row-driver IR": (FS.OI["sky"], "\\\\"), "drift": (FS.OI["yellow"], "oo"),
            "reference-cell spread": (FS.OI["verm"], "++"), "remaining": ("white", None), "headroom (model-error reserve)": ("#CCCCCC", "//")}
    bottom, out = 0.0, []
    for lab, v in seg:
        ax.bar([0], [v * 1e6], bottom=bottom * 1e6, color=cmap[lab][0], edgecolor="black", lw=0.5, hatch=cmap[lab][1], label=f"{lab}: {v * 1e6:.1f} $\\mu$A", width=0.7)
        out.append([lab, v * 1e6, bottom * 1e6])
        bottom += v
    ax.axhline(limit * 1e6, color="black", ls="--", lw=0.8); ax.axhline(half * 1e6, color="black", ls=":", lw=0.6)
    ax.text(0.42, limit * 1e6, "budget limit", va="bottom", ha="left", fontsize=6)
    ax.text(0.42, half * 1e6, "half of the worst step", va="bottom", ha="left", fontsize=6)
    ax.set_xlim(-0.6, 1.5); ax.set_xticks([]); ax.set_ylabel("error current ($\\mu$A)"); ax.set_ylim(0, half * 1e6 * 1.12)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.04), ncol=1, fontsize=6)
    ax.grid(axis="x", visible=False)
    FS.write_csv(name, ["segment", "value_uA", "bottom_uA"], out)
    FS.save(f, name)
    _caption(caption_key, (f"Error budget at {title_pt}; contents: {tag}. The full bar is half the worst differential step ({half * 1e6:.1f} uA). Random terms combine in quadrature, so their segments are the "
                           "root-sum-square split in proportion to squared size; deterministic residuals stack linearly. The dashed line is the 20%-headroom limit; the grey top segment is the model-error reserve and the "
                           "white segment is what remains. The largest segment is the term that dominates the budget."))


def fig3() -> None:
    """1B-i version: spread, comparator, HRS residual only (regenerated with wire IR and drift as fig3_final in Part E)."""
    r = _terms_at_rec()
    _fig3_draw([("device spread", "random", r["spread5_a"]), ("comparator noise", "random", r["comp5_a"]), ("HRS leakage residual", "det", r["leak_resid_a"])], r["delta_a"],
               "fig3_budget_stack", "fig3_budget_stack", "1B-i terms only (spread, comparator noise, HRS residual)",
               f"the 1B-i recommended operating point ({REC_AREA} F^2 cell, R_s = {REC_RS:g} ohm, g = {REC_G}, sigma_lnG = {REC_SIGMA})")


def fig3_final(row: dict, tag: str, title_pt: str) -> None:
    """Part E: the final-surface point (worst group) with wire IR, row-driver IR and drift/reference terms. row: a final_points CSV row (dict)."""
    names = [("t_device spread", "device spread", "random"), ("t_absolute signal (comparator noise)", "comparator noise", "random"),
             ("t_ReRAM HRS leakage residual", "HRS leakage residual", "det"), ("t_wire IR (within group)", "wire IR (within group)", "det"),
             ("t_row-driver IR", "row-driver IR", "random"), ("t_reference-cell spread", "reference-cell spread", "random"), ("t_drift", "drift", "det")]
    terms = [(lab, kind, row[k]) for k, lab, kind in names if k in row and row[k] == row[k] and row[k] > 0]
    _fig3_draw(terms, row["delta_a"], "fig3_budget_stack_final", "fig3_budget_stack_final", tag, title_pt)


def fig4() -> None:
    rows, idx = _idx()
    g = 64
    f, ax = FS.fig(2.6)
    out = []
    for i, area in enumerate(C.AREA_SWEEP_F2):
        st = FS.SERIES[i]
        rs = list(C.R_S_SWEEP)
        nu = [idx[(area, r, 0.0)][g]["mu_nonuniform_min"] for r in rs]
        un = [idx[(area, r, 0.0)][g]["mu_uniform_min"] for r in rs]
        ax.plot(rs, nu, color=st["color"], marker=st["marker"], ls="-", label=f"{area} F$^2$ non-uniform")
        ax.plot(rs, un, color=st["color"], marker=st["marker"], ls="--", mfc="white", label=f"{area} F$^2$ uniform")
        out += [[area, r, a, b] for r, a, b in zip(rs, nu, un)]
    ax.axhspan(-60, 0, color="#DDDDDD", zorder=0); ax.axhline(0, color="black", lw=0.9)
    ax.axhline(1, color="black", lw=0.5, ls=":")
    ax.text(1.05, -4, "uniform ladder mis-decides\nnominal levels", fontsize=6, va="top")
    ax.set_xscale("log"); ax.set_xticks(list(C.R_S_SWEEP)); ax.set_xticklabels([f"{r:g}" for r in C.R_S_SWEEP])
    ax.set_ylim(-58, 22); ax.set_xlabel("sense resistance $R_s$ ($\\Omega$)")
    ax.set_ylabel("minimum per-count margin factor $\\mu$")
    ax.legend(ncol=2, loc="lower left", bbox_to_anchor=(0.0, 0.0), fontsize=5.2, handlelength=2.6)
    FS.write_csv("fig4_ladder_margin", ["cell_area_F2", "R_s_ohm", "mu_nonuniform_min", "mu_uniform_min"], out)
    FS.save(f, "fig4_ladder_margin")
    _caption("fig4", (f"Smallest per-count decision-margin factor mu (mu > 1: every count from 0 to g is decided at 5 sigma, including headroom, comparator noise and the HRS-leakage residual) versus sense resistance for g = {g} rows, "
                      "one colour per cell area. Solid lines: reference ladder with thresholds placed on the actual compressed levels; dashed lines with open markers: thresholds equally spaced between the end levels. "
                      "In the grey region mu < 0: a nominal (error-free) level already lies beyond a uniform threshold, so the uniform ladder mis-decides outright. The differential level curve is S-shaped, so the uniform ladder fails once g x R_s is large "
                      "while the non-uniform ladder stays positive; at small g and small R_s the two are indistinguishable."))


def fig6() -> None:
    f, ax = FS.fig(2.6)
    out = []
    p = C.DEFAULT
    for i, g in enumerate((32, 64)):
        c = A.level_curves(g, p)
        x = (np.arange(1, g + 1) - 0.5) / g
        st = FS.SERIES[i]
        ax.plot(x, c["gap_diff"], color=st["color"], marker=st["marker"], ls="-", markevery=max(g // 8, 1), label=f"differential, g = {g}")
        ax.plot(x, c["gap_single"], color=st["color"], marker=st["marker"], ls="--", mfc="white", markevery=max(g // 8, 1), label=f"single column, g = {g}")
        out += [[g, xx, a, b] for xx, a, b in zip(x, c["gap_diff"], c["gap_single"])]
    for i, g in enumerate((32, 64)):
        c = A.level_curves(g, p)
        kd, ks = int(np.argmin(c["gap_diff"])), int(np.argmin(c["gap_single"]))
        ax.text((kd + 0.5) / g, c["gap_diff"][kd] - 0.075, f"min {c['gap_diff'][kd]:.2f}", fontsize=5.6, ha="center", color=FS.SERIES[i]["color"])
    ax.set_xlabel("match fraction $m/g$"); ax.set_ylabel("level step / uncompressed step")
    ax.set_ylim(0, 1.02); ax.legend(loc="upper right", fontsize=5.6)
    FS.write_csv("fig6_diff_vs_single_gap", ["g", "m_over_g", "differential_gap", "single_column_gap"], out)
    FS.save(f, "fig6_diff_vs_single_gap")
    _caption("fig6", (f"Step between adjacent count levels, normalised to the step with no sense resistor, versus match fraction m/g, for a 40 F^2 cell (R_tx = {p.r_tx:g} ohm) and R_s = {p.r_s:g} ohm. "
                      "A single column (dashed, open markers) loses most of its step at high counts because its current compresses against the sense resistor. The two-device (differential) read (solid) is less compressed, "
                      "because when the + column is heavily loaded the - column is nearly empty, so the compression partly cancels; its worst case is therefore in the middle (m = g/2), not at m = g. "
                      "Note that below m/g of about 0.5 the single column is the less compressed one (its step is larger relative to its own uncompressed step); the comparison that matters for a threshold readout is the minimum over m, where the differential read is 1.5x better at g = 32 and 1.9x at g = 64."))


def fig5() -> None:
    """Wire-IR within-group residual vs g, contiguous vs interleaved. Source: wire/decompose.py (mesh solver, validated against ngspice)."""
    rows, idx = _idx()
    gs = [4, 8, 16, 32, 64]
    f, ax = FS.fig(2.8)
    out = []
    sty = {("contiguous", 0.5): dict(color=FS.OI["blue"], marker="o", ls="-"), ("contiguous", 0.72): dict(color=FS.OI["blue"], marker="o", ls="-", mfc="white"),
           ("interleaved", 0.5): dict(color=FS.OI["verm"], marker="s", ls="--"), ("interleaved", 0.72): dict(color=FS.OI["verm"], marker="s", ls="--", mfc="white")}
    for (lo, r), st in sty.items():
        y = []
        for g in gs:
            d = json.loads(RP.decomposition_json(lo, g, r).read_text())
            y.append(d["within_budget_term_a_a_eq_g"] * 1e6)
            out.append([lo, r, g, y[-1], d["summary"]["table_held"]["max"] * 1e6])
        ax.plot(gs, y, label=f"{lo}, {r:g} $\\Omega$/pitch", **st)
    lim = [idx[(REC_AREA, REC_RS, REC_SIGMA)][g]["limit_a"] * 1e6 for g in gs]
    left = [max(idx[(REC_AREA, REC_RS, REC_SIGMA)][g]["margin_left_a"] * 1e6, 0.05) for g in gs]
    ax.plot(gs, lim, color="black", lw=1.4, label="budget limit (20% headroom)")
    ax.plot(gs, left, color="black", lw=1.0, ls=(0, (1, 1.5)), marker="x", label="margin left after spread ($\\sigma$ = 0.10)")
    ax.set_xscale("log", base=2); ax.set_yscale("log"); ax.set_xticks(gs); ax.set_xticklabels([str(g) for g in gs])
    ax.set_xlabel("active rows per group $g$"); ax.set_ylabel("uncorrectable wire-IR error ($\\mu$A)")
    ax.legend(fontsize=5.6, loc="lower right")
    FS.write_csv("fig5_wire_ir_vs_g", ["layout", "ohm_per_pitch", "g", "within_group_worst_case_uA", "random_pattern_heldout_max_after_table_uA"], out)
    FS.save(f, "fig5_wire_ir_vs_g")
    _caption("fig5", ("Worst-case bitline wire-IR error that no per-group constant can remove (the within-group, activation-dependent residual after the best per-group, per-count ladder level), "
                      "versus group size g, from the validated 2-D mesh solver ({} F^2 cell, R_s = {:g} ohm, farthest group of a 512-row column, 0.5 and 0.72 ohm per cell pitch). Solid blue: rows of a group laid out contiguously; dashed red: rows "
                      "interleaved across the column. Contiguity keeps every active row within g pitches of its neighbours, so the error grows roughly as g^3 up to g = 16; interleaving spreads the active rows over the whole column and costs 15x (g = 16) to 100x (g = 4) more. "
                      "Black: the budget limit and the margin left after device spread at sigma = 0.10 (floored at 0.05 uA where it is exhausted); the wire term must fit under the dotted curve, which it does only for g <= 8."
                      ).format(REC_AREA, REC_RS))


ALL = {"fig1": fig1, "fig2": fig2, "fig3": fig3, "fig4": fig4, "fig5": fig5, "fig6": fig6}


def write_captions_md() -> None:
    d = json.loads(CAPS.read_text())
    order = ["fig1", "fig2", "fig3_budget_stack", "fig3_budget_stack_final", "fig4", "fig5", "fig6"]
    lines = ["# Figure captions (1B)\n"]
    for k in order:
        if k in d:
            lines.append(f"**{k.replace('_', ' ')}.** {d[k]}\n")
    (FS.OUT / "captions.md").write_text("\n".join(lines))


if __name__ == "__main__":
    which = sys.argv[1:] or list(ALL)
    for k in which:
        ALL[k]()
    write_captions_md()
