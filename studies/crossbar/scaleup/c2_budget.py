"""C2(c): re-close the budget with the 1C terms for each rail quality (and feed): supply/ground rail data dependence (measured, run_droop), crosstalk / settling at the
sampling time (measured, run_crosstalk), ladder quantisation and antisymmetric storage (scaleup/table_size). Row line = baseline macro (both-end drive, R_DRV 10, 0.72 ohm/pitch).
Usage: python -m scaleup.c2_budget"""
from __future__ import annotations

import paths as RP

import json
from collections import defaultdict

import numpy as np

import device.constants as C
from scaleup.budget1c import close_1c

Q_LSB_A = 0.1e-6        # [CHOICE] ladder-threshold quantisation step: +/- LSB/2 deterministic error
ANTISYM_FAR_A = None     # filled from ladder_table_size.json


GAIN_RANK = 3           # [CHOICE] rank of the (column) x (group, a) factorisation of the row-line gain used by the readout (storage 3 x (32 + 512) numbers)
GAIN_BITS_EACH = 12     # [CHOICE] bits per stored gain-factor number


def gain_correction_bits() -> int:
    return GAIN_RANK * (C.CELLS_PER_MACRO_ROW + C.GROUPS_PER_COLUMN * C.G_1C) * GAIN_BITS_EACH


def gain_residual_a(which: str, with_rails: bool = True) -> float:
    """Deterministic error left after the rank-GAIN_RANK gain correction: worst relative residual of the measured gain matrix (scaleup/gain_matrix.py) times the group's
    largest level (half the level span, a = g = 8)."""
    m = json.loads((RP.MACRO / ("row_gain_matrix_with_rails.json" if with_rails else "row_gain_matrix.json")).read_text())
    frac = m[f"joint_a_rank{GAIN_RANK}_max_resid_frac"]
    tabs = json.loads(RP.full_column_tables(0.72).read_text())
    t = tabs[-1] if which == "far" else tabs[0]
    return float(frac * t["span"] / 2.0)


def load_rail_rows() -> dict:
    res = json.loads((RP.MACRO / "supply_droop_macro_raw.json").read_text())
    agg = defaultdict(list)
    for r in res:
        if r["a"] == 8 and r["G"] in (0, 63):
            agg[(r["r_rail"], r["feed_both"], "far" if r["G"] == 63 else "near")].append(r)
    return agg


def budget_for(agg, rho, feed, extra_a: dict | None = None, dyn_a: dict | None = None, quant: bool = True, half_table: bool = True) -> dict:
    rows, extra = {}, {}
    ts = json.loads((RP.FULL_COLUMN / "ladder_table_size.json").read_text())["0.72"]
    for w in ("far", "near"):
        rs = agg[(rho, feed, w)]
        gain = min(r["gain_total"] for r in rs)
        rows[w] = dict(gain=gain, row_std_a=max(r["row_std_a"] for r in rs))
        t = []
        if rho is not None:
            t.append(("supply/ground rail (data dependent)", "deterministic", max(r["rail_inc_maxdev_a"] for r in rs)))
        if dyn_a and dyn_a.get(w):
            t.append(("settling + crosstalk at sampling time", "deterministic", dyn_a[w]))
        if quant:
            t.append(("ladder threshold quantisation", "deterministic", Q_LSB_A / 2))
        if half_table:
            t.append(("antisymmetric (half) table storage", "deterministic", 0.5e-6 * (ts["antisym_dev_far_uA"] if w == "far" else ts["antisym_dev_near_uA"])))
        t.append((f"row-gain correction residual (rank {GAIN_RANK})", "deterministic", gain_residual_a(w, rho is not None)))
        extra[w] = t
    b = close_1c(rows, extra)
    b["rows"] = rows
    return b


def main() -> None:
    agg = load_rail_rows()
    print("rail r (ohm/pitch), feed -> margin left (uA, % of limit), worst group, closes")
    out = []
    for rho in (None,) + C.RAIL_R_PER_PITCH_SWEEP:
        for feed in ((True,) if rho is None else (True, False)):
            if (rho, feed, "far") not in agg:
                continue
            b = budget_for(agg, rho, feed)
            out.append(dict(r_rail=rho, feed_both=feed, margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"], closes=b["closes"], worst=b["worst_group"],
                            gain_far=b["rows"]["far"]["gain"], total_a=b["total_a"], limit_a=b["limit_a"]))
            print(f"  rho={rho} feed_both={feed}: margin {b['margin_left_a']*1e6:+.2f} uA ({100*b['margin_frac']:+.1f}%), worst {b['worst_group']}, closes {b['closes']}, gain far {b['rows']['far']['gain']:.3f}")
    (RP.MACRO / "budget_vs_rail.json").write_text(json.dumps(out, indent=1))




# ---------------------------------------------------------------- the 1C baseline design and its sensitivities
def _dyn(G: int, cc: float, t_s_ps: float) -> float:
    """Data-dependent settling + crosstalk error (A) of the victim at sampling time t_s (ladder calibrated at t_s), from the transients."""
    s = json.loads((RP.TRANSIENT / "crosstalk_macro_summary.json").read_text())
    ts = np.array(s["t_s_ps"]); e = np.array(s["groups"][str(G)][str(cc)]["spread_a"])
    return float(np.interp(t_s_ps, ts, e))


def design_budget(r_drv: float = 10.0, rho: float | None = C.RAIL_R_DEFAULT, t_s_ps: float = 200.0, cc: float = C.CC_FRACTION_DEFAULT, r_wl: float = 0.72, quant: bool = True,
                  half_table: bool = True, n_other: int = 40, feed_both: bool = True) -> dict:
    from scaleup.droop import macro_stats
    ts = json.loads((RP.FULL_COLUMN / "ladder_table_size.json").read_text())["0.72"]
    rows, extra, detail = {}, {}, {}
    for which, G in (("far", 63), ("near", 0)):
        ms = [macro_stats(G, 8, v, n_cells=32, n_own=8, n_other=n_other, r_drv=r_drv, r_wl=r_wl, drive_both_ends=True, r_rail=rho, r_gnd=rho, feed_both=feed_both) for v in (0, 15, 31)]
        rows[which] = dict(gain=min(m["gain_total"] for m in ms), row_std_a=max(m["row_std_a"] for m in ms))
        t = []
        if rho is not None:
            t.append(("supply/ground rail (data dependent)", "deterministic", max(m["rail_inc_maxdev_a"] for m in ms)))
        t.append(("settling + crosstalk at sampling time", "deterministic", _dyn(G, cc, t_s_ps)))
        if quant:
            t.append(("ladder threshold quantisation", "deterministic", Q_LSB_A / 2))
        if half_table:
            t.append(("antisymmetric (half) table storage", "deterministic", 0.5e-6 * (ts["antisym_dev_far_uA"] if which == "far" else ts["antisym_dev_near_uA"])))
        t.append((f"row-gain correction residual (rank {GAIN_RANK})", "deterministic", gain_residual_a(which, rho is not None)))
        extra[which] = t
        detail[which] = dict(rail_mean_shift_a=max(m["rail_mean_shift_a"] for m in ms), droop_mean_v=max(m["droop_mean_v"] for m in ms), gnd_max_v=max(m["gnd_max_v"] for m in ms),
                             row_gain=min(m["gain_row"] for m in ms), isup_mean_a=float(np.mean([m["isup_mean_a"] for m in ms])))
    b = close_1c(rows, extra)
    b["rows"] = rows; b["detail"] = detail
    return b


def final_design() -> None:
    out = {}
    base = design_budget()
    out["baseline"] = dict(r_drv=10.0, rho=C.RAIL_R_DEFAULT, t_s_ps=200.0, cc=C.CC_FRACTION_DEFAULT, margin_left_a=base["margin_left_a"], margin_frac=base["margin_frac"], closes=base["closes"],
                           worst_group=base["worst_group"], groups={k: dict(delta_a=v["delta_a"], limit_a=v["limit_a"], total_a=v["total_a"], breakdown=v["breakdown"], margin_left_a=v["margin_left_a"]) for k, v in base["groups"].items()},
                           rows=base["rows"], detail=base["detail"])
    print(f"BASELINE 1C design (both-end drive R_DRV 10, rails {C.RAIL_R_DEFAULT} ohm/pitch fed both ends, sample at 200 ps, cc 0.5): margin {base['margin_left_a']*1e6:+.2f} uA ({100*base['margin_frac']:+.1f}%) worst {base['worst_group']}")
    for k, v in base["groups"]["far"]["breakdown"].items():
        print(f"    far: {k}: {v*1e6:.3f} uA")
    out["vs_sampling_time"] = []
    for cc in (0.5, 0.75):
        for t in (100, 130, 160, 200, 300):
            b = design_budget(t_s_ps=t, cc=cc)
            out["vs_sampling_time"].append(dict(cc=cc, t_s_ps=t, margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"], closes=b["closes"]))
            print(f"  t_s {t} ps cc {cc}: margin {b['margin_left_a']*1e6:+.2f} uA ({100*b['margin_frac']:+.1f}%)")
    out["vs_r_drv"] = []
    for rd in (10.0, 20.0, 30.0):
        b = design_budget(r_drv=rd)
        out["vs_r_drv"].append(dict(r_drv=rd, margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"], closes=b["closes"]))
        print(f"  R_DRV {rd}: margin {b['margin_left_a']*1e6:+.2f} uA ({100*b['margin_frac']:+.1f}%)")
    out["vs_rail"] = []
    for rho, fb in ((C.RAIL_R_DEFAULT, True), (0.072, True), (0.00072, False), (C.RAIL_R_DEFAULT, False), (0.00072, True)):
        b = design_budget(rho=rho, feed_both=fb)
        out["vs_rail"].append(dict(rho=rho, feed_both=fb, margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"], closes=b["closes"], rail_term_far_a=b["groups"]["far"]["breakdown"].get("supply/ground rail (data dependent)", 0.0)))
        print(f"  rails {rho} feed_both {fb}: margin {b['margin_left_a']*1e6:+.2f} uA ({100*b['margin_frac']:+.1f}%)")
    (RP.MACRO / "budget_final_design.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
    final_design()
