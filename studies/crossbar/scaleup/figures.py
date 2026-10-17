"""Figures for 1C in the 1B house style (margin/figstyle.py): results/figures/fig7..fig12 (pdf, svg, png 300 dpi, source csv). Usage: python -m scaleup.figures"""
from __future__ import annotations

import paths as RP

import hashlib
import json
from pathlib import Path

import numpy as np

import device.constants as C
from margin import figstyle as FS
from scaleup.c2_budget import _dyn


MANIFEST = RP.FIGURES / "figures_1c_manifest.json"
_INPUTS: dict[str, list[str]] = {}


def _sha(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def _register(fig: str, *paths) -> None:
    """Record the exact input files (by content hash) a figure was drawn from; scaleup.make_report refuses to build if any has changed since."""
    _INPUTS[fig] = {str(Path(p).relative_to(RP.RESULTS)): _sha(p) for p in paths}


def fig7_profile() -> None:
    f, (a1, a2) = FS.fig(3.1, ncols=1, nrows=2, sharex=True)
    rows = []
    budget = json.loads((RP.MACRO / "budget_final_design.json").read_text())["baseline"]["groups"]["far"]
    for i, r in enumerate(C.BL_R_PER_PITCH_SWEEP):
        tabs = json.loads(RP.full_column_tables(r).read_text())
        G = np.arange(len(tabs)); span = np.array([t["span"] for t in tabs]) * 1e6; step = np.array([t["worst_step_full"] for t in tabs]) * 1e6
        st = FS.SERIES[i]
        for ax_, y in ((a1, span), (a2, step)):
            ax_.plot(G, y, color=st["color"], ls=st["ls"], lw=1.0)                                  # every one of the 64 groups
            ax_.plot(G, y, color=st["color"], ls="none", marker=".", ms=2.2)                         # a dot on each group
            ax_.plot(G[::8], y[::8], color=st["color"], ls="none", marker=st["marker"], label=f"{r} ohm/pitch" if ax_ is a1 else None)   # larger marker every 8th
        rows += [[r, int(g), float(sp), float(t)] for g, sp, t in zip(G, span, step)]
        if r == 0.72:
            far_step = step[-1]
    a1.set_ylabel("level span (uA)"); a2.set_ylabel("worst step $\\Delta_G$ (uA)"); a2.set_xlabel("group index (0 = at the sense node; all 64 plotted)")
    a1.legend(title="bitline r"); a2.set_ylim(0, 175)
    a2.annotate(f"far group: ideal step {far_step:.1f} uA\n-> {budget['delta_a']*1e6:.2f} uA after row-line and rail losses\n-> allows {budget['limit_a']*1e6:.2f} uA;\n    error {budget['total_a']*1e6:.2f} uA", xy=(63, far_step), xytext=(23, 128), fontsize=5.6,
                arrowprops=dict(arrowstyle="->", lw=0.6), bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.5", lw=0.5))
    FS.save(f, "fig7_group_profile"); FS.write_csv("fig7_group_profile", ["r_ohm_per_pitch", "group", "level_span_uA", "worst_step_a8_uA"], rows)
    _register("fig7", *[RP.full_column_tables(r) for r in C.BL_R_PER_PITCH_SWEEP], RP.MACRO / "budget_final_design.json")


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
    ax.axhline(0, color="k", lw=0.6); ax.axhline(0.80, color="0.4", lw=0.8, ls=":", label="1B final (16-cell row line): 0.80 uA")
    ax.set_xscale("log"); ax.set_xlabel("row-driver resistance R$_{DRV}$ (ohm)"); ax.set_ylabel("margin left (uA)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
    FS.save(f, "fig8_row_line_levers"); FS.write_csv("fig8_row_line_levers", ["both_ends", "r_wl", "r_drv", "margin_left_uA"], rows)
    _register("fig8", RP.MACRO / "row_line_levers.json", RP.MACRO / "row_line_levers_weak_drivers.json")


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
    _register("fig9", RP.MACRO / "budget_vs_rail.json", RP.TRANSIENT / "crosstalk_macro_summary.json")


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
    (RP.FIGURES / "fig10_final_budget_far_group.json").write_text(json.dumps(dict(terms=list(bd), margin_left_uA=round(d["margin_left_a"] * 1e6, 2), limit_uA=round(d["limit_a"] * 1e6, 2), total_uA=round(d["total_a"] * 1e6, 2)), indent=1))
    _register("fig10", RP.MACRO / "budget_final_design.json")


def fig11_breakeven() -> None:
    f, ax = FS.fig(2.7)
    res = json.loads((RP.READOUT_VARIANTS / "breakeven_margins.json").read_text()); rows = []
    for i, (v, r) in enumerate((("end", 0.72), ("centre", 0.72), ("centre", 0.5), ("seg2_mid", 0.72), ("seg4_mid", 0.72))):
        pts = sorted([(x["sigma"], 100 * x["margin_frac"]) for x in res if x["variant"] == v and x["r"] == r and x["g"] == 16])
        st = FS.SERIES[i]; ax.plot([p[0] for p in pts], [p[1] for p in pts], label=f"{v}, r {r}", color=st["color"], ls=st["ls"], marker=st["marker"])
        rows += [[v, r, p[0], p[1]] for p in pts]
    ax.axhline(0, color="k", lw=0.6); ax.set_xlabel("$\\sigma_{lnG}$"); ax.set_ylabel("budget margin at g = 16 (% of limit)"); ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False); ax.set_ylim(-130, 40)
    FS.save(f, "fig11_g16_breakeven_variants"); FS.write_csv("fig11_g16_breakeven_variants", ["variant", "r", "sigma", "margin_pct"], rows)
    _register("fig11", RP.READOUT_VARIANTS / "breakeven_margins.json")


def fig12_area() -> None:
    a = json.loads((RP.FULL_ARRAY / "area_model.json").read_text())["variants"]
    f, ax = FS.fig(3.2)
    names = list(a); parts = list(a[names[0]]["parts_mm2"]); bottom = np.zeros(len(names)); rows = []
    nice = {"cell_array": "cell array", "row_drivers": "ROW DRIVERS (largest)", "wordline_buffers": "word-line buffers", "row_decoder": "row decoder", "sense_front_ends": "sense front-ends",
            "reference_dacs": "reference DACs", "ladder_and_gain_storage": "ladder + gain storage", "supply_ground_straps": "supply/ground straps", "overhead_20pct": "overhead (20%)"}
    shades = ["0.15", "0.85", "0.35", "0.60", "0.72", "0.45", "0.25", "0.92", "0.55"]
    hatches = ["", "", "//", "\\\\", "..", "xx", "--", "", "++"]
    handles = []
    for j, p_ in enumerate(parts):
        v = np.array([a[n]["parts_mm2"][p_] for n in names])
        bar = ax.bar(range(len(names)), v, bottom=bottom, label=nice.get(p_, p_.replace("_", " ")), color=shades[j % len(shades)], edgecolor="black", linewidth=0.5, hatch=hatches[j % len(hatches)])
        handles.append(bar); bottom += v
        rows += [[n, p_, float(x)] for n, x in zip(names, v)]
    for k, n in enumerate(names):                                  # totals above the bars
        ax.text(k, bottom[k] + 0.004, f"{bottom[k]:.3f}", ha="center", fontsize=6.5)
    ax.set_xticks(range(len(names))); ax.set_xticklabels(["both-end\nR 10", "one-end\nR 2", "both-end\nR 20", "full\ntable"], fontsize=6.5); ax.set_ylabel("area (mm$^2$)"); ax.set_ylim(0, bottom.max() * 1.10)
    leg = ax.legend(handles[::-1], [nice.get(p_, p_.replace("_", " ")) for p_ in parts[::-1]], loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=6, frameon=False)
    for t in leg.get_texts():
        if t.get_text().startswith("ROW"):
            t.set_fontweight("bold")
    FS.save(f, "fig12_array_area"); FS.write_csv("fig12_array_area", ["variant", "part", "mm2"], rows)
    _register("fig12", RP.FULL_ARRAY / "area_model.json")


def main() -> None:
    for fn in (fig7_profile, fig8_levers, fig9_rail_crosstalk, fig10_budget, fig11_breakeven, fig12_area):
        fn(); print("wrote", fn.__name__)
    MANIFEST.write_text(json.dumps(_INPUTS, indent=1))


if __name__ == "__main__":
    main()
