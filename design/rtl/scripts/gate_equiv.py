#!/usr/bin/env python3
"""Post-synthesis equivalence on WHOLE inferences: the synthesized (and clock-gated) netlist of each build is simulated at gate level (Icarus, zero delay, the library cells as Verilog models,
the ICG as tb/gl/icg_models.v) with the very testbench and stimulus of the RTL regression, one real DVS-Gesture sample per process, from the first event to the prediction, and every timestep
is compared with the golden model exactly as run_hdc_regression.py compares the RTL: spikes, X, V, the N prefix scores, leader, second score, the fire flag, the prediction, the exit timestep
and the number of events ingested. The 8,000-cycle power window of synth_power.py checks 5 timesteps; this checks all of them, up to the exit.

  python design/rtl/scripts/gate_equiv.py --builds full ee_off fact_off both_off --gate 4 --rtl-gating 1 --instr 0 --out ppa_gated --rows 46,1,2,11 [--workers 8]
Writes <out>/<build>/gate_equiv.json. The netlist is the one synth_power.py leaves in <out>/<build>/power/ (it is synthesized here when absent).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import run_hdc_regression as R  # noqa: E402
import synth_power as P  # noqa: E402
import synth_ppa as S  # noqa: E402
from tb.common import golden as G  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402

THETA = {"r1": 50, "base": 56}          # the strict knee of the theta sweep (same as run_hdc_matrix.KNEE)
NEVER = 4095


def build_vvp(work: Path, net_raw: Path, cells: Path, factorized: int) -> Path:
    tb = P.gate_tb(work)
    vvp = work / "gate_full.vvp"
    cmd = ["iverilog", "-g2012", "-s", "hdc_gate_tb", "-P", f"hdc_gate_tb.FACTORIZED_P={factorized}", "-o", str(vvp), *map(str, P.PKGS), str(cells),
           *([str(P.ICG_MODEL)] if "TLATNCAX" in net_raw.read_text() else []), str(net_raw), *map(str, P.BEHAV), str(tb)]
    r = S.run(cmd, log=work / "iverilog_gate_full.log")
    if r.returncode != 0:
        raise SystemExit("gate-level build failed:\n" + (r.stdout + r.stderr)[-1500:])
    return vvp


def one(args) -> dict:
    build, row, vvp, work, theta = args
    f, e = S.BUILDS[build]
    mdl = H.load_model(P.MODEL[build], 0)
    counts_row = mdl["counts"][row].astype(np.int64)
    real, _ = G.real_streams("dvsgesture")
    words = next((w for r, w, _ in real if r == row), None)
    if words is None:
        words = G.synth_events("dvsgesture", counts_row, np.random.default_rng(1), "shuffle")
    job = work / f"ge_job_{row}"
    H.write_job(job, mdl, bool(f), [(words, counts_row)], [mdl["thresh_int"][row]], [theta], [1], gap_mode=0)
    out = job / "out.txt"
    t0 = time.time()
    r = S.run(["vvp", "-n", str(vvp), f"+job={job}", f"+out={out}"], log=job / "run.log", timeout=12 * 3600)
    got = H.parse_output(out) if out.exists() else []
    rec = dict(build=build, row=row, theta=theta, n_events=len(words), wall_s=round(time.time() - t0), returncode=r.returncode)
    if not got or got[0].get("end") is None:
        rec.update(ok=False, first=["no output"], assertions=None)
        return rec
    g0 = got[0]
    cmp_ = R.compare_sample(mdl, row, counts_row, mdl["thresh_int"][row], g0, theta, bool(e) and theta != NEVER, len(words), 8, 160, check_instr=bool(S.CFG["instr"]))
    log = (job / "run.log").read_text()
    rec.update(ok=bool(cmp_["ok"]), first=cmp_["first"], timesteps=len(g0["t"]), t_exit=cmp_["t_exit"], pred=g0["end"]["pred"], ref_pred=cmp_["ref_pred"], early=g0["end"]["early"],
               assertions=log.count("[ASSERT FAIL]"))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", nargs="+", default=list(S.BUILDS))
    ap.add_argument("--rows", default="46,1,2,11", help="golden rows of the samples simulated")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--lib-dir", default=str(S.DEFAULT_LIB_DIR))
    S.add_flow_args(ap)
    a = ap.parse_args()
    S.apply_flow_args(a)
    rows = [int(x) for x in a.rows.split(",")]
    lib = Path(a.lib_dir) / S.LIBS["fast"]
    gl = S.OUT / "gl"
    gl.mkdir(parents=True, exist_ok=True)
    cells = P.liberty_models(lib, gl / "cells_fast.v")
    jobs, vvps = [], {}
    for b in a.builds:
        f, e = S.BUILDS[b]
        work = S.OUT / b / "power"
        work.mkdir(parents=True, exist_ok=True)
        net_raw = work / "cim_neurohdc_top_flat_buf_fast_raw.v"
        if not net_raw.exists():
            S.stub_liberty(work, f, e)
            S.synth(work, lib, f, e, True, "flat_buf_fast", 10.0, True)
        vvps[b] = build_vvp(work, net_raw, cells, f)
        theta = THETA[P.MODEL[b]] if e else NEVER
        jobs += [(b, r, vvps[b], work, theta) for r in rows]
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, jobs))
    for b in a.builds:
        rb = [r for r in res if r["build"] == b]
        out = dict(build=b, gate=S.CFG["gate"], rtl_gating=S.CFG["rtl_gating"], instr=S.CFG["instr"], isolate=S.CFG["isolate"], samples=rb, all_ok=all(r["ok"] and r.get("assertions") == 0 for r in rb),
                   timesteps_compared=sum(r.get("timesteps", 0) for r in rb))
        (S.OUT / b / "gate_equiv.json").write_text(json.dumps(out, indent=1))
        print(f"[{b}] gate-level vs golden, whole inferences: {sum(r['ok'] for r in rb)}/{len(rb)} samples bit-exact, {out['timesteps_compared']} timesteps, "
              f"assertion messages {[r.get('assertions') for r in rb]}, exits {[r.get('t_exit') for r in rb]}, wall {[r['wall_s'] for r in rb]} s", flush=True)
    print(f"{len(res)} runs, {time.time() - t0:.0f} s")
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
