"""Figures for 1F in the house style (margin/figstyle.py): results/figures/fig14..fig21 (pdf, svg, png 300 dpi, source csv), drawn from the JSON files in results/sense_frontend and results/pdn.
Usage: python -m sense.figures"""
from __future__ import annotations

import json

import numpy as np
from matplotlib.ticker import NullFormatter

import device.constants as C
import paths as RP
from margin import figstyle as FS

J = lambda p: json.loads(p.read_text())


def fig14_topologies() -> None:
    t = J(RP.SENSE / "topology_comparison.json")
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    sup = t["supply"]
    pts = []
    for nm, scales in (("a", (1, 4, 16)), ("d", (1, 4, 16)), ("c", (1,)), ("d2", (1,)), ("b", (1,))):
        for s in scales:
            key = f"{nm} x{s}" if nm in ("a", "d", "c", "d2") else "b (per differential channel)"
            i_ua = sup[key][0] / (2 if nm == "b" else 1)               # per bitline
            r = [x for x in t["rows"] if x["topology"] == nm and x["ota_scale"] == s and x["group"] == "far" and abs(x["T"] - 1e-9) < 1e-15][0]
            pts.append((nm, s, max(i_ua, 5.0), r["step_ratio_min"], r["vn_min_mV"], r["vn_max_mV"]))
    lab = {"a": "(a) TIA", "d": "(d) integrator, 1-stage OTA", "c": "(c) latch input", "d2": "(d) integrator, 2-stage OTA", "b": "(b) conveyor + copy"}
    sty = {"a": 0, "d": 1, "c": 2, "d2": 3, "b": 4}
    rows = []
    for nm in lab:
        sel = [p for p in pts if p[0] == nm]
        st = FS.SERIES[sty[nm]]
        a1.plot([p[2] for p in sel], [p[3] for p in sel], color=st["color"], ls=st["ls"], marker=st["marker"], label=lab[nm])
        rows += [[nm, p[1], p[2], p[3], p[4], p[5]] for p in sel]
    a1.axhline(1.0, color="k", lw=0.5, ls=":")
    a1.set_xscale("log"); a1.set_xlabel("supply current per bitline (uA)"); a1.set_ylabel("step collected / ideal\n(far group, T = 1 ns)"); a1.set_ylim(0, 1.2); a1.legend(loc="center right", fontsize=5.2)
    a1.annotate("(c): no bias current;\nnode at 0.54 V, row supply 0.64 V", xy=(5.0, 0.85), xytext=(6.5, 0.97), fontsize=5.4, arrowprops=dict(arrowstyle="->", lw=0.5))
    a1.annotate("(b): node held, 125 uA/bitline", xy=(125, 0.78), xytext=(14, 0.62), fontsize=5.4, arrowprops=dict(arrowstyle="->", lw=0.5))
    names = ["a x1", "a x4", "a x16", "d x1", "d x4", "d x16", "c", "d2", "b (differential channel)"]
    x = np.arange(len(names)); w = 0.27
    for k, T in enumerate(("0.5", "1", "2")):
        a2.bar(x + (k - 1) * w, [t["noise_sigma_uA"][n][T] for n in names], w, label=f"T = {T} ns", color=["0.15", "0.55", "0.85"][k], edgecolor="k", linewidth=0.4)
    a2.set_xticks(x); a2.set_xticklabels(["a\nx1", "a\nx4", "a\nx16", "d\nx1", "d\nx4", "d\nx16", "c", "d\n2-st.", "b\n(diff.)"], fontsize=6)
    a2.set_ylabel("input-referred noise 1$\\sigma$ (uA)\n(one channel; b: differential)"); a2.legend()
    f.subplots_adjust(wspace=0.35)
    FS.save(f, "fig14_topologies")
    FS.write_csv("fig14_topologies", ["topology", "ota_scale", "i_per_bitline_uA", "step_ratio_far_1ns", "node_min_mV", "node_max_mV"], rows)


def fig15_noise_sweep() -> None:
    s = J(RP.SENSE / "sweep_b.json")
    s = [r for r in s if "error" not in r]
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    for i, k in enumerate(("2", "4")):
        sel = [r for r in s if f"{r['design']['k']:g}" == k]
        st = FS.SERIES[i]
        a1.plot([r["i_bias_uA"] for r in sel], [r["sigma_uA"]["1"] for r in sel], ls="none", marker=st["marker"], color=st["color"], label=f"copy ratio k = {k}")
    a1.set_xlabel("channel supply current (uA)"); a1.set_ylabel("input-referred noise at T$_w$ = 1 ns (uA, 1$\\sigma$)"); a1.legend()
    a1.set_title("72 sizing/bias points: lower noise costs power, not area", fontsize=6.3)
    ref = [r for r in s if r["design"]["k"] == 4.0 and r["design"]["w1"] == 15e-6 and r["design"]["wi1"] == 8e-6 and r["design"]["wp"] == 16e-6]
    for i, T in enumerate(("0.5", "1", "2")):
        st = FS.SERIES[i]
        a2.plot([r["i_bias_uA"] for r in ref], [r["sigma_uA"][T] for r in ref], color=st["color"], ls=st["ls"], marker=st["marker"], label=f"T$_w$ = {T} ns")
    a2.set_xlabel("channel supply current (uA), vb = 0.50 / 0.46 / 0.42 V"); a2.set_ylabel("noise (uA, 1$\\sigma$)"); a2.legend()
    a2.set_title("chosen sizing (k = 4, W1 = 15 um, OTA1 8 um, mirror 16/0.36 um)", fontsize=6.3)
    rows = [[r["design"]["vb"], r["design"]["k"], r["design"]["w1"], r["design"]["wi1"], r["design"]["wp"], r["i_bias_uA"], r["gate_area_um2"], r["sigma_uA"]["0.5"], r["sigma_uA"]["1"], r["sigma_uA"]["2"], r["cm_gain"]] for r in s]
    FS.save(f, "fig15_noise_sweep")
    FS.write_csv("fig15_noise_sweep", ["vb", "k", "w1", "wi1", "wp", "i_uA", "gate_area_um2", "sigma_0p5_uA", "sigma_1_uA", "sigma_2_uA", "cm_gain"], rows)


def fig16_calibration() -> None:
    m = J(RP.SENSE / "mismatch_mc.json"); c = J(RP.SENSE / "calibration_mc.json"); tr = J(RP.SENSE / "calibration_transient.json")
    f, axs = FS.fig(2.7, ncols=3, nrows=1)
    f.set_size_inches(7.4, 2.7)
    a1, a2, a3 = axs
    src = list(m["sigma_uA"]["far"])
    x = np.arange(len(src)); w = 0.38
    for k, g in enumerate(("far", "near")):
        a1.bar(x + (k - 0.5) * w, [np.mean(list(m["sigma_uA"][g][s].values())) for s in src], w, label=f"{g} group", color=["0.25", "0.75"][k], edgecolor="k", linewidth=0.4)
    a1.axhline(12.2, color=FS.OI["verm"], ls="--", lw=0.8); a1.text(0.0, 13.5, "budget limit 12.2 uA", color=FS.OI["verm"], fontsize=5.8)
    a1.set_xticks(x); a1.set_xticklabels(["all", "OTA1", "OTA2", "copy\nM1/M2", "mirror"], fontsize=6); a1.set_ylabel("static error, 1$\\sigma$ (uA)"); a1.legend(loc="upper right"); a1.set_title("uncalibrated mismatch", fontsize=6.3)
    temps = [float(t) for t in c["temps"]]
    for i, (k, nm) in enumerate((("gain_only", "gain only"), ("gain_and_offset", "gain + offset"))):
        st = FS.SERIES[i]
        a2.plot([t - 27 for t in temps], [c[k][f"{t:g}"]["sigma_worst_point_uA"] for t in temps], color=st["color"], ls=st["ls"], marker=st["marker"], label=nm)
    a2.set_xlabel("read temp. - calibration temp. (K)"); a2.set_ylabel("residual, worst level 1$\\sigma$ (uA)"); a2.set_yscale("log"); a2.legend(); a2.set_title("calibrated at 27 C (DC)", fontsize=6.3)
    rows = []
    for k, vb in enumerate((0.42, 0.46, 0.50)):
        for j, tail in enumerate((0.3e-9, 1.0e-9)):
            sel = sorted([r for r in tr if abs(r["design"]["vb"] - vb) < 1e-9 and abs(r["tail"] - tail) < 1e-15], key=lambda r: r["T"])
            ys = [np.array(r["gain_and_offset"]["sigma_by_point_uA"])[:9].max() for r in sel]
            a3.plot([r["T"] * 1e9 for r in sel], ys, color=FS.SERIES[k]["color"], ls="-" if j == 0 else "--", marker=FS.SERIES[k]["marker"], label=f"vb {vb}, tail {tail*1e9:g} ns")
            rows += [[vb, tail, r["T"], y] for r, y in zip(sel, ys)]
    a3.set_xlabel("read pulse T (ns)"); a3.set_ylabel("residual, far group 1$\\sigma$ (uA)"); a3.set_xscale("log"); a3.set_xticks([0.5, 1, 2]); a3.set_xticklabels(["0.5", "1", "2"]); a3.xaxis.set_minor_formatter(NullFormatter()); a3.legend(fontsize=5.2); a3.set_title("calibrated on the real transient", fontsize=6.3)
    f.subplots_adjust(wspace=0.5)
    FS.save(f, "fig16_mismatch_calibration")
    FS.write_csv("fig16_calibration_transient", ["vb", "tail_s", "T_s", "far_sigma_uA"], rows)


def fig17_pulse() -> None:
    cm = J(RP.SENSE / "closure_map.json")
    f, axs = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    for ax_, g in zip(axs, (8, 4)):
        for i, (s, tail) in enumerate(((0.07, 0.3e-9), (0.10, 0.3e-9), (0.10, 1.0e-9))):
            sel = sorted([r for r in cm if r["g"] == g and r["sigma"] == s and r["d_t"] == 5.0 and r["droop_mV"] == 0.0 and abs(r["vb"] - 0.50) < 1e-9 and abs(r["tail"] - tail) < 1e-15], key=lambda r: r["T"])
            st = FS.SERIES[i]
            ax_.plot([r["T"] * 1e9 for r in sel], [r["margin_left_a"] * 1e6 for r in sel], color=st["color"], ls=st["ls"], marker=st["marker"], label=f"$\\sigma_{{lnG}}$ {s}, tail {tail*1e9:g} ns")
            rows += [[g, s, tail, r["T"], r["margin_left_a"]] for r in sel]
        ax_.axhline(0, color="k", lw=0.6); ax_.axhspan(-0.15, 0.15, color="0.85", zorder=0)
        ax_.set_xscale("log"); ax_.set_xticks([0.5, 1, 2]); ax_.set_xticklabels(["0.5", "1", "2"]); ax_.xaxis.set_minor_formatter(NullFormatter()); ax_.set_xlabel("read pulse T (ns)"); ax_.set_ylabel("budget margin left (uA)")
        ax_.set_title(f"g = {g}, vb 0.50, $\\Delta$T 5 K (grey: Monte-Carlo scatter)", fontsize=6.3); ax_.legend(fontsize=5.5)
    FS.save(f, "fig17_pulse_length_margin")
    FS.write_csv("fig17_pulse_length_margin", ["g", "sigma_lnG", "tail_s", "T_s", "margin_left_A"], rows)


def fig18_pdn() -> None:
    p = J(RP.PDN / "pdn_sweep.json")
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    for i, (sc, rd, lab) in enumerate(((1.0, 0.02, "160 columns, a = 8 (69 mA)"), (0.5, 0.05, "34.6 mA (g = 4 or 80 columns)"), (0.25, 0.05, "17.3 mA"), (0.125, 0.05, "8.7 mA (g = 4, 40 columns)"))):
        sel = sorted([x for x in p if x["t_pulse"] == 1e-9 and abs(x.get("i_scale", 1.0) - sc) < 1e-9 and x["r_d"] == rd and x["stagger"] == 0.0 and x["c_dec"] > 0], key=lambda x: x["c_dec"])
        st = FS.SERIES[i]
        a1.plot([x["c_dec"] * 1e9 for x in sel], [x["droop_max_mV"] for x in sel], color=st["color"], ls=st["ls"], marker=st["marker"], label=lab)
        rows += [[sc, rd, x["c_dec"], x["droop_max_mV"], x["recovery_ns"]] for x in sel]
    for v in (5, 10, 20):
        a1.axhline(v, color="0.5", lw=0.4, ls=":")
    a1.set_xscale("log"); a1.set_yscale("log"); a1.set_xlabel("decoupling C$_{dec}$ (nF)"); a1.set_ylabel("rail droop during the pulse (mV)"); a1.legend(fontsize=5.4); a1.set_title("T = 1 ns", fontsize=6.3)
    for i, (st_, lab) in enumerate(((0.0, "no stagger"), (200e-12, "macros 200 ps apart"))):
        for k, T in enumerate((0.5e-9, 2e-9)):
            sel = sorted([x for x in p if x["t_pulse"] == T and abs(x.get("i_scale", 1.0) - 1.0) < 1e-9 and x["r_d"] == 0.1 and x["stagger"] == st_ and x["c_dec"] > 0], key=lambda x: x["c_dec"])
            a2.plot([x["c_dec"] * 1e9 for x in sel], [x["droop_max_mV"] for x in sel], color=FS.SERIES[k]["color"], ls="-" if i == 0 else "--", marker=FS.SERIES[k]["marker"], label=f"T = {T*1e9:g} ns, {lab}")
            rows += [["stagger", st_, T, x["c_dec"], x["droop_max_mV"]] for x in sel]
    a2.set_xscale("log"); a2.set_yscale("log"); a2.set_xlabel("decoupling C$_{dec}$ (nF)"); a2.set_ylabel("rail droop (mV)"); a2.legend(fontsize=5.4); a2.set_title("full 69 mA, R$_d$ 0.1 ohm: staggering the five macros", fontsize=6.3)
    f.subplots_adjust(wspace=0.35)
    FS.save(f, "fig18_pdn")
    FS.write_csv("fig18_pdn", ["scale_or_tag", "r_d_or_stagger", "c_dec_or_T", "c_dec_or_droop", "droop_or_recovery"], rows)


def fig19_gsurface() -> None:
    cm = J(RP.SENSE / "closure_map.json")
    gs = (4, 8, 16); ss = (0.03, 0.05, 0.07, 0.10, 0.15)
    f, axs = FS.fig(2.4, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.5)
    rows = []
    for ax, droop, ttl in zip(axs, (0.0, 8.0), ("no rail droop", "8 mV rail droop")):
        M = np.zeros((len(gs), len(ss)))
        for i, g in enumerate(gs):
            for j, s in enumerate(ss):
                sel = [r for r in cm if r["g"] == g and r["sigma"] == s and r["d_t"] == 5.0 and r["droop_mV"] == droop]
                best = max(sel, key=lambda r: r["margin_left_a"])
                M[i, j] = best["margin_left_a"] * 1e6
                rows += [[droop, g, s, best["vb"], best["T"], best["tail"], best["margin_left_a"]]]
        im = ax.imshow(np.clip(M, -8, 8), cmap="RdBu", vmin=-8, vmax=8, aspect="auto", origin="lower")
        for i in range(len(gs)):
            for j in range(len(ss)):
                ax.text(j, i, f"{M[i, j]:+.1f}", ha="center", va="center", fontsize=6.5, color="k", fontweight="bold" if M[i, j] > 0.15 else "normal")
        ax.set_xticks(range(len(ss))); ax.set_xticklabels([f"{s}" for s in ss]); ax.set_yticks(range(len(gs))); ax.set_yticklabels([f"g = {g}" for g in gs]); ax.set_xlabel("$\\sigma_{lnG}$"); ax.grid(False)
        ax.set_title(ttl, fontsize=6.5)
    f.colorbar(im, ax=axs, shrink=0.8, label="margin left (uA)")
    FS.save(f, "fig19_g_surface")
    FS.write_csv("fig19_g_surface", ["droop_mV", "g", "sigma_lnG", "vb", "T_s", "tail_s", "best_margin_A"], rows)


def fig20_energy() -> None:
    rec = J(RP.SENSE / "recommended_designs.json")
    f, ax = FS.fig(2.9)
    names = ["g = 8\n160 col.", "g = 8\n20 col./pass", "g = 4\n40 col./pass"]
    sel = [rec[0], rec[1], rec[2]]
    parts = ["array_J", "wordline_J", "sense_bias_J", "decision_J", "threshold_J"]
    lab = ["array (x3.5 for V$_{VG}$)", "word line", "sense bias", "comparator + DAC", "threshold correction (digital)"]
    shades = ["0.15", "0.85", "0.45", "0.65", "0.30"]; hatch = ["", "", "//", "..", "xx"]
    bottom = np.zeros(len(sel)); rows = []
    for p_, l_, s_, h_ in zip(parts, lab, shades, hatch):
        v = np.array([r["energy"][p_] * 1e6 for r in sel])
        ax.bar(range(len(sel)), v, bottom=bottom, color=s_, edgecolor="k", linewidth=0.4, hatch=h_, label=l_)
        rows += [[n, p_, x] for n, x in zip(names, v)]
        bottom += v
    ax.axhline(3.01, color=FS.OI["verm"], ls="--", lw=1.0); ax.text(-0.45, 3.12, "NeuroHDC-small 3.01 uJ", color=FS.OI["verm"], fontsize=6, ha="left", bbox=dict(fc="white", ec="none", pad=0.8))
    for k, b in enumerate(bottom):
        ax.text(k, b + 0.08, f"{b:.2f}", ha="center", fontsize=6.5)
    ax.set_xticks(range(len(sel))); ax.set_xticklabels(names, fontsize=6.5); ax.set_ylabel("energy per inference (uJ)"); ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=5.8)
    FS.save(f, "fig20_energy_per_inference")
    FS.write_csv("fig20_energy_per_inference", ["design", "part", "uJ"], rows)


def fig21_area() -> None:
    rec = J(RP.SENSE / "recommended_designs.json"); a = J(RP.SENSE / "area_table_1f.json")
    f, ax = FS.fig(2.9)
    base = J(RP.FULL_ARRAY / "area_model.json")["variants"]["baseline: both-end drivers, R_DRV 10"]["parts_mm2"]
    cols = [("1C table\n(assumed sense)", base)]
    for nm, key in (("1F\nno decap", "c_dec=0nF|mid"), ("1F + 1 nF\n(g=4, 40 col.)", "c_dec=1nF|mid"), ("1F + 20 nF\n(160 col.)", "c_dec=20nF|mid")):
        cols.append((nm, {k: v * 1e-6 for k, v in a[key]["parts_um2"].items()}))
    parts = ["cell_array", "row_drivers", "wordline_buffers", "row_decoder", "sense_front_ends", "sense_front_ends_1f", "reference_dacs", "ladder_and_gain_storage", "calibration_storage", "supply_ground_straps", "decoupling", "overhead_20pct"]
    nice = {"sense_front_ends": "sense front-ends (1C assumed)", "sense_front_ends_1f": "sense front-ends (1F, simulated)", "reference_dacs": "reference DACs (1C)", "calibration_storage": "calibration storage", "decoupling": "decoupling at 0.35 V",
            "ladder_and_gain_storage": "ladder + gain storage", "supply_ground_straps": "rail straps", "overhead_20pct": "overhead (20%)", "cell_array": "cell array", "row_drivers": "row drivers", "wordline_buffers": "word-line buffers", "row_decoder": "row decoder"}
    shades = ["0.1", "0.8", "0.5", "0.95", "0.65", "0.4", "0.3", "0.55", "0.2", "0.9", "0.7", "0.6"]; hatch = ["", "", "//", "", "..", "xx", "--", "\\\\", "++", "", "||", ""]
    bottom = np.zeros(len(cols)); rows = []
    for p_, s_, h_ in zip(parts, shades, hatch):
        v = np.array([c_[1].get(p_, 0.0) for c_ in cols])
        if v.sum() == 0:
            continue
        ax.bar(range(len(cols)), v, bottom=bottom, color=s_, edgecolor="k", linewidth=0.4, hatch=h_, label=nice.get(p_, p_))
        rows += [[c_[0].replace("\n", " "), p_, x] for c_, x in zip(cols, v)]
        bottom += v
    for k, b in enumerate(bottom):
        ax.text(k, min(b, 0.93) + 0.012, f"{b:.3f}" if b < 1 else f"{b:.2f}", ha="center", fontsize=6.5, bbox=dict(fc="white", ec="none", pad=0.5))
    ax.set_ylim(0, 1.0); ax.set_xticks(range(len(cols))); ax.set_xticklabels([c_[0] for c_ in cols], fontsize=6); ax.set_ylabel("area (mm$^2$; last bar truncated, 4.2 mm$^2$)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=5.6)
    FS.save(f, "fig21_area_1f")
    FS.write_csv("fig21_area_1f", ["design", "part", "mm2"], rows)


def main() -> None:
    for fn in (fig14_topologies, fig15_noise_sweep, fig16_calibration, fig17_pulse, fig18_pdn, fig19_gsurface, fig20_energy, fig21_area):
        fn()
        print("wrote", fn.__name__)


if __name__ == "__main__":
    main()
