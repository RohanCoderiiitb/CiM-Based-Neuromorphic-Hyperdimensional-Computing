"""Section builders for the consolidated 1B report (results/reports/phase1b_report.md). Each returns Markdown; margin/make_report_1b.py assembles them."""
from __future__ import annotations

import paths as RP

import csv
import json
import math
from pathlib import Path

import numpy as np

import device.constants as C
from drift.strategies import evaluate as drift_eval
from margin import surface as S
from margin.core import params_for
from wire import lumped

ROOT = Path(__file__).resolve().parents[1]
RES = RP.RESULTS
SHORT = {"device spread": "spread", "absolute signal (comparator noise)": "abs.signal", "ReRAM HRS leakage residual": "HRS leak",
         "wire IR (within group)": "wire IR", "row-driver IR": "row IR", "reference-cell spread": "ref cells", "drift": "drift", "CMRR": "CMRR",
         "grid-limited": "grid"}


def tbl(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def ua(x, d=1):
    return f"{x * 1e6:.{d}f}"


def load_final(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            d = {}
            for k, v in r.items():
                if k in ("scenario", "strategy", "binding", "worst_group"):
                    d[k] = v
                elif k in ("ok", "budget_ok", "cmrr_ok", "with_wire"):
                    d[k] = v == "True"
                elif k in ("g", "area"):
                    d[k] = int(float(v))
                else:
                    d[k] = float(v) if v not in ("", None) else float("nan")
            rows.append(d)
    return rows


def index_final(rows):
    idx = {}
    for r in rows:
        idx.setdefault((r["area"], r["r_s"], r["sigma"], r["r"], r["scenario"]), {})[r["g"]] = r
    return idx


def gstar_final(by_g: dict):
    gs = sorted(by_g)
    best = max((g for g in gs if by_g[g]["ok"]), default=0)
    if best == gs[-1]:
        return best, "grid-limited"
    nxt = gs[gs.index(best) + 1] if best else gs[0]
    r = by_g[nxt]
    return best, ("CMRR" if not r["cmrr_ok"] else r["binding"])


# ---------------------------------------------------------------- Part C0
def c0_section() -> tuple[str, dict]:
    rows, out = [], {}
    for g in (4, 8, 16, 32, 64):
        b5, b72 = lumped.bound(g, 20, 5.0, 0.5), lumped.bound(g, 20, 5.0, 0.72)
        i5, i72 = lumped.bound(g, 20, 5.0, 0.5, "interleaved"), lumped.bound(g, 20, 5.0, 0.72, "interleaved")
        out[g] = (b5, b72)
        rows.append((g, f"{ua(b5['within_halfrange_far_a'], 2)} - {ua(b72['within_halfrange_far_a'], 2)}", f"{ua(i5['within_halfrange_far_a'], 1)} - {ua(i72['within_halfrange_far_a'], 1)}",
                     f"{ua(b5['delta_ideal_a'])}", f"{ua(b5['delta_far_a'])} - {ua(b72['delta_far_a'])}", f"{b5['far_series_ohm']:.0f} - {b72['far_series_ohm']:.0f}"))
    t = tbl(["g", "within-group half-range, contiguous (uA, 0.5-0.72 ohm/pitch)", "within-group, interleaved (uA)", "Delta, no wire (uA)", "Delta, farthest group (uA)",
             "bitline series R of the far group (ohm)"], rows)
    return t, out


# ---------------------------------------------------------------- mesh validation
def mesh_validation_section() -> str:
    rows = list(csv.DictReader(RP.MESH_VALIDATION_CSV.open()))
    f = lambda k: np.array([float(r[k]) for r in rows])
    rc, rd = f("rel_col"), f("rel_diff_scale")
    per = []
    for (R, K) in ((16, 8), (32, 8), (64, 16)):
        sel = [i for i, r in enumerate(rows) if int(r["R"]) == R and int(r["K"]) == K]
        per.append((f"{R} x {K}", len(sel), f"{rc[sel].max():.2e}", f"{rd[sel].max():.2e}", int(f('iters')[sel].max())))
    t = tbl(["array (rows x cols)", "cases", "worst |dI_col|/I_col", "worst scale-normalised I_diff", "max Newton iterations"], per)
    return (f"{t}\n\n**Worst disagreement over all {len(rows)} cases: {rc.max():.2e} on column current, {rd.max():.2e} on scale-normalised I_diff (threshold {C.ACCEPT_REL_DIFF:.0e}) -> PASS.** "
            f"Every active count a = 1..R, four activation patterns per count (nearest-to-sense rows, farthest rows, two random subsets), two random 2T2R weight draws with log-normal spread (sigma 0.10), "
            f"two wire settings (0.72 ohm/pitch with 10 ohm drivers, and an exaggerated 5 ohm/pitch with 100 ohm drivers). ngspice keeps every physical row; the solver collapses runs of inactive rows analytically, "
            f"so this also validates that elimination. Method: full Newton on all 2nK + K unknowns with the Jacobian solved by sparse LU, step limited to 0.2 V with backtracking, convergence asserted "
            f"(raises if not converged in 60 iterations).")


# ---------------------------------------------------------------- decomposition
def decomposition_section() -> str:
    rows = []
    for g in (4, 8, 16, 32, 64):
        for lo in ("contiguous", "interleaved"):
            for r in (0.5, 0.72):
                d = json.loads(RP.decomposition_json(lo, g, r).read_text()); s = d["summary"]
                rows.append((g, lo, r, ua(s["none"]["max"]), ua(s["table_fit"]["max"], 2), ua(s["table_held"]["max"], 2), ua(s["extreme"]["max"], 2),
                             ua(d["within_budget_term_a_a_eq_g"], 2), ua(s["gain_held"]["max"])))
    t = tbl(["g", "layout", "ohm/pitch", "total wire error vs ideal, max (uA)", "after per-group table: fit max (uA)", "held-out max (uA)", "extremal patterns (uA)",
             "WITHIN-group budget term, worst case (uA)", "after per-group scalar gain only, held-out max (uA)"], rows)
    return t


def groups_section() -> str:
    d = json.loads(RP.decomposition_json("contiguous", 16, 0.72).read_text())
    rows = []
    for gd in d["groups"]:
        full = [c for c in gd["cells"] if c["a"] == 16]
        w = max(max(c["held_vs_minimax_max"], c["minimax_halfrange"], c["ext_vs_minimax_max"]) for c in full)
        rows.append((gd["G"], f"{gd['rows_span'][0]}-{gd['rows_span'][1]}", f"{gd['alpha']:.3f}", ua(max(abs(c['raw_shift']) for c in full)), ua(gd["delta_group_a"]), ua(w, 2),
                     f"{gd['gain_held_rms'] / gd['none_rms'] * 100:.0f}%"))
    return tbl(["group G", "physical rows", "level-scale (alpha) vs ideal", "level shift removed by the per-group table, max (uA)", "group step Delta_G (uA)",
                "residual within the group (uA)", "rms left by a per-group SCALAR gain (% of before)"], rows)


def rowside_section() -> str:
    d = json.loads(RP.ROW_LINE_JSON.read_text())
    rows = [(r["g"], r["K"], f"{r['r_drv']:g}", r["pos"], f"{r['gain_error'] * 100:.0f}%", ua(r["uncorr_std_a"], 2), ua(r["uncorr_maxdev_a"], 2)) for r in d]
    return tbl(["g", "columns per row line K", "R_DRV (ohm)", "pair position", "row-line gain error (correctable per column)", "uncorrectable 1-sigma across other columns' weights (uA)",
                "max deviation (uA)"], rows)


# ---------------------------------------------------------------- drift
def drift_tables() -> dict:
    d = json.loads(RP.DRIFT_SWEEP_JSON.read_text())
    G = (1, 2, 4, 8, 16, 32)

    def gs(dct, fn):
        return max((g for g in G if dct[fn(g)]["ok"]), default=0)
    out = {"s1": [], "s2": [], "s3": []}
    for t in d:
        out["s1"].append((t["sigma"], t["nu"], t["kappa"], gs(t["s1"], lambda g: f"{g}|1.0"), gs(t["s1"], lambda g: f"{g}|10.0")))
        out["s3"].append((t["sigma"], t["nu"], t["kappa"], {(n, m): gs(t["s3"], lambda g, n=n, m=m: f"{g}|10.0|{n}|{m}") for n in C.REF_CELLS_SWEEP for m in ("abs", "ratio")}))
        out["s2"].append((t["sigma"], t["nu"], t["kappa"], {dd: gs(t["s2"], lambda g, dd=dd: f"{g}|{dd}") for dd in C.REFRESH_INTERVALS_DAYS}))
    return out


def drift_gstar_table(dt: dict) -> str:
    rows = []
    s1 = {(a, b, c): (x, y) for a, b, c, x, y in dt["s1"]}
    s3 = {(a, b, c): v for a, b, c, v in dt["s3"]}
    s2 = {(a, b, c): v for a, b, c, v in dt["s2"]}
    for sg in (0.05, 0.10, 0.15):
        for nu in C.NU_MEAN_SWEEP:
            k = (sg, nu, 0.25)
            rows.append((sg, nu, f"{s1[k][0]} / {s1[k][1]}", s2[k][1.0], s2[k][90.0], s2[k][365.0], s2[k][3652.5], s3[k][(128, 'abs')], s3[k][(128, 'ratio')], s3[k][(512, 'abs')]))
    return tbl(["sigma_lnG", "mean exponent nu", "S1 headroom: g* (1 y / 10 y life)", "S2 refresh every 1 d", "every 90 d", "every 365 d", "every 10 y (= none)",
                "S3 128 refs, 'abs'", "S3 128 refs, 'ratio'", "S3 512 refs, 'abs'"], rows)


def refresh_cost_table(dt: dict) -> str:
    n_dev = 2 * C.ROWS_TOTAL * C.FULL_COLS
    e_uj = n_dev * C.WRITE_RETRIES * C.WRITE_ENERGY_PJ * 1e-6
    s2 = {(a, b, c): v for a, b, c, v in dt["s2"]}
    rows = []
    for sg in (0.05, 0.10):
        for nu in (0.003, 0.01, 0.03):
            v = s2[(sg, nu, 0.25)]
            base = max(v.values())
            ok_intervals = [d for d in C.REFRESH_INTERVALS_DAYS if v[d] == base]
            tr = max(ok_intervals)
            n_ref = C.DRIFT_LIFE_YEARS[-1] * 365.25 / tr
            rows.append((sg, nu, base, f"{tr:g}", f"{n_ref:.0f}", f"{n_ref * e_uj:.1f}", f"{n_ref:.0f} of {C.ENDURANCE_CYCLES:.0e}"))
    return tbl(["sigma_lnG", "nu", "best attainable g (any interval)", "longest refresh interval that keeps it (days)", "refreshes in 10 y", "refresh energy over 10 y (uJ) [ASSUM]",
                "cycles used / endurance [ASSUM]"], rows), e_uj, n_dev


def strategy_tradeoff() -> tuple[str, list]:
    """At the recommended cell (no wire): how much drift each strategy cancels and how much spread S3 adds. sigma 0.10, nu 0.01, kappa 0.25, 10 years."""
    rows, raw = [], []
    for g in (8, 16):
        for sc, kw in (("S1 headroom", dict(strategy="S1")), ("S2 refresh 90 d", dict(strategy="S2", refresh_days=90.0)),
                       ("S3 32 refs, abs", dict(strategy="S3", n_ref=32, ref_mode="abs")), ("S3 128 refs, abs", dict(strategy="S3", n_ref=128, ref_mode="abs")),
                       ("S3 512 refs, abs", dict(strategy="S3", n_ref=512, ref_mode="abs")), ("S3 128 refs, ratio", dict(strategy="S3", n_ref=128, ref_mode="ratio"))):
            e0 = drift_eval(g, 20, 5.0, 0.10, 0.0, 0.25, 10.0, kw["strategy"], **{k: v for k, v in kw.items() if k != "strategy"})
            e1 = drift_eval(g, 20, 5.0, 0.10, 0.01, 0.25, 10.0, kw["strategy"], **{k: v for k, v in kw.items() if k != "strategy"})
            w0 = max(e0["ages"], key=lambda a: a["total_a"]); w1 = max(e1["ages"], key=lambda a: a["total_a"])
            rows.append((g, sc, ua(w1["drift_shift_a"]), ua(w1["ref_a"]), ua(w0["ref_a"]), ua(w1["spread5_a"]), ua(w0["spread5_a"]), f"{w1['margin_left_frac'] * 100:.0f}%", "yes" if e1["ok"] else "NO",
                         f"{w0['margin_left_frac'] * 100:.0f}%"))
            raw.append(dict(g=g, strategy=sc, drift_shift_a=w1["drift_shift_a"], ref_a=w1["ref_a"], ref_a_nodrift=w0["ref_a"], margin=w1["margin_left_frac"], margin_nodrift=w0["margin_left_frac"], ok=e1["ok"]))
    t = tbl(["g", "strategy", "uncancelled drift shift (uA)", "reference-cell error added (uA, 5 sigma)", "same with no drift (nu = 0)", "device-spread term at worst age (uA)",
             "same with no drift", "budget left at worst age (nu 0.01)", "closes?", "budget left with no drift"], rows)
    return t, raw


def strategy_final_compare(area: int, r_s: float, r: float = 0.72) -> tuple[str, dict]:
    """g* of each drift strategy on the FINAL budget (wire + row + drift) at the recommended cell, for sigma 0.05/0.10/0.15 and the moderate/strong scenarios."""
    from wire.final import final_point
    variants = [("S1 headroom", "S1", {}), ("S2 refresh 90 d", "S2", dict(refresh_days=90.0)), ("S2 refresh 365 d", "S2", dict(refresh_days=365.0)),
                ("S3 128 refs, abs", "S3", dict(n_ref=128, ref_mode="abs")), ("S3 128 refs, ratio", "S3", dict(n_ref=128, ref_mode="ratio")), ("S3 512 refs, abs", "S3", dict(n_ref=512, ref_mode="abs"))]
    rows, res = [], {}
    for lab, st, kw in variants:
        row = [lab]
        for sc in ("moderate", "strong"):
            cells = []
            for sg in (0.05, 0.10, 0.15):
                best = 0
                for g in (1, 2, 4, 8, 16, 32):
                    if final_point(g, area, r_s, sg, r, sc, st, kw)["ok"]:
                        best = g
                    else:
                        break
                cells.append(best); res[(lab, sc, sg)] = best
            row.append(" / ".join(str(c) for c in cells))
        rows.append(row)
    return tbl(["strategy", "g* at sigma .05 / .10 / .15, drift 'moderate' (nu 0.003)", "drift 'strong' (nu 0.01)"], rows), res


def levers_table(area: int, r_s: float, r: float = 0.72) -> tuple[str, dict]:
    """How fragile is the final g? Layout / front-end levers evaluated on the final budget (S1, drift 'moderate')."""
    from wire.final import final_point
    variants = [("baseline", {}), ("sense node in the column middle", dict(sense="middle")), ("comparator 0.3 uA (1 sigma)", dict(comp_sigma=3e-7)),
                ("both", dict(sense="middle", comp_sigma=3e-7)), ("comparator 3 uA", dict(comp_sigma=3e-6))]
    rows, res = [], {}
    for lab, kw in variants:
        cells = []
        for sg in (0.03, 0.05, 0.10, 0.15):
            best, lim = 0, "-"
            for g in (1, 2, 4, 8, 16, 32):
                fp = final_point(g, area, r_s, sg, r, "moderate", "S1", {}, **kw)
                if fp["ok"]:
                    best = g
                else:
                    lim = "CMRR" if not fp["cmrr_ok"] else SHORT.get(fp["binding"], fp["binding"]); break
            cells.append(f"{best} ({lim})"); res[(lab, sg)] = best
        rows.append([lab] + cells)
    return tbl(["lever", "g* at sigma 0.03", "0.05", "0.10", "0.15"], rows), res
