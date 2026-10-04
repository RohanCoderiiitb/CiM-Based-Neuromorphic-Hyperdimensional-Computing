"""Turn the swept points into the g surface and the binding-term map."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import device.constants as C

PTS = Path(__file__).resolve().parents[1] / "results" / "1b_i" / "surface_points.csv"
FINE = PTS.with_name("surface_points_fine.csv")      # 1B Part A: sigma 0.01 / 0.02 / 0.03
_NUM = {"g", "a", "area", "delta_loc", "spread_std_loc", "mu_nonuniform_argmin"}
_BOOL = {"cmrr_ok", "budget_closes", "ok"}


def load(path: Path = PTS, fine: bool = True) -> list[dict]:
    rows = []
    paths = [path] + ([FINE] if fine and FINE.exists() else [])
    for pth in paths:
        rows += _load_one(pth)
    return rows


def _load_one(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            d = {}
            for k, v in r.items():
                if k == "binding_term":
                    d[k] = v
                elif k in _BOOL:
                    d[k] = v == "True"
                elif k in _NUM:
                    d[k] = int(float(v))
                else:
                    d[k] = float(v)
            rows.append(d)
    return rows


def index(rows: list[dict]) -> dict:
    """(area, r_s, sigma) -> {g: row}"""
    idx = defaultdict(dict)
    for r in rows:
        idx[(r["area"], r["r_s"], r["sigma"])][r["g"]] = r
    return idx


def limiting(row: dict) -> str:
    """Which constraint fails at this point (row must be not ok)."""
    if not row["cmrr_ok"]:
        return "CMRR"
    return row["binding_term"]


def g_star(by_g: dict) -> tuple[int, str, bool]:
    """Largest g in the grid that is ok, the term that limits the NEXT grid g, and whether ok is monotone in g.

    g* = 0 means even g = 1 fails. 'grid-limited' means the largest grid g is still ok."""
    gs = sorted(by_g)
    oks = [by_g[g]["ok"] for g in gs]
    monotone = all(oks[i] >= oks[i + 1] for i in range(len(oks) - 1))
    best = max((g for g in gs if by_g[g]["ok"]), default=0)
    if best == gs[-1]:
        return best, "grid-limited", monotone
    nxt = gs[gs.index(best) + 1] if best else gs[0]
    return best, limiting(by_g[nxt]), monotone
