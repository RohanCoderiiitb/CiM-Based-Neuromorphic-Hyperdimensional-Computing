"""C5: how many columns can sense at once. Electrical side from the five-macro DC study (run_array: supply/ground rails shared by the macros, contiguous macros 1..5 sensing, and the
one-bit-plane mode with floating idle bitlines) plus the bit-plane crosstalk transient; digital side from 1E's measured regressions (cycles, group reads, g = 8).
Cycle model (fits all 1E runs to 1 cycle): cycles/inference = C0 + group_reads, C0 = mean(cycles - reads_issued) over the 1E runs; reads(W) = reads_160 * ceil(160 / W).
Usage: python -m scaleup.c5_decision"""
from __future__ import annotations

import paths as RP

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

import device.constants as C
from scaleup.budget1c import close_1c
from scaleup.c2_budget import GAIN_RANK, Q_LSB_A, _dyn, gain_residual_a

REG = Path(__file__).resolve().parents[2] / "03_rtl" / "results" / "regression"


def cycle_model() -> dict:
    runs = {}
    for tag in ("dvs_seed0_g4_c160", "dvs_seed0_g8_c160", "dvs_seed0_g16_c160", "dvs_seed0_g32_c160", "dvs_seed0_g64_c160", "dvs_seed0_g8_c20", "dvs_seed0_g64_c20"):
        d = json.loads((REG / f"{tag}.json").read_text())["samples"]
        runs[tag] = dict(cycles=float(np.mean([s["cycles"] for s in d])), reads=float(np.mean([s["group_reads_issued"] for s in d])), events=float(np.mean([s["n_events"] for s in d])))
        runs[tag]["c0"] = runs[tag]["cycles"] - runs[tag]["reads"]
    c0 = float(np.mean([r["c0"] for r in runs.values()]))
    return dict(runs=runs, c0=c0, c0_spread=float(np.ptp([r["c0"] for r in runs.values()])), reads_160=runs["dvs_seed0_g8_c160"]["reads"])


def _bitplane_dyn(G: int, cc: float, t_s_ps: float) -> float:
    raw = json.loads((RP.TRANSIENT / "crosstalk_bitplane_raw.json").read_text()); ts = np.array(raw["t_s"]) * 1e12
    e = np.array([r["err_a"] for r in sorted([x for x in raw["runs"] if x["G"] == G and x["cc"] == cc], key=lambda r: r["pat"])])
    return float(np.interp(t_s_ps, ts, np.abs(e - e.mean(0)).max(0)))


def main() -> None:
    cm = cycle_model()
    raw = json.loads((RP.FULL_ARRAY / "five_macro_dc_raw.json").read_text())
    agg = defaultdict(list)
    for r in raw:
        agg[(r["mode"], r["G"], r["r_rail"], r["feed_both"])].append(r)
    ts = json.loads((RP.FULL_COLUMN / "ladder_table_size.json").read_text())["0.72"]
    en = json.loads((RP.FULL_ARRAY / "energy_per_inference.json").read_text())
    rows_out = []
    for mode, W in (("macros=5", 160), ("macros=4", 128), ("macros=3", 96), ("macros=2", 64), ("macros=1", 32), ("bitplane", 20)):
        for rho in (0.0072, 0.00072):
            rows, extra = {}, {}
            for which, G in (("far", 63), ("near", 0)):
                rs = agg[(mode, G, rho, True)]
                rows[which] = dict(gain=min(r["gain_total"] for r in rs), row_std_a=max(r["row_std_a"] for r in rs))
                dyn = _bitplane_dyn(G, 0.5, 200.0) if mode == "bitplane" else _dyn(G, 0.5, 200.0)
                extra[which] = [("supply/ground rail (data dependent)", "deterministic", max(r["rail_inc_maxdev_a"] for r in rs)), ("settling + crosstalk at sampling time", "deterministic", dyn),
                                ("ladder threshold quantisation", "deterministic", Q_LSB_A / 2), ("antisymmetric (half) table storage", "deterministic", 0.5e-6 * (ts["antisym_dev_far_uA"] if which == "far" else ts["antisym_dev_near_uA"])),
                                (f"row-gain correction residual (rank {GAIN_RANK})", "deterministic", gain_residual_a(which, True))]
            b = close_1c(rows, extra)
            ts_close = None
            if mode == "bitplane":                                               # earliest sampling time at which the bit-plane mode closes
                for t in (200, 300, 500, 700, 1000):
                    extra2 = {w: [x if x[0] != "settling + crosstalk at sampling time" else (x[0], x[1], _bitplane_dyn(63 if w == "far" else 0, 0.5, float(t))) for x in extra[w]] for w in extra}
                    if close_1c(rows, extra2)["closes"]:
                        ts_close = t; break
            passes = math.ceil(160 / W)
            reads = cm["reads_160"] * passes
            rows_out.append(dict(mode=mode, W=W, rho=rho, passes=passes, reads=reads, cycles=cm["c0"] + reads, margin_left_a=b["margin_left_a"], margin_frac=b["margin_frac"], closes=b["closes"],
                                 gain_far=rows["far"]["gain"], rail_term_far_a=extra["far"][0][2], dyn_far_a=extra["far"][1][2], earliest_closing_sampling_ps=ts_close,
                                 i_total_far_mA=float(np.mean([r["isup_mean_a"] for r in agg[(mode, 63, rho, True)]]) * 1e3), i_total_near_mA=float(np.mean([r["isup_mean_a"] for r in agg[(mode, 0, rho, True)]]) * 1e3)))
            o = rows_out[-1]
            print(f"W={W:3d} ({mode}, rails {rho}): reads {o['reads']:,.0f} cycles {o['cycles']:,.0f} | margin {o['margin_left_a']*1e6:+.2f} uA ({100*o['margin_frac']:+.1f}%) closes {o['closes']} "
                  f"| dyn@200ps {o['dyn_far_a']*1e6:.3f} uA" + (f" | closes from t_s = {ts_close} ps" if ts_close else "") + f" | I_near {o['i_total_near_mA']:.1f} mA")
    (RP.COLUMN_SENSING / "column_sensing_table.json").write_text(json.dumps(dict(cycle_model=cm, rows=rows_out), indent=1))


if __name__ == "__main__":
    RP.COLUMN_SENSING.mkdir(parents=True, exist_ok=True)
    main()
