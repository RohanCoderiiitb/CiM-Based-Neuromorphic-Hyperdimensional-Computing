"""House style shared by every paper figure (1B Part B)."""
from __future__ import annotations

import paths as RP

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = RP.FIGURES
W_IN = 3.5                      # single-column width, 89 mm
# Okabe-Ito colourblind-safe palette (never relied on alone: every series also has a marker and a line style)
OI = {"black": "#000000", "orange": "#E69F00", "sky": "#56B4E9", "green": "#009E73", "yellow": "#F0E442",
      "blue": "#0072B2", "verm": "#D55E00", "purple": "#CC79A7"}
SERIES = [dict(color=OI["blue"], marker="o", ls="-"), dict(color=OI["verm"], marker="s", ls="--"),
          dict(color=OI["green"], marker="^", ls="-."), dict(color=OI["purple"], marker="D", ls=":"),
          dict(color=OI["orange"], marker="v", ls="-"), dict(color=OI["sky"], marker="P", ls="--"),
          dict(color=OI["black"], marker="X", ls="-.")]


def apply() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 7.5, "axes.labelsize": 7.5, "axes.titlesize": 7.5,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.2, "legend.frameon": False,
        "axes.linewidth": 0.6, "lines.linewidth": 1.1, "lines.markersize": 3.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "pdf.fonttype": 42, "svg.fonttype": "none", "savefig.bbox": "tight", "savefig.pad_inches": 0.03, "axes.grid": True,
        "grid.linewidth": 0.3, "grid.alpha": 0.5})


def fig(h_in: float = 2.5, **kw):
    apply()
    return plt.subplots(figsize=(W_IN, h_in), **kw)


def save(f, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ext, kw in (("pdf", {}), ("svg", {}), ("png", {"dpi": 300})):
        f.savefig(OUT / f"{name}.{ext}", **kw)
    plt.close(f)


def write_csv(name: str, header: list[str], rows: list[list]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{name}.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(header); w.writerows(rows)
