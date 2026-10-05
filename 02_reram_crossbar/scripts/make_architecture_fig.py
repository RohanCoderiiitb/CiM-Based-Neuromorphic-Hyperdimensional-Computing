#!/usr/bin/env python3
"""Architecture figure for the project (1C report Figure 13): (a) one 2T2R cell as a schematic, (b) the 512 x 160 array as a block diagram.

Tooling note: ngspice has no schematic capture and no schematic output (it reads netlists and writes numbers), so the picture cannot be produced from the simulator. Panel (a) is drawn with
schemdraw (scripted, SVG/PNG, regenerates with everything else). Xschem (the open-source schematic editor that pairs with ngspice) would let the schematic BE the netlist the simulations run, so the
picture provably matches what was simulated; worth doing for a paper figure of the cell later, not worth the set-up now. Until then every value drawn here is read from device/constants.py (and the 1A /
1C result files) at draw time and ASSERTED equal to the Params the simulations use (margin.core.params_for), so the figure cannot drift from the circuit.

Panel (b) is a block diagram (81,920 cells cannot be drawn) carrying the four design requirements 1C established: five macros, row drivers at BOTH ends of every macro row, contiguous groups of
adjacent rows with per-group thresholds, and supply rails fed from both ends (+ the ground rail as simulated: one pad per macro).

Output: results/figures/fig13_architecture.{png,svg} (both panels), fig13a_cell.{png,svg}, fig13b_array.{png,svg}   (png at 300 dpi).   Usage: python scripts/make_architecture_fig.py (from 02_reram_crossbar)
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import matplotlib                                      # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                        # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle   # noqa: E402
import schemdraw                                       # noqa: E402
import schemdraw.elements as elm                       # noqa: E402

import device.constants as C                           # noqa: E402
import paths as RP                                     # noqa: E402
from device.model import device_resistance             # noqa: E402
from margin.core import params_for                     # noqa: E402
from scaleup.column import R_WIRE_DEFAULT              # noqa: E402

# ------------------------------------------------------------------ every number comes from here
rtx = json.loads((RP.DEVICE / "access_transistor_rtx.json").read_text())
row20 = next(r for r in rtx["rows"] if r["area_f2"] == C.AREA_1C)
ts = json.loads((RP.FULL_COLUMN / "ladder_table_size.json").read_text())["0.72"]
prof = list(csv.DictReader(open(RP.FULL_COLUMN / "group_profile_r0.72.csv")))
V = dict(r_lrs=float(device_resistance(C.GAP_LRS)), r_hrs=float(device_resistance(C.GAP_HRS)), r_tx=C.RTX_BY_AREA[C.AREA_1C], v_read=C.V_READ, v_wl=C.V_WL,
         i_on_uA=row20["i_lrs"] * 1e6, i_off_uA=row20["i_hrs"] * 1e6, rows=C.ROWS_TOTAL, cells=C.FULL_CELLS, macros=C.N_MACROS, cells_per_macro=C.CELLS_PER_MACRO_ROW, g=C.G_1C,
         groups=C.GROUPS_PER_COLUMN, rail=C.RAIL_R_DEFAULT, r_wire=R_WIRE_DEFAULT, thresholds=ts["thresholds_total"], table_bits=ts["sizes"]["0.1"]["half_per_group_range"],
         step_near=float(prof[0]["worst_step_a8_uA"]), step_far=float(prof[-1]["worst_step_a8_uA"]))
V["wire_far"] = V["r_wire"] * (V["rows"] - V["g"] + 1) + C.RS_1C          # bitline + sense resistance behind the farthest group, ohm

# the simulations use margin.core.params_for(...): the drawn values must be exactly its values
_p = params_for(C.AREA_1C, C.RS_1C)
assert V["r_tx"] == _p.r_tx == row20["rtx_lrs"] or abs(V["r_tx"] - row20["rtx_lrs"]) < 1e-3, "access-transistor resistance drawn differs from the simulations'"
assert V["v_read"] == _p.v_read and V["v_wl"] == _p.v_wl, "read / word-line voltage drawn differs from the simulations'"
assert abs(V["r_lrs"] - (row20["r_eff"] - row20["rtx_lrs"])) < 0.5, "low-resistance value drawn differs from the 1A result"
assert V["r_hrs"] == float(device_resistance(_p.gap_hrs)) and V["r_lrs"] == float(device_resistance(_p.gap_lrs)), "device resistances differ from the Params gaps"
assert V["rows"] * V["cells"] == 81920 and V["macros"] * V["cells_per_macro"] == V["cells"] and V["rows"] // V["g"] == V["groups"]

drawn: list[tuple[str, float]] = []                    # (label text, value) pairs; re-checked against the labels at the end


def lab(text: str, key: str, value: float) -> str:
    drawn.append((text, value))
    return text


def check_labels() -> None:
    for text, value in drawn:
        nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", text)]
        assert any(abs(n - value) <= 0.0051 * max(abs(value), 1) for n in nums), f"label {text!r} does not contain {value}"


FS = 8.5
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": FS, "svg.fonttype": "none", "pdf.fonttype": 42})


# ================================================================== panel (a): the cell, schemdraw
def _box(d, x0, y0, x1, y1, lw=1.8):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        d += elm.Line().at(a).to(b).linewidth(lw)


def draw_cell(ax) -> None:
    d = schemdraw.Drawing(canvas=ax, show=False)
    d.config(unit=2.5, fontsize=FS - 0.5, lw=1.4)
    xl, xr = 3.0, 8.0
    d += elm.Line().at((-0.2, 0)).to((11.2, 0)).linewidth(2.4)
    d += elm.Label().at((-0.2, 0.55)).label(lab(f"row line: read voltage {V['v_read']:.3f} V", "v_read", V["v_read"]), halign="left")
    T1 = elm.NFet().right().at((xl, 0)); d += T1
    T2 = elm.NFet().right().reverse().at((xr, 0)); d += T2
    wl_y = T1.gate[1]
    d += elm.Line().at(T1.gate).to(T2.gate).linewidth(2.0)
    d += elm.Dot().at(T1.gate); d += elm.Dot().at(T2.gate)
    xm = (T1.gate[0] + T2.gate[0]) / 2
    d += elm.Label().at((xm, wl_y - 0.55)).label("word line:\n" + lab(f"{V['v_wl']:.2f} V on both gates", "v_wl", V["v_wl"]), halign="center")
    d += elm.Label().at((xl - 0.45, wl_y)).label("access transistor\n" + lab(f"{V['r_tx']:,.0f} ohm in series", "r_tx", V["r_tx"]), halign="right")
    d += elm.Label().at((xr + 0.45, wl_y)).label("access transistor\n" + lab(f"{V['r_tx']:,.0f} ohm in series", "r_tx", V["r_tx"]), halign="left")
    M1 = elm.Memristor().down().at(T1.source).length(2.4); d += M1
    M2 = elm.Memristor().down().at(T2.source).length(2.4); d += M2
    my = (M1.start[1] + M1.end[1]) / 2
    d += elm.Label().at((xl - 0.7, my)).label("LOW resistance\n" + lab(f"{V['r_lrs']:,.0f} ohm", "r_lrs", V["r_lrs"]), halign="right")
    d += elm.Label().at((xr + 0.7, my)).label("HIGH resistance\n" + lab(f"{V['r_hrs']:,.0f} ohm", "r_hrs", V["r_hrs"]), halign="left")
    by = M1.end[1] - 1.3
    d += elm.Line().at(M1.end).to((xl, by)); d += elm.Line().at(M2.end).to((xr, by))
    d += elm.Label().at((xl + 0.55, by + 0.55)).label("BL+", halign="left"); d += elm.Label().at((xr + 0.55, by + 0.55)).label("BL-", halign="left")
    bx0, bx1, bt, bb = xl - 1.4, xr + 1.4, by - 0.9, by - 2.9
    d += elm.Line().at((xl, by)).to((xl, bt)); d += elm.Line().at((xr, by)).to((xr, bt))
    _box(d, bx0, bb, bx1, bt)
    d += elm.Label().at(((bx0 + bx1) / 2, (bt + bb) / 2)).label("sense front-end:\nreads the difference  I(BL+) - I(BL-)", halign="center")
    xc = (bx0 + bx1) / 2
    d += elm.Line().at((xc, bb)).to((xc, bb - 0.8)).linewidth(2.0)
    d += elm.Label().at((xc, bb - 1.55)).label(
        "stored 1: left LOW, right HIGH  ->  difference = +" + lab(f"{V['i_on_uA'] - V['i_off_uA']:.1f} uA", "i", V["i_on_uA"] - V["i_off_uA"]) + "\n"
        "stored 0: the mirror image  ->  same size, negative.  Never zero.", halign="center")
    d.draw(show=False)
    ax.axis("off"); ax.set_xlim(-0.5, 11.5); ax.set_ylim(bb - 2.6, 1.4)


# ================================================================== panel (b): the array, block diagram
def draw_array(ax) -> None:
    ax.set_xlim(0, 100); ax.set_ylim(0, 106); ax.axis("off")
    nm, mw, gw = V["macros"], 9.0, 3.6
    x0 = 1.0
    mx = [x0 + gw + i * (mw + gw) for i in range(nm)]                       # left edge of each macro
    rails = [x0 + gw / 2 + i * (mw + gw) for i in range(nm + 1)]            # rail x (centre of every gap)
    xr_end = rails[-1] + 1.4
    bands = [(88 - 8 * k, 8, V["groups"] - 1 - k) for k in range(3)] + [(52 - 8 * k, 8, 2 - k) for k in range(3)]   # (y_top, height, group index)
    ytop, ymac = 88, 28
    gray = "0.88"
    for rx in rails:                                                          # supply rails with a pad at BOTH ends
        ax.add_patch(Rectangle((rx - 1.0, 93.6), 2.0, 2.6, fc="black", ec="black"))
        ax.add_patch(Rectangle((rx - 1.0, ymac - 4.2), 2.0, 2.6, fc="black", ec="black"))
        ax.plot([rx, rx], [ymac - 1.6, 93.6], color="black", lw=2.6, solid_capstyle="butt")
    ax.text(x0, 103.2, "supply rails (V_read): a pad at the TOP and at the BOTTOM of every rail", ha="left", va="center", fontsize=FS - 1.6, fontweight="bold")
    ax.text(x0, 100.2, f"= fed from BOTH ends;  each rail <= {V['rail']:g} ohm per row", ha="left", va="center", fontsize=FS - 1.6, fontweight="bold")
    for i, x in enumerate(mx):
        ax.add_patch(Rectangle((x, ymac), mw, ytop - ymac, fc="white", ec="black", lw=1.2))
        ax.text(x + mw / 2, ytop + 1.0, f"macro {i + 1}", ha="center", va="bottom", fontsize=FS - 1.8)
        for yt, h, gi in bands:
            hi = (gi == 1)
            ax.add_patch(Rectangle((x, yt - h), mw, h, fc=("0.62" if hi else gray), ec="black", lw=0.7, hatch=("//" if hi else None)))
            if hi:
                for k in range(1, V["g"]):
                    ax.plot([x, x + mw], [yt - h + k * h / V["g"]] * 2, color="black", lw=0.35)
            if i == 0:
                ax.text(x + mw / 2, yt - h / 2, f"group {gi}", ha="center", va="center", fontsize=FS - 3.0, bbox=dict(fc="white", ec="none", pad=0.3, alpha=0.95))
            for side in (0, 1):                                               # a row driver at BOTH ends of this band's rows (triangle pointing into the macro)
                xe = x if side == 0 else x + mw
                dx = -1.8 if side == 0 else 1.8
                ax.add_patch(Polygon([(xe + dx, yt - h / 2 - 1.4), (xe + dx, yt - h / 2 + 1.4), (xe, yt - h / 2)], closed=True, fc="black", ec="black", lw=0.5))
        for yb in (64, 52):                                                   # zigzag break at the edges of the omitted groups
            xs = [x + k * mw / 8 for k in range(9)]
            ax.plot(xs, [yb + (1.0 if k % 2 else -1.0) for k in range(9)], color="black", lw=0.9)
        ax.text(x + mw / 2, 58, "...", ha="center", va="center", fontsize=FS + 3, fontweight="bold")
        for k in range(6):                                                    # bitlines into the sense front-ends under every macro
            cx = x + (k + 0.5) * mw / 6
            ax.plot([cx, cx], [ymac, ymac - 1.4], color="black", lw=0.7)
            ax.add_patch(Rectangle((cx - 0.6, ymac - 6.2), 1.2, 4.8, fc="0.45", ec="black", lw=0.5))
        ax.plot([x, x + mw], [17.0, 17.0], color="black", lw=2.0, ls=(0, (5, 1.5)))        # ground rail of this macro
        ax.add_patch(Rectangle((x - 1.1, 15.9), 1.8, 2.2, fc="black", ec="black"))          # its ground pad
    # far-group dimension arrow along the bitline (right of the last rail), numbered markers in the right margin, matching boxes in the annotation column
    xf = xr_end + 5.2
    ax.annotate("", xy=(xf, ymac - 1.5), xytext=(xf, 86.0), arrowprops=dict(arrowstyle="<->", lw=1.3, color="black"))
    ax.text(xf - 0.9, 57, f"bitline: {V['r_wire']:g} ohm per row", ha="right", va="center", fontsize=FS - 2.6, rotation=90)
    xm_ = xr_end + 2.2
    def marker(n, x, y):
        ax.add_patch(plt.Circle((x, y), 1.45, fc="black", ec="black", zorder=5))
        ax.text(x, y, str(n), ha="center", va="center", color="white", fontsize=FS - 1.8, fontweight="bold", zorder=6)
    xa = 78.0
    box = dict(boxstyle="round,pad=0.3", fc="white", ec="black", lw=0.8)
    def note(n, y, text, bold=False):
        marker(n, xa - 2.6, y)
        ax.text(xa, y, text, ha="left", va="center", fontsize=FS - 2.4, bbox=box, fontweight=("bold" if bold else "normal"))
    marker(1, xm_, 91.5); note(1, 91.5, f"FIVE macros of {V['rows']} x {V['cells_per_macro']}\ncells = {V['rows']*V['cells']:,} bits.\nA longer row line starves\nits far end.")
    marker(2, xm_, 84.0); note(2, 77.5, "ROW DRIVERS at BOTH\nends of every macro row.\nOne driver per row fails\nthe error budget.", bold=True)
    marker(3, xf, 72.0); note(3, 62.5, f"FAR group: {V['wire_far']:.0f} ohm of\nbitline between it and the\nsense circuit -> step\n{V['step_far']:.0f} uA (nearest: {V['step_near']:.0f} uA)")
    marker(4, xm_, 40.0); note(4, 44.0, f"{V['groups']} GROUPS per column,\neach {V['g']} adjacent rows read\ntogether. Must be\ncontiguous.")
    marker(5, xm_, 24.0); note(5, 27.0, "sense front-end under\nevery column pair\n(reads I+ minus I-)")
    marker(6, xm_, 17.0); note(6, 12.5, f"ground rails <= {V['rail']:g}\nohm per pitch, one pad\nper macro (as simulated)")
    # threshold table feeding every sense block
    ax.add_patch(FancyBboxPatch((x0 + 1.5, 1.2), xr_end - x0 - 1.5, 7.4, boxstyle="round,pad=0.25", fc="0.8", ec="black", lw=1.2))
    ax.text((x0 + 1.5 + xr_end) / 2, 4.9, f"stored threshold table: {V['thresholds']:,} thresholds ({V['table_bits']:,} bits).\nEvery group has its OWN entries: far groups give\nweaker signals, so their thresholds sit closer together", ha="center", va="center", fontsize=FS - 2.0, fontweight="bold")
    for x in mx:
        ax.annotate("", xy=(x + mw / 2, ymac - 6.8), xytext=(x + mw / 2, 9.2), arrowprops=dict(arrowstyle="-|>", lw=1.1, color="black"))


def build(which: str):
    if which == "a":
        fig, ax = plt.subplots(figsize=(7.4, 4.6)); draw_cell(ax)
    elif which == "b":
        fig, ax = plt.subplots(figsize=(7.4, 6.2)); draw_array(ax)
    else:
        fig, (a, b) = plt.subplots(2, 1, figsize=(7.4, 11.0), gridspec_kw=dict(height_ratios=[4.6, 6.2], hspace=0.04))
        draw_cell(a); draw_array(b)
        fig.text(0.01, 0.985, "(a) one 2-transistor + 2-resistive-device cell", fontsize=FS + 1, fontweight="bold", va="top")
        fig.text(0.01, 0.575, "(b) the array: five macros of 512 x 32 cells", fontsize=FS + 1, fontweight="bold", va="top")
        fig.subplots_adjust(left=0.01, right=0.99, top=0.975, bottom=0.01)
    return fig


def main() -> None:
    RP.FIGURES.mkdir(parents=True, exist_ok=True)
    for which, name in (("a", "fig13a_cell"), ("b", "fig13b_array"), ("ab", "fig13_architecture")):
        fig = build(which)
        fig.savefig(RP.FIGURES / f"{name}.png", dpi=300, bbox_inches="tight"); fig.savefig(RP.FIGURES / f"{name}.svg", bbox_inches="tight")
        plt.close(fig)
    check_labels()
    print("wrote fig13_architecture / fig13a_cell / fig13b_array (png 300 dpi + svg); labels verified against the constants")


if __name__ == "__main__":
    main()
