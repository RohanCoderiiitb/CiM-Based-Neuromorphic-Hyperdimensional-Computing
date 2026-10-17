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
SNN = sorted((RTL / "phase1_snn").glob("*.sv"))
MVM = ROOT / "tb" / "sv" / "mvm_unit.sv"
OUT = ROOT / "results" / "unit_tests"
BUILD = ROOT / "build" / "cocotb"
G_SWEEP = (1, 4, 8, 16, 32, 48, 64, 512)          # 48 does not divide 512; 1 and 512 are the extremes
CASES = [
    # (name, toplevel, test module, parameters, env)
    ("addr_gen", "addr_gen", "test_addr_gen", {}, {}),
    ("event_ctr", "event_ctr", "test_event_ctr", {}, {}),
    ("count_mem", "count_mem", "test_count_mem", {}, {}),
    ("weight_load", "weight_load", "test_weight_load", {}, {}),
    ("spike_reg", "spike_reg", "test_spike_reg", {}, {}),
    ("if_neuron_array", "if_neuron_array", "test_if_neuron", {}, {}),
]
for g, cols, skip in ((8, 160, 1), (48, 160, 1), (1, 160, 1), (512, 160, 1), (8, 20, 1), (8, 160, 0), (64, 20, 1)):
    p = dict(ROWS_PER_GROUP=g, N_PARALLEL_COLS=cols, PLANE_SKIP_EN=skip)
    e = dict(ROWS_PER_GROUP=str(g), N_PARALLEL_COLS=str(cols), PLANE_SKIP_EN=str(skip))
    CASES.append((f"plane_seq_g{g}_c{cols}_s{skip}", "plane_seq", "test_plane_seq", p, e))
for g in (8, 48, 512):
    CASES.append((f"cim_macro_g{g}", "cim_macro", "test_cim_macro", dict(ROWS_PER_GROUP=g), dict(ROWS_PER_GROUP=str(g))))
    CASES.append((f"shift_accum_g{g}", "shift_accum", "test_shift_accum", dict(ROWS_PER_GROUP=g), dict(ROWS_PER_GROUP=str(g))))
for g in G_SWEEP:
    CASES.append((f"mvm_unit_g{g}", "mvm_unit", "test_mvm_unit", dict(ROWS_PER_GROUP=g, N_PARALLEL_COLS=160, PLANE_SKIP_EN=1),
                  dict(ROWS_PER_GROUP=str(g), N_PARALLEL_COLS="160", PLANE_SKIP_EN="1", MVM_OUT=str(OUT / f"mvm_x_g{g}_c160.json"))))
for g, cols, skip in ((8, 20, 1), (64, 20, 1), (8, 160, 0)):
    CASES.append((f"mvm_unit_g{g}_c{cols}_s{skip}", "mvm_unit", "test_mvm_unit", dict(ROWS_PER_GROUP=g, N_PARALLEL_COLS=cols, PLANE_SKIP_EN=skip),
                  dict(ROWS_PER_GROUP=str(g), N_PARALLEL_COLS=str(cols), PLANE_SKIP_EN=str(skip), MVM_OUT=str(OUT / f"mvm_x_g{g}_c{cols}_s{skip}.json"))))


def run_case(sim: str, name: str, top: str, module: str, params: dict, env: dict) -> dict:
    t0 = time.time()
    runner = get_runner(sim)
    sources = [PKG] + SNN + ([MVM] if top == "mvm_unit" else [])
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
