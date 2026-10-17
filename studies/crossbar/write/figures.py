"""Figures for 1D-i in the house style (margin/figstyle.py): <repo>/figures/fig22..fig24 (pdf, svg, png 300 dpi, source csv), drawn from results/write_path/*.json.
Usage: python -m write.figures"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from margin import figstyle as FS

J = lambda p: json.loads(p.read_text())


def fig22_delivery() -> None:
    d = J(RP.WRITE / "d1_parallel.json")
    rows = [r for r in d["rows"] if r["kind"] == "base" and "error" not in r and r["params"]["row"] == 512]
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    out = []
    k = 0
    for mode in ("set", "reset"):
        for ori in ("bl", "rl"):
            sel = sorted([r for r in rows if r["params"]["mode"] == mode and r["params"]["orientation"] == ori and r["params"]["v_wl"] == 1.1], key=lambda r: r["params"]["v_drive"])
            x = [r["params"]["v_drive"] for r in sel]
            y = [min(r["before"]["v_dev_min"], r["last"]["v_dev_min"]) for r in sel]
            st = FS.SERIES[k]; k += 1
            lab = (f"SET of an HRS device" if mode == "set" else "RESET of the 541.8 ohm LRS") + f", transistor on {'bitline' if ori == 'bl' else 'row-line'} side"
            a1.plot(x, y, color=st["color"], ls=st["ls"], marker=st["marker"], label=lab)
            out += [[mode, ori, 1.1, xx, yy] for xx, yy in zip(x, y)]
    a1.fill_between([0.8, 2.5], 0.8, 2.0, color="0.85", alpha=0.6, lw=0, label="swept device thresholds 0.8-2.0 V")
    a1.set_xlabel("write supply V_drive (V)"); a1.set_ylabel("voltage reaching the last target device (V)\n(far row, word line 1.1 V)")
    a1.set_xlim(0.8, 2.5); a1.set_ylim(0, 2.5); a1.legend(loc="upper left", fontsize=5.4)
    # right: stress of the selected access transistor (SET, bl) vs drive, and the RESET cap vs word line
    sel = sorted([r for r in rows if r["params"]["mode"] == "set" and r["params"]["orientation"] == "bl" and r["params"]["v_wl"] == 1.1], key=lambda r: r["params"]["v_drive"])
    a2.plot([r["params"]["v_drive"] for r in sel], [r["after"]["vds_max_target"] for r in sel], color=FS.SERIES[0]["color"], marker="o", label="SET: Vds of the written cell's transistor (after switching)")
    for i, vwl in enumerate((1.1, 1.5, 1.8, 2.5)):
        rs = sorted([r for r in rows if r["params"]["mode"] == "reset" and r["params"]["orientation"] == "bl" and r["params"]["v_wl"] == vwl], key=lambda r: r["params"]["v_drive"])
        st = FS.SERIES[i + 1]
        a2.plot([r["params"]["v_drive"] for r in rs], [r["after"]["v_dev_min"] for r in rs], color=st["color"], ls=st["ls"], marker=st["marker"], label=f"RESET: |V| across an HRS-side device, WL {vwl} V")
        out += [["reset_cap", "bl", vwl, r["params"]["v_drive"], r["after"]["v_dev_min"]] for r in rs]
    a2.axhline(1.1, color="k", lw=0.6, ls=":")
    a2.text(0.85, 1.13, "1.1 V core-device rating", fontsize=5.4)
    a2.set_xlabel("write supply V_drive (V)"); a2.set_ylabel("voltage (V)"); a2.set_xlim(0.8, 2.5); a2.set_ylim(0, 2.2); a2.legend(loc="upper left", fontsize=4.9)
    f.subplots_adjust(wspace=0.32)
    FS.save(f, "fig22_write_delivery")
    FS.write_csv("fig22_write_delivery", ["mode", "orientation", "v_wl", "v_drive", "v"], out)


def fig23_unselected() -> None:
    d = J(RP.WRITE / "d2_unselected.json")
    f, (a1, a2) = FS.fig(2.7, ncols=2, nrows=1)
    f.set_size_inches(7.2, 2.7)
    rows = []
    for i, (v, st_) in enumerate(((1.2, "HRS"), (2.0, "HRS"), (1.2, "LRS"), (2.0, "LRS"))):
        r = [x for x in d["float"] if x["v_drive"] == v and x["state"] == st_][0]
        c = max(r["curves"].values(), key=lambda c: c["peak"])
        t = np.array(c["t"]); y = np.array(c["v_dev"])
        st = FS.SERIES[i]
        a1.plot(t * 1e9, y, color=st["color"], ls=st["ls"], label=f"V_drive {v} V, non-target {st_}")
        rows += [["float", v, st_, tt, yy] for tt, yy in zip(t, y)]
    a1.axhline(0.8, color="k", lw=0.5, ls=":"); a1.text(20, 0.62, "lowest swept\nthreshold 0.8 V", fontsize=5.4)
    a1.set_xscale("symlog", linthresh=1.0); a1.set_xlim(0, 300); a1.set_xlabel("time from pulse start (ns)"); a1.set_ylabel("voltage across a FLOATING non-target device (V)")
    a1.legend(fontsize=5.4, loc="upper right")
    modes = ("clamp0", "inhibit_V2", "inhibit_V")
    lab = {"clamp0": "clamped to 0 V", "inhibit_V2": "inhibit at V/2", "inhibit_V": "inhibit at V"}
    for i, m in enumerate(modes):
        for j, st_ in enumerate(("LRS", "HRS")):
            sel = sorted([x for x in d["dc"] if x["mode"] == m and x["row"] == 512 and x["nontarget_state"] == st_], key=lambda x: x["v_drive"])
            st = FS.SERIES[i]
            a2.plot([x["v_drive"] for x in sel], [max(x["after"]["nontarget_i_total"], 1e-9) * 1e3 for x in sel], color=st["color"], ls="-" if st_ == "LRS" else "--", marker=st["marker"],
                    mfc="none" if st_ == "HRS" else st["color"], label=f"{lab[m]}, non-targets {st_}")
            rows += [[m, x["v_drive"], st_, x["after"]["nontarget_i_total"], x["after"]["nontarget_vdev_max"]] for x in sel]
    a2.set_yscale("log"); a2.set_ylim(1e-7, 1e3); a2.set_xlabel("write supply V_drive (V)"); a2.set_ylabel("current, 160 non-target devices (mA)")
    a2.axhline(34.3, color="k", lw=0.5, ls=":"); a2.text(1.45, 80, "write current of the 160 targets", fontsize=5.4)
    a2.text(1.0, 2e-7, "inhibit at V: below the 1e-6 mA plot floor (transistor cut off)", fontsize=5.2)
    a2.legend(fontsize=4.8, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    f.subplots_adjust(wspace=0.32)
    FS.save(f, "fig23_unselected_bitlines")
    FS.write_csv("fig23_unselected_bitlines", ["case", "v_drive", "state", "t_or_current", "v_or_vdev"], rows)


def fig24_schemes() -> None:
    d = J(RP.WRITE / "d3_halfselect.json")
    f, a = FS.fig(2.7)
    rows = []
    for i, (phase, ori) in enumerate((("set", "bl"), ("reset", "bl"), ("reset", "rl"))):
        xs, ys, ts = [], [], []
        for v in sorted({r["v"] for r in d["rows"]}):
            b = d["best"].get(f"{phase}|{v}|{ori}|27.0")
            if b:
                xs.append(v); ys.append(b["stress_others_v"]); ts.append(b["stress_target_v"])
                rows.append([phase, ori, v, b["bln"], b["rlu"], b["wlu"], b["stress_others_v"], b["stress_target_v"], b["disturb_v"]])
        st = FS.SERIES[i]
        a.plot(xs, ys, color=st["color"], ls=st["ls"], marker=st["marker"], label=f"{phase.upper()} ({'bitline' if ori == 'bl' else 'row-line'} side): non-target transistors")
        if phase == "set":
            a.plot(xs, ts, color=st["color"], ls=":", marker=st["marker"], mfc="none", label="SET: the written cell's own transistor (Vds in compliance)")
    a.axhline(1.1, color="k", lw=0.6, ls=":"); a.text(1.0, 1.13, "1.1 V rating", fontsize=5.4)
    a.set_xlabel("write voltage V (V)"); a.set_ylabel("largest terminal voltage on an access\ntransistor, best admissible scheme (V)"); a.legend(fontsize=5.0, loc="upper left")
    a.set_xlim(0.95, 2.25); a.set_ylim(0, 2.4)
    FS.save(f, "fig24_bias_schemes")
    FS.write_csv("fig24_bias_schemes", ["phase", "orientation", "v", "bl_nontarget", "rl_unselected", "wl_unselected", "stress_others_v", "stress_target_v", "disturb_v"], rows)


def main() -> None:
    fig22_delivery(); fig23_unselected(); fig24_schemes()


if __name__ == "__main__":
    main()
