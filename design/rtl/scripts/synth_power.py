#!/usr/bin/env python3
"""Phase 5(a), power: switching-activity power of the SYNTHESIZED digital design, per ablation build, from a GATE-LEVEL simulation.

Why gate level. The FFT project annotated an RTL-simulation VCD onto the netlist by net name and got ~2 % of the pins matched; here (Yosys renames every internal net) the RTL VCD
matched 1.5 % even with the hierarchy kept, and OpenSTA then propagates a default activity through the rest: a power number from that is not worth reporting. So instead:
  1. the Yosys netlist is simulated as it is - Icarus, the liberty cells turned into Verilog models by Yosys' own read_liberty, the two analog arrays as their behavioural models -
     under the SAME testbench and stimulus as the RTL regression (hdc_regress_tb, a real DVS-Gesture sample), with $dumpvars on a window of cycles;
  2. the VCD's net names are the netlist's net names, so OpenSTA's read_vcd annotates (nearly) every pin; report_power then needs no activity propagation;
  3. the timesteps the gate-level run completes are compared against the golden model (spikes, X, V, scores): the netlist is functionally the RTL (post-synthesis equivalence on real data).
Power is DIGITAL ONLY (the analog arrays are zero-power black boxes here; Phase 5(b) adds them) and the clock network is ideal: no clock tree, so the clock-tree power is NOT
included - the same convention as the FFT project's flow. The window average is the figure of merit; the report says how the window was chosen.

Usage: python design/rtl/scripts/synth_power.py [--builds full ...] [--row 46] [--start 12000] [--len 8000]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import synth_ppa as S  # noqa: E402
from tb.common import golden as G  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402

MODEL = {"full": "r1", "ee_off": "r1", "fact_off": "base", "both_off": "base"}
PKGS = [ROOT / "rtl/pkg/cim_neurohdc_pkg.sv", ROOT / "rtl/pkg/hdc_pkg.sv"]
BEHAV = [ROOT / "rtl/phase1_snn/cim_macro.sv", ROOT / "rtl/phase2_hdc/hdc_class_array.sv"]
TB_RTL = ROOT / "tb/sv/hdc_regress_tb.sv"


def liberty_models(lib: Path, out: Path) -> Path:
    if not out.exists():
        r = S.run(["yosys", "-q", "-p", f"read_liberty -ignore_miss_func -ignore_miss_dir {lib}; write_verilog -noattr {out}"], log=out.with_suffix(".log"))
        if r.returncode != 0:
            raise SystemExit("liberty -> verilog failed: " + r.stderr[-500:])
    return out


def gate_tb(work: Path) -> Path:
    t = TB_RTL.read_text().replace("module hdc_regress_tb;", "module hdc_gate_tb;")
    t, n = re.subn(r"cim_neurohdc_top #\(.*?\) dut \(", "cim_neurohdc_top dut (", t, flags=re.S)
    assert n == 1, "could not strip the parameter list of the DUT"
    t = t.replace("        $dumpoff;\n        vcd_active <= 1'b0;", "        $dumpoff;\n        vcd_active <= 1'b0;\n        $fflush(fd_out);\n        $finish;")
    p = work / "hdc_gate_tb.sv"
    p.write_text(t)
    return p


def gate_sim(build: str, work: Path, net_raw: Path, cells: Path, row: int, start: int, length: int, theta: int, seed: int = 0) -> dict:
    f, e = S.BUILDS[build]
    mdl = H.load_model(MODEL[build], seed)
    counts_row = mdl["counts"][row].astype(int)
    real, _ = G.real_streams("dvsgesture")
    words = next((w for r, w, _ in real if r == row), None)
    if words is None:
        words = G.synth_events("dvsgesture", counts_row, np.random.default_rng(1), "shuffle")
    job = work / "vcd_job"
    H.write_job(job, mdl, bool(f), [(words, counts_row)], [mdl["thresh_int"][row]], [theta], [1], gap_mode=0)
    tb = gate_tb(work)
    vvp = work / "gate.vvp"
    cmd = ["iverilog", "-g2012", "-DVCD_DUMP", "-s", "hdc_gate_tb", "-P", f"hdc_gate_tb.FACTORIZED_P={f}", "-o", str(vvp), *map(str, PKGS), str(cells), str(net_raw), *map(str, BEHAV), str(tb)]
    r = S.run(cmd, log=work / "iverilog_gate.log")
    if r.returncode != 0:
        raise SystemExit("gate-level build failed:\n" + (r.stdout + r.stderr)[-1500:])
    vcd = work / "activity.vcd"
    t0 = time.time()
    out = work / "gate_out.txt"
    r = S.run(["vvp", "-n", str(vvp), f"+job={job}", f"+out={out}", f"+vcd={vcd}", f"+vcd_start={start}", f"+vcd_len={length}"], log=work / "gate_run.log", timeout=6 * 3600)
    if not vcd.exists():
        raise SystemExit("gate-level run produced no VCD:\n" + (r.stdout + r.stderr)[-800:])
    # post-synthesis equivalence on the timesteps that completed: spikes, X, V and the prefix scores against the golden model
    got = H.parse_output(out)[0]
    n = len(got["t"])
    tr = G.reference_trace(counts_row, mdl["W"], mdl["thresh_int"][row])
    ref_scores = mdl["prefix"][row]
    ok = n > 0 and np.array_equal(got["S"], tr.S[:n]) and np.array_equal(got["X"], tr.X[:n]) and np.array_equal(got["V"], tr.V[:n]) and np.array_equal(got["scores"], ref_scores[:n])
    return dict(vcd=vcd, vcd_mb=round(vcd.stat().st_size / 1e6, 1), gate_sim_s=round(time.time() - t0, 1), timesteps_checked=int(n), gate_level_matches_golden=bool(ok), n_events=len(words))


FF_RE = re.compile(r"\b((?:E|S|SE)?DFF\w*)\s+(\S+)\s*\((.*?)\);", re.S)


def flop_activity(vcd: Path, net_raw: Path, cycles: int) -> dict:
    """Switching activity of the flip-flops over the window, from the gate-level VCD: how many flops ever change, the total number of Q transitions, and the same by module (the RTL
    instance prefix of the Q net). A flop whose Q does not change in a cycle needs no clock edge in that cycle: the Q transition count is the lower bound of the clock edges an ideally
    clock-gated implementation would still need. (The ungated design clocks every flop every cycle; OpenSTA's sequential power is dominated by exactly that.)
    Yosys netlist Q nets are scalars (`\\u_snn.seq_done `) or bit-selects (`\\u_snn.u_event_ctr.acc_q [3]`); Icarus' VCD declares the vectors whole (`$var wire 22 id \\...acc_q [21:0]`)."""
    need: dict[str, set] = {}
    n_flops = 0
    for m in FF_RE.finditer(net_raw.read_text()):
        q = re.search(r"\.Q\(\s*(.*?)\s*\)\s*,?\s*(?:\.|$)", m.group(3), re.S)
        if not q:
            continue
        n_flops += 1
        nm = q.group(1).strip().lstrip("\\").strip()
        bit = re.match(r"(.*?)\s*\[(\d+)\]$", nm)
        if bit:
            need.setdefault(bit.group(1).replace(" ", ""), set()).add(int(bit.group(2)))
        else:
            need.setdefault(nm.replace(" ", ""), set()).add(None)
    vec: dict[str, tuple] = {}            # id -> (base name, width, lsb)
    state: dict[tuple, int] = {}          # (id) -> last integer value (for vectors) / bit for scalars
    toggles: dict[tuple, int] = {}        # (base, bit) -> transitions
    in_defs = True
    with open(vcd) as fh:
        for line in fh:
            if in_defs:
                if line.startswith("$var"):
                    f = line.split()
                    width, vid, toks = int(f[2]), f[3], f[4:-1]
                    rng_ = re.match(r"\[(\d+):(\d+)\]$", toks[-1]) if toks else None
                    if rng_ and width > 1:
                        base, lsb = " ".join(toks[:-1]).lstrip("\\").replace(" ", ""), int(rng_.group(2))
                    else:
                        base, lsb = " ".join(toks).lstrip("\\").replace(" ", ""), 0
                        m2 = re.match(r"(.*)\[(\d+)\]$", base)
                        if width == 1 and m2 and m2.group(1) in need and int(m2.group(2)) in need[m2.group(1)]:
                            base, lsb = m2.group(1), int(m2.group(2))
                    if base in need:
                        vec[vid] = (base, width, lsb)
                elif line.startswith("$enddefinitions"):
                    in_defs = False
                continue
            c = line[0]
            if c == "b" or c == "B":
                val, vid = line[1:].split()
                if vid not in vec:
                    continue
                base, width, lsb = vec[vid]
                if any(ch in "xXzZ" for ch in val):
                    state[vid] = None
                    continue
                v = int(val, 2)
                old = state.get(vid)
                if old is not None:
                    diff = old ^ v
                    for bit in need[base]:
                        if bit is not None and diff >> (bit - lsb) & 1:
                            toggles[(base, bit)] = toggles.get((base, bit), 0) + 1
                state[vid] = v
            elif c in "01xzXZ":
                vid = line[1:].strip()
                if vid not in vec:
                    continue
                base, width, lsb = vec[vid]
                v = None if c in "xXzZ" else int(c)
                old = state.get(vid)
                if old is not None and v is not None and old != v:
                    key = (base, lsb if lsb else None) if None not in need[base] else (base, None)
                    toggles[key] = toggles.get(key, 0) + 1
                state[vid] = v
    by_mod: dict[str, dict] = {}
    n_matched = 0
    for base, bits in need.items():
        for bit in bits:
            key = (base, bit)
            n_matched += 1
            mod = ".".join(base.split(".")[:2]) if base.startswith("u_snn.") else base.split(".")[0]
            d = by_mod.setdefault(mod, dict(flops=0, toggling=0, toggles=0))
            d["flops"] += 1
            d["toggles"] += toggles.get(key, 0)
            d["toggling"] += toggles.get(key, 0) > 0
    tot_tog = sum(toggles.values())
    return dict(flops_in_netlist=n_flops, flops_counted=n_matched, flops_that_toggle=sum(1 for v in toggles.values() if v), q_toggles=tot_tog, window_cycles=cycles,
                alpha_q_per_flop_cycle=tot_tog / max(1, n_matched) / cycles, by_module=by_mod)


def sta_power(work: Path, net_sta: Path, libs: list[Path], period: float, vcd: Path, scope: str) -> dict:
    rpt, ann = work / "power.rpt", work / "annotation.rpt"
    tcl = "\n".join([*(f"read_liberty {l}" for l in libs), f"read_verilog {net_sta}", f"link_design {S.TOP}", f"create_clock -name clk -period {period} [get_ports {S.CLK}]",
                     f"read_vcd -scope {scope} {vcd}", f"report_activity_annotation > {ann}", f"report_power > {rpt}", "exit"]) + "\n"
    (work / "power.tcl").write_text(tcl)
    r = S.run([str(ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(work / "power.tcl")], cwd=work, log=work / "power.log", timeout=7200)
    txt = rpt.read_text() if rpt.exists() else ""
    a = ann.read_text() if ann.exists() else ""
    tot = re.search(r"^Total\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)
    grp = {m.group(1): [float(m.group(i)) for i in (2, 3, 4, 5)] for m in re.finditer(r"^(Sequential|Combinational|Clock|Macro|Pad)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)}
    ann_m = {k: int(v) for k, v in re.findall(r"^\s*(vcd|saif|unannotated|input)\s+(\d+)", a, re.M)}
    warn = [l for l in (r.stdout + r.stderr).splitlines() if "Warning" in l][:6]
    return dict(returncode=r.returncode, total_w=float(tot.group(4)) if tot else None, internal_w=float(tot.group(1)) if tot else None, switching_w=float(tot.group(2)) if tot else None,
                leakage_w=float(tot.group(3)) if tot else None, groups_internal_switching_leakage_total_w=grp, annotation=ann_m, warnings=warn, report=str(rpt))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", nargs="+", default=list(S.BUILDS))
    ap.add_argument("--row", type=int, default=46, help="golden row of the sample simulated (46: a real AER stream with 319,130 events, near the median 334,643)")
    ap.add_argument("--start", type=int, default=12000, help="first cycle of the activity window, counted from start_i (timestep ~3 of the sample)")
    ap.add_argument("--len", type=int, default=8000)
    ap.add_argument("--theta", type=int, default=4095)
    ap.add_argument("--period", type=float, default=10.0)
    ap.add_argument("--lib-dir", default=str(S.DEFAULT_LIB_DIR))
    a = ap.parse_args()
    lib = Path(a.lib_dir) / S.LIBS["fast"]
    gl = S.OUT / "gl"
    gl.mkdir(parents=True, exist_ok=True)
    cells = liberty_models(lib, gl / "cells_fast.v")
    for b in a.builds:
        f, e = S.BUILDS[b]
        work = S.OUT / b / "power"
        work.mkdir(parents=True, exist_ok=True)
        stub = S.stub_liberty(work, f, e)
        t0 = time.time()
        net, _, area, stat = S.synth(work, lib, f, e, True, "flat_buf_fast", a.period, True)       # the very netlist the area / timing numbers come from
        net_raw = net.with_name(net.stem + "_raw.v")
        g = gate_sim(b, work, net_raw, cells, a.row, a.start, a.len, a.theta)
        r = sta_power(work, net, [lib, stub], a.period, g["vcd"], "hdc_gate_tb/dut")
        try:
            r["flop_activity"] = flop_activity(g["vcd"], net_raw, a.len)
        except Exception as exc:  # noqa: BLE001
            r["flop_activity"] = dict(error=f"{type(exc).__name__}: {exc}")
        r.update(build=b, model=MODEL[b], row=a.row, window_start=a.start, window_cycles=a.len, area_um2=area, **{k: v for k, v in g.items() if k != "vcd"}, wall_s=round(time.time() - t0))
        (work / "power_summary.json").write_text(json.dumps(r, indent=1))
        g["vcd"].unlink()                      # hundreds of MB; regenerable
        print(f"[{b}] power {None if r['total_w'] is None else round(r['total_w'] * 1e3, 3)} mW (internal {r['internal_w']}, switching {r['switching_w']}, leakage {r['leakage_w']}), "
              f"annotation {r['annotation']}, gate-level matches golden over {g['timesteps_checked']} timesteps: {g['gate_level_matches_golden']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
