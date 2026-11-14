"""figures/operating_point_sweep.png: crossbar energy per inference against analog-macro area over the LRS sweep (S1 d). One series; emphasis on the chosen point and the 541.8 ohm baseline,
hollow markers where the integration window needs more than one clock cycle per pass.   python scripts/make_op_sweep_fig.py"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
d = json.loads((HERE / "results/macro_512x32/operating_point_sweep_report.json").read_text())
rows = [r for r in d["rows"] if r.get("feasible") and "area_mm2" in r and r["ron"] <= 20000]
INK, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#e3e2de", "#fcfcfb"
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#9a998f"
CHOSEN = 5000.0
LABELLED = {541.8: (6, 6), 1000.0: (6, 6), 1500.0: (6, -13), 2000.0: (4, 8), 3000.0: (6, 8), 5000.0: (8, -14), 7500.0: (8, -3), 10000.0: (8, -3), 20000.0: (8, 0)}
fig, ax = plt.subplots(figsize=(8.2, 5.0), dpi=160, facecolor=SURF)
ax.set_facecolor(SURF)
xs = [r["area_mm2"]["macro_160_s2"] for r in rows]
ys = [r["energy_uJ"]["total_after"] for r in rows]
ax.plot(xs, ys, color=GRAY, lw=1.2, zorder=1)
for r, x, y in zip(rows, xs, ys):
    one = r["cycles_per_pass"] == 1
    col = BLUE if r["ron"] == CHOSEN else ORANGE if r["ron"] == 541.8 else GRAY
    ax.scatter([x], [y], s=46 if r["ron"] in (CHOSEN, 541.8) else 30, facecolor=col if one else SURF, edgecolor=col, lw=1.6, zorder=3)
    if r["ron"] not in LABELLED:
        continue
    lab = f"{r['ron'] / 1000:g} k" if r["ron"] >= 1000 else f"{r['ron']:g}"
    dx, dy = LABELLED[r["ron"]]
    ax.annotate(lab + ("" if one else f" ({r['cycles_per_pass']} cycles/pass)"), (x, y), textcoords="offset points", xytext=(dx, dy), fontsize=8, color=INK if r["ron"] in (CHOSEN, 541.8) else MUTED)
ax.set_xlabel("analog macro area, mm$^2$ (cell array + periphery + front-end + decoupling, x1.2)", color=MUTED, fontsize=9)
ax.set_ylabel("crossbar energy per inference, $\\mu$J", color=MUTED, fontsize=9)
ax.set_title("LRS sweep: each point with its own select transistor, comparators re-costed (S2)", color=INK, fontsize=10.5, loc="left")
ax.grid(color=GRID, lw=0.8)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color(GRID)
ax.tick_params(colors=MUTED, labelsize=8)
ax.text(0.99, 0.02, "filled: one clock cycle per pass; hollow: the window needs more\nblue: chosen 5 k$\\Omega$; orange: 541.8 $\\Omega$ (128 F cell)", transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=MUTED)
out = REPO / "figures" / "operating_point_sweep.png"
fig.tight_layout()
fig.savefig(out, facecolor=SURF)
print(out)
