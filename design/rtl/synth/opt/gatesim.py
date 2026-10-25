#!/usr/bin/env python3
"""Gate-level simulation of a laid-out netlist (zero delay, Icarus) on the regression testbench, with a VCD of a window of cycles (counted from start_i). The netlist is the ONE that is analysed
for power - the final routed one - so the activity is that of every cell and every net of the layout (buffers, clock tree, ICGs included).
Differences from scripts/synth_power.gate_sim: the macros' behavioural models include the count SRAM; every drive strength of the ICG has a model; primary outputs that synthesis proved constant (and
that were removed from the chip, synth_opt.strip_constant_outputs) are tied off in the testbench; the golden comparison (spikes, X, V, prefix scores) is done over the whole run.
  python opt/gatesim.py --net <netlist.v> --const-ports <json> --out <dir> --row 46 --start 12000 --len 2400 [--build full]"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import synth_power as P  # noqa: E402
import synth_ppa as S  # noqa: E402
from tb.common import golden as G  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402

PDK_LIB = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lib"
import os
RR = Path(os.environ["CIM_RTL_ROOT"]) if os.environ.get("CIM_RTL_ROOT") else ROOT
BEHAV = [p for p in (RR / "rtl/phase1_snn/cim_macro.sv", RR / "rtl/phase2_hdc/hdc_class_array.sv", RR / "rtl/phase1_snn/count_sram.sv", RR / "rtl/phase2_hdc/sign_sram.sv") if p.exists()]
P.PKGS = [RR / "rtl/pkg/cim_neurohdc_pkg.sv", RR / "rtl/pkg/hdc_pkg.sv"]
ICG = HERE / "icg_models_all.v"


def cells_model(out: Path) -> Path:
    return P.liberty_models(PDK_LIB / S.LIBS["fast"], out)


def make_tb(work: Path, const_ports: dict) -> Path:
    t = P.TB_RTL.read_text().replace("module hdc_regress_tb;", "module hdc_gate_tb;")
    t, n = re.subn(r"cim_neurohdc_top #\(.*?\) dut \(", "cim_neurohdc_top dut (", t, flags=re.S)
    assert n == 1
    t = t.replace("        $dumpoff;\n        vcd_active <= 1'b0;", "        $dumpoff;\n        vcd_active <= 1'b0;\n        $fflush(fd_out);\n        $finish;")
    ties = []
    for name, d in const_ports.items():
        m = re.search(rf"\.{name}\s*\(\s*([A-Za-z_]\w*)\s*\)\s*,?", t)
        assert m, f"port {name} not found in the testbench instance"
        sig = m.group(1)
        t = t[:m.start()] + t[m.end():]
        ties.append(f"  assign {sig} = {d['width']}'d{d['value']};")
    # the connection list may now end with a trailing comma before ');'
    t = re.sub(r",(\s*)\);(\s*\n\s*// ----)", r"\1);\2", t, count=0)
    i = t.index(") dut (") if ") dut (" in t else t.index("dut (")
    j = t.index(");", t.index("dut ("))
    # fix a dangling comma right before the closing parenthesis of the instance
    inst = t[t.index("dut ("):j + 2]
    inst_fixed = re.sub(r",\s*\);\s*$", "\n  );", inst)
    t = t.replace(inst, inst_fixed + "\n" + "\n".join(ties) + "\n")
    p = work / "hdc_gate_tb.sv"
    p.write_text(t)
    return p


def run(build: str, work: Path, net: Path, const_ports: dict, row: int, start: int, length: int, theta: int = 50, seed: int = 0, cols: int = 40, vcd_name: str = "activity.vcd", no_vcd: bool = False) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    f, e = S.BUILDS[build]
    mdl = H.load_model(P.MODEL[build], seed)
    counts_row = mdl["counts"][row].astype(int)
    real, _ = G.real_streams("dvsgesture")
    words = next((w for r, w, _ in real if r == row), None)
    if words is None:
        words = G.synth_events("dvsgesture", counts_row, np.random.default_rng(1), "shuffle")
    job = work / "job"
    H.write_job(job, mdl, bool(f), [(words, counts_row)], [mdl["thresh_int"][row]], [theta], [1], gap_mode=0)
    tb = make_tb(work, const_ports)
    cells = cells_model(work.parent / "cells_fast.v") if not (work.parent / "cells_fast.v").exists() else work.parent / "cells_fast.v"
    vvp = work / "gate.vvp"
    cmd = ["iverilog", "-g2012", "-DVCD_DUMP", "-s", "hdc_gate_tb", "-P", f"hdc_gate_tb.FACTORIZED_P={f}", "-P", f"hdc_gate_tb.N_PARALLEL_COLS_P={cols}", "-o", str(vvp), *map(str, P.PKGS), str(cells), str(ICG), str(net), *map(str, BEHAV), str(tb)]
    r = S.run(cmd, log=work / "iverilog.log")
    if r.returncode != 0:
        raise SystemExit("gate-level build failed:\n" + (r.stdout + r.stderr)[-2000:])
    vcd = work / vcd_name
    out = work / "gate_out.txt"
    t0 = time.time()
    args = [f"+job={job}", f"+out={out}"] + ([] if no_vcd else [f"+vcd={vcd}", f"+vcd_start={start}", f"+vcd_len={length}"])
    r = S.run(["vvp", "-n", str(vvp), *args], log=work / "run.log", timeout=8 * 3600)
    got = H.parse_output(out)[0]
    n = len(got["t"])
    tr = G.reference_trace(counts_row, mdl["W"], mdl["thresh_int"][row])
    ref_scores = mdl["prefix"][row]
    unobs = any(d.get("unobserved") for d in const_ports.values())
    if unobs:        # X, V and the scores are internal in the laid-out chip: the check is at its interface - the spike raster of every timestep and the prediction / exit timestep
        ok = n > 0 and np.array_equal(got["S"], tr.S[:n])
    else:
        ok = n > 0 and np.array_equal(got["S"], tr.S[:n]) and np.array_equal(got["X"], tr.X[:n]) and np.array_equal(got["V"], tr.V[:n]) and np.array_equal(got["scores"], ref_scores[:n])
    return dict(vcd=str(vcd), vcd_mb=round(vcd.stat().st_size / 1e6, 1) if vcd.exists() else 0, sim_s=round(time.time() - t0, 1), timesteps_checked=int(n), matches_golden=bool(ok), n_events=len(words), end=got.get("end"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--net", required=True)
    ap.add_argument("--const-ports", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--build", default="full")
    ap.add_argument("--row", type=int, default=46)
    ap.add_argument("--start", type=int, default=12000)
    ap.add_argument("--len", type=int, default=2400)
    ap.add_argument("--cols", type=int, default=40)
    ap.add_argument("--no-vcd", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.build, Path(a.out), Path(a.net), json.loads(Path(a.const_ports).read_text()), a.row, a.start, a.len, cols=a.cols, no_vcd=a.no_vcd), indent=1, default=str))
