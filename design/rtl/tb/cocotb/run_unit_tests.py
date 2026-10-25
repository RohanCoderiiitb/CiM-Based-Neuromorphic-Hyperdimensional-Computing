#!/usr/bin/env python3
"""Run every Level 2 / Level 3 cocotb test on Verilator and Icarus, then the g-sweep check (X identical at every g).

  python tb/cocotb/run_unit_tests.py [--sims verilator icarus] [--only addr_gen ...]

Results: results/unit_tests/<sim>__<case>.json and results/unit_tests/summary.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tb" / "cocotb"))
from cocotb_tools.runner import get_results, get_runner  # noqa: E402

RTL = ROOT / "rtl"
PKG = RTL / "pkg" / "cim_neurohdc_pkg.sv"
HDC_PKG = RTL / "pkg" / "hdc_pkg.sv"
SNN = sorted((RTL / "common").glob("*.sv")) + sorted((RTL / "phase1_snn").glob("*.sv"))
HDC = sorted((RTL / "phase2_hdc").glob("*.sv")) + sorted((RTL / "phase4_exit").glob("*.sv"))
MVM = ROOT / "tb" / "sv" / "mvm_unit.sv"
T2W = ROOT / "tb" / "sv" / "top2_wrap.sv"
OUT = ROOT / "results" / "unit_tests"
BUILD = ROOT / "build" / "cocotb"
CASES = [
    # (name, toplevel, test module, parameters, env)
    ("addr_gen", "addr_gen", "test_addr_gen", {}, {}),
    ("event_ctr", "event_ctr", "test_event_ctr", {}, {}),
    ("count_mem", "count_mem", "test_count_mem", {}, {}),
    ("weight_load", "weight_load", "test_weight_load", {}, {}),
    ("spike_reg", "spike_reg", "test_spike_reg", {}, {}),
    ("if_neuron_array", "if_neuron_array", "test_if_neuron", {}, {}),
]
for g, cols in ((4, 40), (4, 160), (4, 20), (8, 40), (8, 160), (1, 40), (16, 20), (64, 40), (512, 160)):
    p = dict(ROWS_PER_GROUP=g, N_PARALLEL_COLS=cols)
    e = dict(ROWS_PER_GROUP=str(g), N_PARALLEL_COLS=str(cols))
    CASES.append((f"plane_seq_g{g}_c{cols}", "plane_seq", "test_plane_seq", p, e))
    CASES.append((f"cim_macro_g{g}_c{cols}", "cim_macro", "test_cim_macro", p, e))
    CASES.append((f"shift_accum_g{g}_c{cols}", "shift_accum", "test_shift_accum", p, e))
G_SWEEP = (1, 2, 4, 8, 16, 32, 64, 128, 512)                       # g must divide 512
for g in G_SWEEP:
    CASES.append((f"mvm_unit_g{g}", "mvm_unit", "test_mvm_unit", dict(ROWS_PER_GROUP=g, N_PARALLEL_COLS=40),
                  dict(ROWS_PER_GROUP=str(g), N_PARALLEL_COLS="40", MVM_OUT=str(OUT / f"mvm_x_g{g}_c40.json"))))
for g, cols in ((4, 160), (4, 20), (8, 20), (64, 160)):
    CASES.append((f"mvm_unit_g{g}_c{cols}", "mvm_unit", "test_mvm_unit", dict(ROWS_PER_GROUP=g, N_PARALLEL_COLS=cols),
                  dict(ROWS_PER_GROUP=str(g), N_PARALLEL_COLS=str(cols), MVM_OUT=str(OUT / f"mvm_x_g{g}_c{cols}.json"))))


HDC_TOPS = ("top2_wrap", "exit_ctrl", "hdc_query")
CLKT = ROOT / "tb" / "sv" / "clk_tree_wrap.sv"

# digital-energy pass: the clock-gate tree itself (three shapes: count_mem's 8 x 8 x 8, the 100-row sign table's two levels, a non-power-of-two single level) and the non-default
# parameter settings of the blocks whose structure the pass changed (enabled flip-flops instead of clock gates, no operand isolation)
for n, lv in ((512, 3), (100, 2), (20, 1)):
    CASES.append((f"clk_gate_tree_n{n}_l{lv}", "clk_tree_wrap", "test_clk_gate_tree", dict(N=n, LEVELS=lv), dict(N=str(n))))

# Phase 2-4 blocks (the references are Phase 0 / hdc_query.py, imported by the tests)
for n in (7, 10, 16, 24):
    CASES.append((f"top2_tree_n{n}", "top2_wrap", "test_top2_tree", dict(N=n, W=11, WI=5), dict(N=str(n))))
for ee in (1, 0):
    CASES.append((f"exit_ctrl_ee{ee}", "exit_ctrl", "test_exit_ctrl", dict(EARLY_EXIT_EN=ee), dict(EARLY_EXIT_EN=str(ee))))
for f in (0, 1):
    CASES.append((f"hdc_query_f{f}", "hdc_query", "test_hdc_query", dict(FACTORIZED=f), dict(FACTORIZED=str(f))))
    if f:
        CASES.append((f"hdc_query_f{f}_cg0", "hdc_query", "test_hdc_query", dict(FACTORIZED=f, CLOCK_GATING=0), dict(FACTORIZED=str(f))))
    if f:
        CASES.append((f"hdc_query_f{f}_flopsign", "hdc_query", "test_hdc_query", dict(FACTORIZED=f, SIGN_SRAM=0), dict(FACTORIZED=str(f))))
    CASES.append((f"hdc_query_f{f}_n24", "hdc_query", "test_hdc_query", dict(FACTORIZED=f, N_CLASSES=24), dict(FACTORIZED=str(f), N_CLASSES="24")))     # README Phase 4: N is 10-24


def run_case(sim: str, name: str, top: str, module: str, params: dict, env: dict) -> dict:
    t0 = time.time()
    runner = get_runner(sim)
    sources = [PKG] + SNN + ([MVM] if top == "mvm_unit" else []) + ([CLKT] if top == "clk_tree_wrap" else [])
    if top in HDC_TOPS:
        sources = [PKG, HDC_PKG] + SNN + HDC + ([T2W] if top == "top2_wrap" else [])
    bdir = BUILD / f"{sim}__{name}"
    if sim == "icarus":
        build_args = ["-g2012"]
    else:
        build_args = ["--timing", "-Wno-fatal", "-Wno-lint", "-Wno-style", "-Wno-WIDTH", "-Wno-TIMESCALEMOD", "-Wno-BLKSEQ", "-Wno-STMTDLY", "-Wno-INITIALDLY"]
    try:
        runner.build(sources=sources, hdl_toplevel=top, build_dir=bdir, parameters=params, build_args=build_args, always=True, timescale=("1ns", "1ps"), log_file=str(bdir) + "_build.log")
        res = runner.test(hdl_toplevel=top, test_module=module, timescale=("1ns", "1ps"), test_dir=ROOT / "tb" / "cocotb", build_dir=bdir, test_args=[] if sim == "icarus" else [],
                          extra_env=dict(env, PYTHONPATH=str(ROOT / "tb" / "cocotb")), results_xml=bdir / "results.xml", log_file=str(bdir) + "_test.log")
        n, nfail = get_results(res)
        ok = (nfail == 0 and n > 0)
        err = ""
    except Exception as exc:  # noqa: BLE001
        n, nfail, ok, err = 0, 1, False, f"{type(exc).__name__}: {exc}"
    return dict(sim=sim, case=name, toplevel=top, module=module, parameters=params, tests=n, failed=nfail, ok=bool(ok), error=err, wall_s=round(time.time() - t0, 1))


def g_sweep_check() -> dict:
    """X must be identical at every g (and column mode / skip setting): grouping changes the number of reads, never the answer."""
    runs = {}
    for f in sorted(OUT.glob("mvm_x_g*.json")):
        runs[f.name] = json.loads(f.read_text())
    if not runs:
        return dict(ok=False, error="no mvm_x logs")
    ref_name, ref = next(iter(runs.items()))
    diffs = []
    for name, r in runs.items():
        for v, d in r["vectors"].items():
            if d["X"] != ref["vectors"][v]["X"]:
                diffs.append((name, v))
    reads = {name: {v: d["stats"]["reads_allcols"] for v, d in r["vectors"].items() if v.startswith("real row 0")} for name, r in runs.items()}
    return dict(ok=not diffs, runs=sorted(runs), reference=ref_name, vectors=len(ref["vectors"]), x_differences=diffs, reads_allcols_real_row0=reads)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", nargs="+", default=["verilator", "icarus"])
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for sim in args.sims:
        for name, top, module, params, env in CASES:
            if args.only and not any(name.startswith(o) for o in args.only):
                continue
            r = run_case(sim, name, top, module, params, env)
            results.append(r)
            (OUT / f"{sim}__{name}.json").write_text(json.dumps(r, indent=1))
            print(f"[{'PASS' if r['ok'] else 'FAIL'}] {sim:9s} {name:28s} {r['tests']} tests, {r['wall_s']}s {r['error']}", flush=True)
        sweep = g_sweep_check()
        (OUT / f"g_sweep_{sim}.json").write_text(json.dumps(sweep, indent=1))
        print(f"[{'PASS' if sweep['ok'] else 'FAIL'}] {sim}: g-sweep X identical across {len(sweep.get('runs', []))} runs / {sweep.get('vectors')} vectors")
        results.append(dict(sim=sim, case="g_sweep_identical_X", ok=sweep["ok"]))
    (OUT / "summary.json").write_text(json.dumps(results, indent=1))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
