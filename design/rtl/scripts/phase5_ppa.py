#!/usr/bin/env python3
"""Phase 5: the combined PPA of the complete accelerator and the ablation table. Writes design/rtl/results/ppa/phase5_tables.json (everything reports/phase5_ppa.md prints).

What goes in, and where each number comes from
  READS      per timestep, per sample, from the RTL regression logs (results/hdc/ab_*.out.txt.gz): group reads (all 160 columns), reads of groups with no active row (the a = 0 reads),
             cycles, events ingested. Non-zero reads = all reads - zero-group reads. MEASURED on the RTL, up to the timestep each sample actually reached.
  ENERGY/READ  1F (studies/crossbar/results/sense_frontend/recommended_designs.json): per non-zero group read 228 pJ (g = 8, T = 2 ns, 20 columns per pass) / 186 pJ (g = 4, T = 1 ns,
             40 columns per pass), split into array + word line, sense bias, comparators, threshold correction. Carried forward, not re-derived. Reads with a = 0 are assumed to draw
             nothing (the RTL still issues them; recorded, not implemented); the sensitivity if they are issued with the front end powered is reported.
  CYCLES     RTL cycles at 160 columns per read + (passes - 1) per group read for the 1F sensing passes (validated against the RTL's own 20-column run, c20_check).
  DIGITAL    window-average power of the synthesized digital design (gate-level activity, OpenSTA; scripts/synth_power.py) x cycles / 100 MHz.
  HDC ARRAYS modelled from 1F's per-column read cost and 1C's area parts (the class-HV arrays were never designed): [ASSUM] / [MODEL], flagged in the report.
  AREA       digital: Yosys + the 45 nm library, timing-driven mapping with fanout buffering (scripts/synth_ppa.py); SNN array: 1F's table with the 1 nF decoupling; HDC arrays: modelled.
Energy is reported at the full run (100 timesteps) and at the exit point; the difference is the saving attributable to early exit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
from tb.common import hdc_golden as H  # noqa: E402

HDC = ROOT / "results" / "hdc"
PPA = ROOT / "results" / "ppa"
SENSE = REPO / "studies" / "crossbar" / "results" / "sense_frontend"
XBAR = REPO / "studies" / "crossbar" / "results"
F_CLK_HZ = 100e6                       # [S] NeuroHDC-small: 100 MHz
NEUROHDC = dict(area_mm2=0.399, energy_uJ=3.01, f_mhz=100, node_nm=45, dataset="DVS-Gesture")        # as published; the task's reference
SEEDS = (0, 1, 2)
BUILDS = {   # name -> (model, factorized, early exit, tag of the early-exit/knee run, tag of the same model run to the end)
    "full": dict(model="r1", fact=1, ee=1, tag="ab_full_g{g}_s{s}"), "ee_off": dict(model="r1", fact=1, ee=0, tag="ab_eeoff_g{g}_s{s}"),
    "fact_off": dict(model="base", fact=0, ee=1, tag="ab_factoff_g{g}_s{s}"), "both_off": dict(model="base", fact=0, ee=0, tag="ab_bothoff_g{g}_s{s}")}
FULL_RUN_OF = {"full": "ee_off", "ee_off": "ee_off", "fact_off": "both_off", "both_off": "both_off"}
DESIGN = {8: dict(index=1, passes=8, cols=20), 4: dict(index=2, passes=4, cols=40)}      # 1F's recommended_designs.json rows: g = 8 with 20 columns per pass, g = 4 with 40
T_CYCLE_NS = 1e9 / F_CLK_HZ


def per_read(g: int) -> dict:
    d = json.loads((SENSE / "recommended_designs.json").read_text())[DESIGN[g]["index"]]
    e = d["energy"]
    n = e["reads_nonzero"]
    comp = {"array_and_wordline": (e["array_J"] + e["wordline_J"]) / n * 1e12, "sense_bias": e["sense_bias_J"] / n * 1e12, "comparators": e["decision_J"] / n * 1e12,
            "threshold_correction": e["threshold_J"] / n * 1e12}
    idle = e["i_idle_uA"] * 1e-6 * 1.1 * (e["t_en_ns"] + d["T"] * 1e9 + d["tail"] * 1e9) * 1e-9 * 160 * 1e12
    return dict(name=d["name"], per_read_pj=e["per_read_pJ"], components_pj=comp, reads_nonzero_1f=n, total_uJ_1f=e["total_J"] * 1e6, T_ns=d["T"] * 1e9, passes=d["passes"],
                cols_per_pass=160 // d["passes"], decap_nF=d["c_dec"] * 1e9, droop_mV=d["droop_mV"], cycles_skip_a0_1f=d.get("cycles_skip_a0"), idle_bias_per_empty_read_pj=idle,
                active_rows_mean=2.24 if g == 8 else 1.61)


def hdc_array_energy_pj(factorized: int, rows_gated: float, g: int) -> dict:
    """[ASSUM] Class-HV array cost per timestep from 1F's per-column read costs.
    factorized:   10 columns sensed once (AND-popcount of the spike-gated rows): per column sense bias + comparators (1F) + the array energy of the active rows.
    unfactorized: the 20-bit slices of 10 classes read bit by bit (200 single-bit senses, one active row each) for the digital XNOR-popcount."""
    p = per_read(g)
    c = p["components_pj"]
    per_col_sense = (c["sense_bias"] + c["comparators"]) / 160.0
    per_cell = c["array_and_wordline"] / (p["active_rows_mean"] * 160.0)
    if factorized:
        return dict(sense=10 * per_col_sense, array=10 * rows_gated * per_cell, total=10 * (per_col_sense + rows_gated * per_cell))
    return dict(sense=200 * per_col_sense, array=200 * per_cell, total=200 * (per_col_sense + per_cell))


def hdc_array_area_mm2(factorized: int) -> dict:
    """[MODEL] 1C's area parts (area_model.json, baseline variant) scaled to the class-HV arrays: 2T2R cell 0.081 um^2, per row two drivers + word-line buffer + decoder at 1C's
    per-row values, per column the 1F sense periphery (524 um^2, mid), +20 % overhead."""
    am = json.loads((XBAR / "full_array" / "area_model.json").read_text())
    base = am["variants"]["baseline: both-end drivers, R_DRV 10"]["parts_mm2"]
    cell = am["cell_um2"]
    rows = 20 if factorized else 2000
    n_cells = rows * 10
    per_row = base["row_drivers"] * 1e6 / (512 * 5) + base["wordline_buffers"] * 1e6 / 512 + base["row_decoder"] * 1e6 / 512
    sense = 524.0 * 10
    tot = (n_cells * cell + rows * per_row + sense) * 1.2
    return dict(rows=rows, columns=10, cells=n_cells, cell_array_um2=n_cells * cell, rows_periphery_um2=rows * per_row, sense_um2=sense, total_mm2=tot * 1e-6)


def snn_array_area() -> dict:
    a = json.loads((SENSE / "area_table_1f.json").read_text())
    return {k: v["total_mm2"] for k, v in a.items()}


def load_run(tag: str) -> list[dict]:
    """Per-sample records of one regression run (canonical log): stats per timestep + the END record."""
    out = [o for o in H.parse_output(HDC / f"{tag}.out.txt.gz") if o.get("end")]
    recs = []
    for o in out:
        st, e = o["stats"], o["end"]
        recs.append(dict(n_ts=len(o["t"]), reads_all=int(st[:, 4].sum()), zero=int(st[:, 7].sum()), cycles=e["cycles_inf"], events=e["events_ingested"], events_total=e["events_total"],
                         query=e["cycles_query"], rows_gated=float(o["rows_gated"].sum()), pred=e["pred"], early=e["early"], reload=e["reload_cycles"],
                         nz_by_ts=(st[:, 4] - st[:, 7]).astype(int), all_by_ts=st[:, 4].astype(int)))
    return recs


def load_labels_acc(tag: str) -> dict:
    s = json.loads((HDC / f"{tag}.json").read_text())
    return dict(accuracy=s["summary"]["accuracy"], mismatching=s["summary"]["mismatching_samples"], samples=s["summary"]["samples"])


def build_numbers(build: str, g: int, power_mw: dict, synth: dict, power_full: dict) -> dict:
    b = BUILDS[build]
    des, pr = DESIGN[g], per_read(g)
    runs = {s: load_run(b["tag"].format(g=g, s=s)) for s in SEEDS}
    acc = {s: load_labels_acc(b["tag"].format(g=g, s=s)) for s in SEEDS}
    recs = [r for s in SEEDS for r in runs[s]]
    n = len(recs)
    mean = lambda k: float(np.mean([r[k] for r in recs]))      # noqa: E731
    reads_all = np.array([r["reads_all"] for r in recs], float)
    cycles = np.array([r["cycles"] + (des["passes"] - 1) * r["reads_all"] for r in recs], float)                 # as built: the sequencer walks every group read, empty or not
    cycles_skip = np.array([(r["cycles"] - r["reads_all"]) + des["passes"] * (r["reads_all"] - r["zero"]) for r in recs], float)      # 1F's model: only non-zero reads cost cycles (the a = 0 skip)
    nz = np.array([r["reads_all"] - r["zero"] for r in recs], float)
    n_ts = np.array([r["n_ts"] for r in recs], float)
    rg = np.array([r["rows_gated"] for r in recs], float)
    p_dig = power_mw[build] * 1e-3
    pw = power_full[build]
    p_seq = pw["groups_internal_switching_leakage_total_w"]["Sequential"][3]
    alpha = pw.get("flop_activity", {}).get("alpha_q_per_flop_cycle")
    p_gated = (p_dig - p_seq) + p_seq * alpha if alpha is not None else None          # clock edges only where a flop changes (a lower bound, not a design)
    e_read = pr["per_read_pj"] * 1e-12
    e_snn = nz * e_read
    e_dig = p_dig * cycles * T_CYCLE_NS * 1e-9
    e_dig_skip = p_dig * cycles_skip * T_CYCLE_NS * 1e-9
    e_dig_gated = p_gated * cycles * T_CYCLE_NS * 1e-9 if p_gated is not None else None
    e_dig_skip_gated = p_gated * cycles_skip * T_CYCLE_NS * 1e-9 if p_gated is not None else None
    hdc = hdc_array_energy_pj(b["fact"], float(rg.sum() / n_ts.sum()), g)
    e_hdc = n_ts * hdc["total"] * 1e-12
    e_empty = (np.array([r["zero"] for r in recs], float)) * pr["idle_bias_per_empty_read_pj"] * 1e-12
    tot = e_snn + e_dig + e_hdc
    # energy at the MEAN exit timestep, from the mean per-timestep read profile of the same inputs (B), next to the mean of the per-sample energies (A)
    prof = np.mean([r["nz_by_ts"] for s in SEEDS for r in load_run(BUILDS[FULL_RUN_OF[build]]["tag"].format(g=g, s=s))], axis=0)
    prof_all = np.mean([r["all_by_ts"] for s in SEEDS for r in load_run(BUILDS[FULL_RUN_OF[build]]["tag"].format(g=g, s=s))], axis=0)
    tbar = n_ts.mean()
    lo = int(np.floor(tbar)); frac = tbar - lo
    nz_at_mean = prof[:lo].sum() + frac * prof[lo] if lo < len(prof) else prof.sum()
    out = dict(build=build, g=g, model=b["model"], factorized=b["fact"], early_exit=b["ee"], samples=n,
               accuracy_by_seed={str(s): acc[s]["accuracy"] for s in SEEDS}, accuracy_mean=float(np.mean([acc[s]["accuracy"] for s in SEEDS])), rtl_mismatching_samples=int(sum(acc[s]["mismatching"] for s in SEEDS)),
               mean_exit_timestep=float(tbar), mean_events_ingested=mean("events"), mean_events_total=mean("events_total"), mean_events_fraction=float(np.mean([r["events"] / r["events_total"] for r in recs])),
               mean_nonzero_reads=float(nz.mean()), mean_all_reads=mean("reads_all"), mean_zero_reads=mean("zero"), mean_cycles_160col=mean("cycles"), mean_cycles=float(cycles.mean()),
               cycles_query=mean("query"), cycles_events=mean("events"), mean_reload_cycles_per_sample=mean("reload"), exit_fraction_early=float(np.mean([r["early"] for r in recs])),
               energy_uJ=dict(snn_array=float(e_snn.mean() * 1e6), digital=float(e_dig.mean() * 1e6), hdc_array=float(e_hdc.mean() * 1e6), total=float(tot.mean() * 1e6)),
               scenarios_total_uJ=dict(as_built=float(tot.mean() * 1e6), a0_skip=float((e_snn + e_dig_skip + e_hdc).mean() * 1e6),
                                       clock_gated_bound=None if e_dig_gated is None else float((e_snn + e_dig_gated + e_hdc).mean() * 1e6),
                                       a0_skip_and_clock_gated_bound=None if e_dig_skip_gated is None else float((e_snn + e_dig_skip_gated + e_hdc).mean() * 1e6)),
               digital_uJ_scenarios=dict(as_built=float(e_dig.mean() * 1e6), a0_skip=float(e_dig_skip.mean() * 1e6), clock_gated_bound=None if e_dig_gated is None else float(e_dig_gated.mean() * 1e6),
                                         a0_skip_and_clock_gated_bound=None if e_dig_skip_gated is None else float(e_dig_skip_gated.mean() * 1e6)),
               mean_cycles_a0_skip=float(cycles_skip.mean()), flop_activity_alpha=alpha, digital_power_gated_bound_mW=None if p_gated is None else p_gated * 1e3,
               snn_components_uJ={k: float(nz.mean() * v * 1e-12 * 1e6) for k, v in pr["components_pj"].items()},
               energy_if_empty_reads_issued_uJ=dict(extra=float(e_empty.mean() * 1e6), total=float((tot + e_empty).mean() * 1e6)),
               energy_at_mean_exit_timestep_snn_uJ=float(nz_at_mean * e_read * 1e6), digital_power_mW=power_mw[build], hdc_array_pj_per_timestep=hdc,
               area_digital_mm2=synth[build]["buf_fast"]["area_um2"] * 1e-6, flip_flops=synth[build]["buf_fast"]["flip_flops"], cells=synth[build]["buf_fast"]["cells"])
    return out


def cycle_model_check() -> dict | None:
    """The multi-pass cycle model (cycles at 160 columns + (passes - 1) x group reads) against the RTL's own 20-column run (8 passes), same samples, same threshold."""
    f20, f160 = HDC / "c20_check_s0.json", HDC / "ab_full_g4_s0.json"
    if not (f20.exists() and f160.exists()):
        return None
    a = {p["row"]: p for p in json.loads(f160.read_text())["samples"]}
    b = json.loads(f20.read_text())["samples"]
    err = []
    for p in b:
        q = a.get(p["row"])
        if q and p.get("ok") and q.get("ok") and p["n_timesteps"] == q["n_timesteps"]:
            err.append(p["cycles_inf"] - (q["cycles_inf"] + 7 * q["group_reads_allcols"]))
    return dict(samples=len(err), model="cycles_160col + 7 x group_reads_allcols (g = 4, 8 passes of 20 columns)", max_abs_error_cycles=int(np.max(np.abs(err))) if err else None,
                mean_error_cycles=float(np.mean(err)) if err else None, mean_cycles_rtl=float(np.mean([p["cycles_inf"] for p in b])))


def main() -> int:
    synth = {b: json.loads((PPA / b / "summary.json").read_text()) for b in BUILDS}
    power_full = {b: json.loads((PPA / b / "power" / "power_summary.json").read_text()) for b in BUILDS}
    power = {b: power_full[b]["total_w"] * 1e3 for b in BUILDS}
    res: dict = {"neurohdc_small": NEUROHDC, "f_clk_hz": F_CLK_HZ, "per_read": {str(g): per_read(g) for g in (8, 4)}, "digital_power_mW": power,
                 "snn_array_area_mm2": snn_array_area(), "hdc_array_area_mm2": {"factorized": hdc_array_area_mm2(1), "unfactorized": hdc_array_area_mm2(0)}, "builds": {}}
    for g in (4, 8):
        for b in BUILDS:
            res["builds"][f"{b}_g{g}"] = build_numbers(b, g, power, synth, power_full)
    res["cycle_model_check"] = cycle_model_check()
    area_snn = res["snn_array_area_mm2"]["c_dec=1nF|mid"] if "c_dec=1nF|mid" in res["snn_array_area_mm2"] else None
    for k, v in res["builds"].items():
        hd = res["hdc_array_area_mm2"]["factorized" if v["factorized"] else "unfactorized"]["total_mm2"]
        v["area_mm2"] = dict(digital=v["area_digital_mm2"], snn_array_1nF=area_snn, hdc_array=hd, total=v["area_digital_mm2"] + (area_snn or 0) + hd)
    (PPA / "phase5_tables.json").write_text(json.dumps(res, indent=1, default=float))
    for k, v in res["builds"].items():
        print(f"{k:12s} acc {v['accuracy_mean'] * 100:5.2f}%  exit t {v['mean_exit_timestep']:6.2f}  nz reads {v['mean_nonzero_reads']:8.0f}  cycles {v['mean_cycles']:9.0f}  "
              f"E {v['energy_uJ']['total']:.3f} uJ (snn {v['energy_uJ']['snn_array']:.3f}, dig {v['energy_uJ']['digital']:.3f}, hdc {v['energy_uJ']['hdc_array']:.4f})  area {v['area_mm2']['total']:.3f} mm2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
