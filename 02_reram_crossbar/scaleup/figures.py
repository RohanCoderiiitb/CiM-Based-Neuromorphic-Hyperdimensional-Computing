"""Figures for 1C in the 1B house style (margin/figstyle.py): results/figures/fig7..fig12 (pdf, svg, png 300 dpi, source csv). Usage: python -m scaleup.figures"""
from __future__ import annotations

import paths as RP

import json

import numpy as np

import device.constants as C
from margin import figstyle as FS
from scaleup.c2_budget import _dyn


def fig7_profile() -> None:
    f, (a1, a2) = FS.fig(2.9, ncols=1, nrows=2, sharex=True)
    rows = []
    for i, r in enumerate(C.BL_R_PER_PITCH_SWEEP):
        tabs = json.loads(RP.full_column_tables(r).read_text())
        G = np.arange(len(tabs)); span = np.array([t["span"] for t in tabs]) * 1e6; step = np.array([t["worst_step_full"] for t in tabs]) * 1e6
        st = FS.SERIES[i]
        a1.plot(G, span, label=f"{r} ohm/pitch", color=st["color"], ls=st["ls"], marker=st["marker"], markevery=8)
        a2.plot(G, step, color=st["color"], ls=st["ls"], marker=st["marker"], markevery=8)
        rows += [[r, int(g), float(s), float(t)] for g, s, t in zip(G, span, step)]
    a1.set_ylabel("level span (uA)"); a2.set_ylabel("worst step $\\Delta_G$ (uA)"); a2.set_xlabel("group index (0 = at the sense node)")
    a1.legend(title="bitline r")
    FS.save(f, "fig7_group_profile"); FS.write_csv("fig7_group_profile", ["r_ohm_per_pitch", "group", "level_span_uA", "worst_step_a8_uA"], rows)


def fig8_levers() -> None:
    f, ax = FS.fig(2.6)
    lev = json.loads((RP.MACRO / "row_line_levers.json").read_text()); ext = json.loads((RP.MACRO / "row_line_levers_weak_drivers.json").read_text())
    rows = []
    for i, (both, rwl) in enumerate(((False, 0.72), (False, 0.36), (True, 0.72), (True, 0.36))):
        pts = sorted([(t["r_drv"], t["margin_left_a"] * 1e6) for t in lev if t["n_cells"] == 32 and t["both_ends"] == both and t["r_wl"] == rwl] +
                     [(t["r_drv"], t["margin_left_a"] * 1e6) for t in ext if both and t["r_wl"] == rwl and t["r_drv"] > 10])
        st = FS.SERIES[i]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], label=f"{'both ends' if both else 'one end'}, r$_{{wl}}$ {rwl}", color=st["color"], ls=st["ls"], marker=st["marker"])
        rows += [[both, rwl, p[0], p[1]] for p in pts]
    ax.axhline(0, color="k", lw=0.6); ax.axhline(0.80, color="0.4", lw=0.6, ls=":"); ax.text(1.1, 0.88, "1B final (16-cell row line): 0.80 uA", fontsize=5.8, color="0.3")
    ax.set_xscale("log"); ax.set_xlabel("row-driver resistance R$_{DRV}$ (ohm)"); ax.set_ylabel("margin left (uA)"); ax.legend()
    FS.save(f, "fig8_row_line_levers"); FS.write_csv("fig8_row_line_levers", ["both_ends", "r_wl", "r_drv", "margin_left_uA"], rows)


def fig9_rail_crosstalk() -> None:
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.5)
    bud = json.loads((RP.MACRO / "budget_vs_rail.json").read_text()); rows = []
    for i, fb in enumerate((True, False)):
        pts = sorted([(b["r_rail"], b["margin_left_a"] * 1e6) for b in bud if b["r_rail"] is not None and b["feed_both"] == fb])
        st = FS.SERIES[i]; a1.plot([p[0] for p in pts], [max(p[1], -4) for p in pts], label="supply fed from both ends" if fb else "fed from one end", color=st["color"], ls=st["ls"], marker=st["marker"])
        rows += [["rail", fb, p[0], p[1]] for p in pts]
    a1.axhline(0, color="k", lw=0.6); a1.set_xscale("log"); a1.set_xlabel("rail resistance (ohm / pitch)"); a1.set_ylabel("margin left (uA)"); a1.legend()
    s = json.loads((RP.TRANSIENT / "crosstalk_macro_summary.json").read_text()); ts = np.array(s["t_s_ps"])
    k = 0
    for G, nm in (("63", "far group"), ("0", "near group")):
        for cc in ("0.5", "0.75"):
            e = np.maximum(np.array(s["groups"][G][cc]["spread_a"]) * 1e6, 1e-4); st = FS.SERIES[k]; k += 1
            a2.plot(ts, e, label=f"{nm}, cc {cc}", color=st["color"], ls=st["ls"], marker=st["marker"])
            rows += [["crosstalk", nm, cc, float(t), float(v)] for t, v in zip(ts, e)]
    a2.axhline(0.1, color="0.4", lw=0.6, ls=":"); a2.set_yscale("log"); a2.set_xlabel("sampling time (ps)"); a2.set_ylabel("data-dependent error (uA)"); a2.legend()
    FS.save(f, "fig9_rail_and_crosstalk"); FS.write_csv("fig9_rail_and_crosstalk", ["panel", "a", "b", "c", "d"], rows)


def fig10_budget() -> None:
    d = json.loads((RP.MACRO / "budget_final_design.json").read_text())["baseline"]["groups"]["far"]
    bd = d["breakdown"]
    rand = {k: v for k, v in bd.items() if k in ("device spread", "absolute signal (comparator noise)", "row-driver IR")}
    det = {k: v for k, v in bd.items() if k not in rand}
    f, ax = FS.fig(2.7)
    names = list(det) + list(rand); vals = [det[k] * 1e6 for k in det] + [rand[k] * 1e6 for k in rand]
    colors = [FS.OI["verm"]] * len(det) + [FS.OI["blue"]] * len(rand)
    ax.barh(range(len(names)), vals, color=colors); ax.set_yticks(range(len(names))); ax.set_yticklabels([n.replace(" (", "\n(") for n in names], fontsize=5.5); ax.invert_yaxis()
    ax.set_xlabel("error at the far group (uA)  [blue: random, 5 sigma; red: deterministic]")
    ax.text(0.98, 0.04, f"limit {d['limit_a']*1e6:.2f} uA; margin left {d['margin_left_a']*1e6:.2f} uA", transform=ax.transAxes, ha="right", fontsize=6)
    FS.save(f, "fig10_final_budget_far_group"); FS.write_csv("fig10_final_budget_far_group", ["term", "uA"], [[n, v] for n, v in zip(names, vals)])


def fig11_breakeven() -> None:
    f, ax = FS.fig(2.7)
    res = json.loads((RP.READOUT_VARIANTS / "breakeven_margins.json").read_text()); rows = []
    for i, (v, r) in enumerate((("end", 0.72), ("centre", 0.72), ("centre", 0.5), ("seg2_mid", 0.72), ("seg4_mid", 0.72))):
        pts = sorted([(x["sigma"], 100 * x["margin_frac"]) for x in res if x["variant"] == v and x["r"] == r and x["g"] == 16])
        st = FS.SERIES[i]; ax.plot([p[0] for p in pts], [p[1] for p in pts], label=f"{v}, r {r}", color=st["color"], ls=st["ls"], marker=st["marker"])
        rows += [[v, r, p[0], p[1]] for p in pts]
    ax.axhline(0, color="k", lw=0.6); ax.set_xlabel("$\\sigma_{lnG}$"); ax.set_ylabel("budget margin at g = 16 (% of limit)"); ax.legend(); ax.set_ylim(-70, 40)
    FS.save(f, "fig11_g16_breakeven_variants"); FS.write_csv("fig11_g16_breakeven_variants", ["variant", "r", "sigma", "margin_pct"], rows)


def fig12_area() -> None:
    a = json.loads((RP.FULL_ARRAY / "area_model.json").read_text())["variants"]
    f, ax = FS.fig(2.7)
    names = list(a); parts = list(a[names[0]]["parts_mm2"]); bottom = np.zeros(len(names)); rows = []
    for j, p in enumerate(parts):
        v = np.array([a[n]["parts_mm2"][p] for n in names]); ax.bar(range(len(names)), v, bottom=bottom, label=p.replace("_", " "), color=list(FS.OI.values())[j % 8]); bottom += v
        rows += [[n, p, float(x)] for n, x in zip(names, v)]
    ax.set_xticks(range(len(names))); ax.set_xticklabels(["both-end\nR 10", "one-end\nR 2", "both-end\nR 20", "full\ntable"], fontsize=6); ax.set_ylabel("area (mm$^2$)"); ax.legend(fontsize=5, ncol=2)
    FS.save(f, "fig12_array_area"); FS.write_csv("fig12_array_area", ["variant", "part", "mm2"], rows)


def main() -> None:
    for fn in (fig7_profile, fig8_levers, fig9_rail_crosstalk, fig10_budget, fig11_breakeven, fig12_area):
        fn(); print("wrote", fn.__name__)


if __name__ == "__main__":
    main()
