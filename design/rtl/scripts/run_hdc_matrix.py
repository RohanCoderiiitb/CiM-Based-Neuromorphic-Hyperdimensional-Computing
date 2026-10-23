#!/usr/bin/env python3
"""The Phase 2-4 regression matrix. Each entry is one run of run_hdc_regression.py (all 240 DVS-Gesture samples unless stated); runs execute concurrently and are resumable
(a run whose results/hdc/<tag>.json exists and says PASS is skipped).

  python scripts/run_hdc_matrix.py --sim verilator [--only prefix ...] [--workers 9]
  python scripts/run_hdc_matrix.py --sim icarus                       # the subset profile: 48 random rows per configuration (Icarus is ~50x slower)
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
RES = ROOT / "results" / "hdc"
GRID = [1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96, 128, 192, 256, 512]       # theta in XNOR-score margin units (software bipolar theta = 2 x)
NEVER = 4095
SEEDS = (0, 1, 2)


def matrix(sim: str) -> list[tuple[str, list[str]]]:
    sub = sim == "icarus"
    rows = ["--rows", "rand24"] if sub else ["--rows", "all"]
    pre = "ic_" if sub else ""
    M = []

    def add(tag, model, seed, f, e, theta=NEVER, extra=()):
        M.append((pre + tag, ["--model", model, "--seed", str(seed), "--factorized", str(f), "--early-exit", str(e), "--theta", str(theta), *rows, *extra, "--sim", sim]))

    # A. Phase 3 (early exit not built): the two class-HV mappings, and the factorized one run through the UNFACTORIZED RTL with the expanded class hypervector (identity test)
    for s in SEEDS:
        add(f"p3_base_s{s}", "base", s, 0, 0)
        add(f"p3_r1fact_s{s}", "r1", s, 1, 0)
        add(f"p3_r1unfact_s{s}", "r1", s, 0, 0)
    # B. early exit built, threshold set so it never fires: must be bit-identical to A
    for s in SEEDS:
        add(f"dis_base_s{s}", "base", s, 0, 1)
        add(f"dis_r1fact_s{s}", "r1", s, 1, 1)
    # C. the theta sweep, in hardware, both models
    grid = [8, 40, 56] if sub else GRID
    for s in SEEDS[:1] if sub else SEEDS:
        for th in grid:
            add(f"sw_r1fact_s{s}_t{th}", "r1", s, 1, 1, th)
            add(f"sw_base_s{s}_t{th}", "base", s, 0, 1, th)
    # D. stress: random inter-event gaps, real AER streams, event order inside a timestep
    for s in SEEDS[:1] if sub else SEEDS:
        M.append((pre + f"l4_real_gaps_s{s}", ["--model", "r1", "--seed", str(s), "--factorized", "1", "--early-exit", "1", "--theta", "56", "--rows", "real", "--gap", "1", "--sim", sim]))
        M.append((pre + f"l4_sorted_gaps_s{s}", ["--model", "r1", "--seed", str(s), "--factorized", "1", "--early-exit", "1", "--theta", "56", "--rows", "rand24" if sub else "rand48", "--gap", "1", "--order", "sorted", "--sim", sim]))
        M.append((pre + f"l4_shuffled_nogap_s{s}", ["--model", "base", "--seed", str(s), "--factorized", "0", "--early-exit", "1", "--theta", "40", "--rows", "rand24" if sub else "rand48", "--order", "shuffle", "--sim", sim]))
    return M


KNEE = {"r1": 50, "base": 56}        # strict knee of the theta sweep (zero accuracy loss at it and at every larger theta), from the reference sweep over theta = 1..240 (see phase234_report.md)
KNEE1 = {"r1": 47, "base": 37}       # the "within one sample (0.14 pp)" knee


def matrix_extra(sim: str) -> list[tuple[str, list[str]]]:
    """The runs the Phase 5 evaluation needs on top of the main matrix: the knee thresholds, the four builds at g = 4, and one 20-column run for the cycle model check."""
    pre = "ic_" if sim == "icarus" else ""
    rows = ["--rows", "rand24" if sim == "icarus" else "all"]
    M = []
    sub = sim == "icarus"

    def add(tag, model, seed, f, e, theta=NEVER, g=8, cols=160):
        M.append((pre + tag, ["--model", model, "--seed", str(seed), "--factorized", str(f), "--early-exit", str(e), "--theta", str(theta), "--g", str(g), "--cols", str(cols), *rows, "--sim", sim]))

    for s in SEEDS[:1] if sub else SEEDS:
        if not sub:
            add(f"sw_r1fact_s{s}_t{KNEE['r1']}", "r1", s, 1, 1, KNEE["r1"])
            add(f"sw_r1fact_s{s}_t{KNEE1['r1']}", "r1", s, 1, 1, KNEE1["r1"])
            add(f"sw_base_s{s}_t{KNEE1['base']}", "base", s, 0, 1, KNEE1["base"])
        # the four ablation builds at their knee, g = 4 (the 1F design point) and g = 8
        for g in (4,) if sub else (4, 8):
            add(f"ab_full_g{g}_s{s}", "r1", s, 1, 1, KNEE["r1"], g)
            add(f"ab_eeoff_g{g}_s{s}", "r1", s, 1, 0, NEVER, g)
            add(f"ab_factoff_g{g}_s{s}", "base", s, 0, 1, KNEE["base"], g)
            add(f"ab_bothoff_g{g}_s{s}", "base", s, 0, 0, NEVER, g)
    M.append((pre + "c20_check_s0", ["--model", "r1", "--seed", "0", "--factorized", "1", "--early-exit", "1", "--theta", str(KNEE["r1"]), "--g", "4", "--cols", "20", "--rows", "rand24", "--sim", sim]))
    return M


def one(item):
    tag, args = item
    f = RES / f"{tag}.json"
    if f.exists() and json.loads(f.read_text())["summary"]["mismatching_samples"] == 0 and json.loads(f.read_text())["summary"]["sim_returncode"] == 0:
        return tag, 0, "skipped (PASS on disk)"
    r = subprocess.run([PY, str(ROOT / "scripts" / "run_hdc_regression.py"), "--tag", tag, *args], capture_output=True, text=True, cwd=ROOT)
    return tag, r.returncode, (r.stdout.strip().splitlines() or ["(no output)"])[0] if r.returncode == 0 else r.stdout[-1500:] + r.stderr[-800:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", default="verilator", choices=["verilator", "icarus"])
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--set", default="main", choices=["main", "extra", "twin"], help="twin: the Icarus subset configurations run on Verilator with identical arguments (tag prefix vt_)")
    a = ap.parse_args()
    RES.mkdir(parents=True, exist_ok=True)
    if a.set == "twin":
        M0 = matrix("icarus") + matrix_extra("icarus")
        M = [("vt_" + t[3:], [x if x != "icarus" else "verilator" for x in args]) for t, args in M0]
    else:
        M = matrix(a.sim) if a.set == "main" else matrix_extra(a.sim)
    M = [m for m in M if not a.only or any(m[0].startswith(o) or m[0][3:].startswith(o) for o in a.only)]
    # build once (serially) so the parallel runs do not race on the cached build
    sys.path.insert(0, str(ROOT / "scripts"))
    import sim_hdc
    sim = "verilator" if a.set == "twin" else a.sim
    for f, e in ((1, 1), (1, 0), (0, 1), (0, 0)):
        for g, cols in ((8, 160), (4, 160), (4, 20)):
            sim_hdc.build(sim, f, e, g, cols)
    t0 = time.time()
    fails = 0
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        for tag, rc, line in ex.map(one, M):
            print(f"[{int(time.time() - t0):5d}s] {line if line.startswith('[') else tag + ': ' + line}", flush=True)
            fails += rc != 0
    print(f"{len(M)} runs, {fails} failed, {time.time() - t0:.0f}s")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
