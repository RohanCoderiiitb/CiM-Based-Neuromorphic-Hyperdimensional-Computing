"""Figures for 1D-ii in the house style (margin/figstyle.py): <repo>/figures/fig25..fig29 (pdf, svg, png 300 dpi, source csv), drawn from results/compact_model and
results/program_verify.
Usage: python -m program.figures"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from margin import figstyle as FS
from program import tables as T

J = lambda p: json.loads(p.read_text())


def fig25_validation() -> None:
    d = J(RP.COMPACT / "d0_validation.json")
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    gs = d["gap_sweep"]
    a1.semilogy(gs["gaps"], gs["r_1a_equation"], color=FS.OI["black"], lw=2.4, alpha=0.35, label="1A read equation (device/model.py)")
    a1.semilogy(gs["gaps"], gs["r_osdi"], color=FS.SERIES[0]["color"], ls="none", marker="o", label="compiled rram.va (OpenVAF -> ngspice OSDI)")
    a1.annotate(f"541.82 ohm (1A 541.82)", xy=(0.2, d["r_lrs"]), xytext=(0.45, 2000), fontsize=5.4, arrowprops=dict(arrowstyle="->", lw=0.5))
    a1.annotate(f"218,586 ohm (1A 218,586)", xy=(1.7, d["r_hrs"]), xytext=(0.95, 4e5), fontsize=5.4, arrowprops=dict(arrowstyle="->", lw=0.5))
    a1.set_xlabel("gap (nm)"); a1.set_ylabel("resistance at 0.1 V (ohm)"); a1.legend(fontsize=5.4, loc="lower right")
    a1.text(0.22, 6e4, f"max relative error {gs['max_rel_err']:.1e}", fontsize=5.4)
    rows = [["r_vs_gap", g, a, b] for g, a, b in zip(gs["gaps"], gs["r_osdi"], gs["r_1a_equation"])]
    for i, h in enumerate(d["hysteresis"]):
        st = FS.SERIES[i]
        v, cur = np.array(h["v"]), np.abs(np.array(h["i"]))
        a2.semilogy(v, np.maximum(cur, 1e-9) * 1e6, color=st["color"], ls=st["ls"], label=f"sweep period {h['period_s']:g} s")
        rows += [["hysteresis", h["period_s"], vv, cc] for vv, cc in zip(v, cur)]
    a2.set_xlabel("voltage across the device (V)"); a2.set_ylabel("|current| (uA)"); a2.set_ylim(1e-1, 2e3)
    a2.legend(fontsize=5.4, loc="lower right", title="triangular sweep through 2 kohm", title_fontsize=5.4)
    f.subplots_adjust(wspace=0.3)
    FS.save(f, "fig25_compact_model_validation")
    FS.write_csv("fig25_compact_model_validation", ["series", "x", "y1", "y2"], rows)


def fig26_set_reset() -> None:
    t = T.main_tables()
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    for ax, d, g_in, vs, ttl in ((a1, "set", 1.7, (1.0, 1.3, 1.6, 2.0, 2.4), "SET from HRS (1.7 nm)"), (a2, "reset", 0.35, (0.8, 1.1, 1.4, 2.0, 2.4), "RESET from 0.35 nm")):
        tb = t[d]
        k = int(np.argmin(np.abs(tb["gaps"] - g_in)))
        for i, v in enumerate(vs):
            iv = int(np.argmin(np.abs(tb["volts"] - v)))
            rated = (tb["v_tx_max"][iv, :, k].max() <= 1.1)
            st = FS.SERIES[i]
            ax.semilogx(tb["widths"], tb["gap_out"][iv, :, k], color=st["color"], ls=st["ls"], marker=st["marker"], ms=2.5, mfc=st["color"] if rated else "none",
                        label=f"{v} V" + ("" if rated else " (transistor > 1.1 V)"))
            rows += [[d, v, w, g] for w, g in zip(tb["widths"], tb["gap_out"][iv, :, k])]
        ax.axhline(0.35, color="k", lw=0.5, ls=":"); ax.axhline(1.55, color="k", lw=0.5, ls=":")
        ax.axvline(1e-6, color="0.5", lw=0.6, ls="--")
        ax.text(1.15e-6, 0.95 if d == "set" else 1.25, "1 us\n(1D-i sweep end)", fontsize=5.0)
        ax.text(1.2e-8, 0.37, "design-adjacent LRS 0.35 nm", fontsize=5.0); ax.text(1.2e-8, 1.57, "design-adjacent HRS 1.55 nm", fontsize=5.0)
        ax.set_xlabel("pulse width (s)"); ax.set_ylabel("gap after one pulse (nm)"); ax.set_title(ttl + ", 20 F$^2$, word line 1.1 V, far row", fontsize=6.4)
        ax.set_ylim(0.15, 1.75); ax.legend(fontsize=5.0, loc="upper right" if d == "set" else "center left")
    f.subplots_adjust(wspace=0.28)
    FS.save(f, "fig26_set_reset_maps")
    FS.write_csv("fig26_set_reset_maps", ["direction", "amplitude_v", "width_s", "gap_out_nm"], rows)


def fig27_sigma_surface() -> None:
    d = J(RP.PROGRAM / "d2_surface.json")
    R = d["A"]
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    for i, na in enumerate((1, 4, 16, 64)):
        st = FS.SERIES[i]
        sel = [r for r in R if r["state"] == "lrs" and r["read"] == "1ns" and r["n_avg"] == na and r["c2c"] == 0.3 and r["d2d"] == 0.3 and r["w"] == 0.05 and abs(r["t_w"] - 3.162e-3) < 1e-9]
        sel.sort(key=lambda r: r["n_max"])
        x = [r["n_max"] for r in sel]
        y = [r["sigma_lnG_all"] for r in sel]
        a1.semilogx(x, y, color=st["color"], ls=st["ls"], marker=st["marker"], label=f"verify = mean of {na} read{'s' if na > 1 else ''}")
        fl = d["targets"]["floor_model"][f"lrs|1ns|{na}|0.05"]
        a1.axhline(fl, color=st["color"], lw=0.5, ls=":")
        rows += [["sigma_vs_nmax", na, r["n_max"], r["sigma_lnG_all"], r["yield_"]] for r in sel]
    sel = [r for r in R if r["state"] == "lrs" and r["read"] == "1ns" and r["n_avg"] == 1 and r["c2c"] == 0.3 and r["d2d"] == 0.3 and r["w"] == 0.05 and r["n_max"] == 1]
    a1.axhline(0.10, color="k", lw=0.8, ls="--"); a1.text(1.05, 0.104, "1A-1F assumed 0.10", fontsize=5.4)
    a1.axhline(0.07, color="0.4", lw=0.6, ls="-."); a1.text(1.05, 0.073, "1F: g = 8 needs <= 0.07", fontsize=5.0)
    a1.axhline(0.045, color="0.4", lw=0.6, ls="-."); a1.text(1.05, 0.047, "1F: g = 16 needs <= 0.045", fontsize=5.0)
    a1.set_xlabel("pulses allowed per device (n_max)"); a1.set_ylabel("achieved sigma_lnG, all devices (LRS)"); a1.set_ylim(0, 0.2)
    a1.legend(fontsize=5.0, loc="upper right"); a1.set_title("in-envelope array, 3.2 ms pulses, +/-5% window, imposed variability 0.3/0.3", fontsize=5.6)
    # effort frontier: sigma vs energy per device, every configuration with yield >= 99.9% and variability 0.3/0.3
    for i, na in enumerate((1, 4, 16, 64)):
        st = FS.SERIES[i]
        sel = [r for r in R if r["state"] == "lrs" and r["n_avg"] == na and r["c2c"] == 0.3 and r["d2d"] == 0.3 and r["yield_"] >= 0.999]
        a2.loglog([r["energy_mean_j"] * 1e6 for r in sel], [max(r["sigma_lnG"], 1e-3) for r in sel], color=st["color"], ls="none", marker=st["marker"], ms=2.5, alpha=0.7,
                  label=f"{na} read{'s' if na > 1 else ''} per verify")
        rows += [["frontier", na, r["energy_mean_j"], r["sigma_lnG"], r["time_mean_s"]] for r in sel]
    a2.set_xlabel("program energy per LRS device (uJ)"); a2.set_ylabel("sigma_lnG of the accepted devices"); a2.legend(fontsize=5.0)
    a2.set_title("every configuration reaching 99.9% yield", fontsize=5.6)
    f.subplots_adjust(wspace=0.3)
    FS.save(f, "fig27_sigma_surface")
    FS.write_csv("fig27_sigma_surface", ["series", "n_avg", "x", "y", "extra"], rows)


def fig28_retention() -> None:
    d = J(RP.PROGRAM / "d3_retention.json")
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    from program.d3_retention import zero_bias_mirror
    tt = np.logspace(-9, np.log10(3.2e8), 120)
    for i, sm in enumerate((1e-8, 1e-10, 1e-12)):
        st = FS.SERIES[i]
        for g0, ls in ((0.35, "-"), (1.55, "--")):
            y = zero_bias_mirror(g0, sm, tuple(tt))
            a1.semilogx(tt, y, color=st["color"], ls=ls, label=f"smoothing {sm:g}" if g0 == 0.35 else None)
            rows += [["zero_bias", sm, g0, t_, y_] for t_, y_ in zip(tt, y)]
    for x, lab in ((1, "1 s"), (3600, "1 h"), (86400, "1 d"), (3.156e7, "1 y")):
        a1.axvline(x, color="0.8", lw=0.5); a1.text(x * 1.3, 0.95, lab, fontsize=5)
    a1.set_xlabel("time at zero bias (s)"); a1.set_ylabel("gap (nm)"); a1.legend(fontsize=5.2, loc="center left", title="from 0.35 nm (solid) / 1.55 nm (dashed)", title_fontsize=5.2)
    a1.set_title("zero bias: the clamp tail only (physical term = 0)", fontsize=6)
    for i, rec in enumerate(d["read_disturb"]):
        st = FS.SERIES[i]
        x = [r["gap"] for r in rec["rows"] if "rate_nm_per_s" in r]
        y = [abs(r["rate_nm_per_s"]) for r in rec["rows"] if "rate_nm_per_s" in r]
        a2.semilogy(x, y, color=st["color"], ls=st["ls"], marker=st["marker"], label=f"{rec['temp_c']:g} C")
        rows += [["read_disturb", rec["temp_c"], a, b] for a, b in zip(x, y)]
    a2.set_xlabel("gap (nm)"); a2.set_ylabel("gap closing rate at the read bias (nm/s)"); a2.legend(fontsize=5.4)
    a2.set_title("1F read bias (0.35 / 0.25 V): read disturb, SET direction", fontsize=6)
    f.subplots_adjust(wspace=0.3)
    FS.save(f, "fig28_retention_read_disturb")
    FS.write_csv("fig28_retention_read_disturb", ["series", "param", "x", "y", "z"], rows)


def fig29_budget_trade() -> None:
    d = J(RP.PROGRAM / "d4_budget.json")
    best = d["closure_best"]
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    for i, g in enumerate((4, 8, 16)):
        st = FS.SERIES[i]
        ks = sorted([v for v in best.values() if v["g"] == g and v["droop_mV"] == 8.0 and v["cal_scale"] == 1.0 and v["sigma_lrs"] == v["sigma_hrs"]], key=lambda v: v["sigma_lrs"])
        a1.plot([v["sigma_lrs"] for v in ks], [v["margin_a"] * 1e6 for v in ks], color=st["color"], ls=st["ls"], marker=st["marker"], label=f"g = {g} (1F's surface, sigma_HRS = sigma_LRS)")
        rows += [["surface", g, v["sigma_lrs"], v["margin_a"]] for v in ks]
        pts = [p for p in d["effort"] if p["scen"] == "A"]
        for p in pts:
            k = f"{g}|{round(p['sigma_lrs'], 4)}|{round(p['sigma_hrs'], 4)}|8|1.0"
            if k in best:
                a1.plot(p["sigma_lrs"], best[k]["margin_a"] * 1e6, color=st["color"], marker="*", ms=6, ls="none")
                rows.append(["measured", g, p["sigma_lrs"], best[k]["margin_a"]])
    a1.axhline(0, color="k", lw=0.6); a1.axhspan(-0.15, 0.15, color="0.85", alpha=0.6, lw=0)
    a1.plot([], [], "k*", ms=6, label="measured program-verify points (model)")
    a1.set_xlabel("sigma_lnG of the LRS"); a1.set_ylabel("budget margin left (uA), best front-end point,\n5 K window, 8 mV droop"); a1.legend(fontsize=5.0)
    # trade: program energy per refresh amortised per inference vs number of inferences per program
    n = np.logspace(2, 9, 200)
    pts = sorted([p for p in d["effort"] if p["scen"] == "A" and p["c2c"] == 0.3], key=lambda p: p["sigma_lrs"])
    for i, p in enumerate(pts[:4]):
        st = FS.SERIES[i]
        y = (p["e_full_j"] / n + 4.65e-6) * 1e6
        a2.loglog(n, y, color=st["color"], ls=st["ls"], label=f"sigma {p['sigma_lrs']:.3f} ({p['read']}, {p['n_avg']} reads): {p['e_full_j']:.2g} J / program")
        rows += [["trade", p["sigma_lrs"], nn, yy] for nn, yy in zip(n[::10], y[::10])]
    a2.axhline(5.29, color="k", lw=0.6, ls="--"); a2.text(150, 5.6, "g = 4 per-inference energy (1F, 5.29 uJ)", fontsize=5.0)
    a2.axhline(4.65, color="0.4", lw=0.6, ls=":"); a2.text(150, 3.9, "g = 8 (4.65 uJ)", fontsize=5.0)
    rd = d["read_disturb"]
    for key, lab in (("27.0|8", "refresh needed, 27 C"), ("85.0|8", "85 C")):
        x = rd[key]["inferences_to_027uA"]
        a2.axvline(x, color="0.3", lw=0.6, ls="-."); a2.text(x * 1.1, 2e3, lab + f"\n({x:.2g} inf.)", fontsize=5.0)
    a2.set_xlabel("inferences per program (refresh interval)"); a2.set_ylabel("energy per inference incl. programming (uJ)"); a2.set_ylim(3, 1e4)
    a2.legend(fontsize=4.6, loc="upper right")
    f.subplots_adjust(wspace=0.32)
    FS.save(f, "fig29_budget_trade")
    FS.write_csv("fig29_budget_trade", ["series", "param", "x", "y"], rows)


def main() -> None:
    fig25_validation(); fig26_set_reset(); fig27_sigma_surface(); fig28_retention(); fig29_budget_trade()


if __name__ == "__main__":
    main()
