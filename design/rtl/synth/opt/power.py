#!/usr/bin/env python3
"""Power of a laid-out stage from switching activity: gate-level simulation of THAT stage's netlist (routed.v) -> VCD windows -> OpenSTA (OpenROAD) with the stage's SPEF, FAST library (1.1 V, as every
earlier number) - and the slow library next to it. Phase-resolved: `ing` = 2400 cycles inside the ingest phase of timestep TS of sample ROW, `mvm` = the whole non-ingest part (scan + reads + update) of that
timestep. Writes <run>/power_<stage>.json with total / group powers, the annotated-pin fraction of each window and the windows (sample, start cycle, length).
  python opt/power.py --tag c5 --stage routed [--row 46 --ts 10]"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
sys.path.insert(0, str(HERE))
import gatesim as GS  # noqa: E402

PDK = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm"
OPENROAD = os.environ.get("OPENROAD", os.path.expanduser("~/.cache/cim_neurohdc/openroad_src/build/bin/openroad"))


BUILD_ARGS = {"full": ("r1", 1, 1, 50), "ee_off": ("r1", 1, 0, 4095), "fact_off": ("base", 0, 1, 56), "both_off": ("base", 0, 0, 4095)}


def windows(row: int, ts: int, tag: str = "win", build: str = "full", cols: int = 40) -> dict:
    """phase boundaries of timestep ts from the RTL counters (a run of the same design with the counters on)."""
    t = subprocess.run([str(ROOT.parents[1] / "venv/bin/python"), str(ROOT / "scripts/run_hdc_regression.py"), "--model", BUILD_ARGS[build][0], "--seed", "0", "--factorized", str(BUILD_ARGS[build][1]), "--early-exit", str(BUILD_ARGS[build][2]),
                        "--theta", str(BUILD_ARGS[build][3]), "--rows", str(row), "--g", "4", "--cols", str(cols), "--sim", "verilator", "--tag", f"{tag}{build}c{cols}_{row}"], capture_output=True, text=True, cwd=ROOT)
    rows = [l.split() for l in gzip.open(ROOT / "results" / "hdc" / f"{tag}{build}c{cols}_{row}.out.txt.gz", "rt")]
    tsr = [r for r in rows if r[0] == "TS"]
    start = sum(int(r[53]) for r in tsr[:ts])
    cyc, ing = int(tsr[ts][53]), int(tsr[ts][54])
    return dict(row=row, timestep=ts, ts_start=start, ts_cycles=cyc, ts_ingest_cycles=ing,
                ing=dict(start=start + 300, length=min(2400, ing - 400)), mvm=dict(start=start + ing + 2, length=cyc - ing - 4))


BOUNDARY = ("u_snn.m_data", "u_snn.rd_bits", "u_snn.group_idx", "u_snn.rd_pass", "u_snn.rd_valid", "u_snn.m_valid")


def boundary_toggles(vcd: Path) -> dict:
    """transitions of the nets that cross the crossbar macro's boundary (names as the flat netlist keeps them): the level shifters' activity. bits = width of each group."""
    ids, last, tog = {}, {}, {}
    scope = []
    with open(vcd) as f:
        for line in f:
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                p = line.split()
                nm = p[4].lstrip("\\")
                if scope and scope[-1] == "dut" and any(nm.startswith(b) for b in BOUNDARY):
                    ids.setdefault(p[3], (nm.split("[")[0], int(p[2])))
            elif line.startswith("$enddefinitions"):
                break
        for line in f:
            c = line[0]
            if c in "01xz":
                i = line[1:].strip()
                if i in ids:
                    if last.get(i, c) != c:
                        tog[ids[i][0]] = tog.get(ids[i][0], 0) + 1
                    last[i] = c
            elif c == "b":
                v, i = line[1:].split()
                if i in ids:
                    o = last.get(i)
                    if o is not None and len(o) == len(v):
                        tog[ids[i][0]] = tog.get(ids[i][0], 0) + sum(x != y for x, y in zip(o, v))
                    last[i] = v
    width = {}
    for k, w in ids.values():
        width[k] = width.get(k, 0) + w
    return dict(toggles=tog, bits=width)


def vcd_to_saif(vcd: Path, saif: Path, netlist: Path | None = None) -> int:
    """Convert the gate-level VCD window into a (backward) SAIF file: per net T0 / T1 / TX durations and TC toggle count, for the nets of scope `dut`. Returns the number of nets written."""
    ts_ps, nets, scope = 1, {}, []
    vars_ = {}                                    # vcd id -> list of net names (one per bit, MSB first)
    with open(vcd) as f:
        for line in f:
            if line.startswith("$timescale"):
                tok = (line.split()[1:] if len(line.split()) > 2 else next(f).split())
                num = int("".join(ch for ch in tok[0] if ch.isdigit()) or 1) if not tok[0].isalpha() else 1
                unit = tok[1] if len(tok) > 1 and not tok[0].isalpha() else "".join(ch for ch in tok[0] if ch.isalpha())
                ts_ps = num * {"s": 10**12, "ms": 10**9, "us": 10**6, "ns": 1000, "ps": 1, "fs": 0.001}[unit]
            elif line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                p_ = line.split()
                if scope and scope[-1] == "dut":
                    w, nm = int(p_[2]), p_[4].lstrip("\\")
                    names = [nm] if w == 1 and "[" in nm else ([nm] if w == 1 else [f"{nm}[{i}]" for i in range(w - 1, -1, -1)])
                    if len(p_) > 6 and p_[5].startswith("[") and w == 1:
                        names = [nm + p_[5]]
                    vars_.setdefault(p_[3], names)
            elif line.startswith("$enddefinitions"):
                break
        st = {}                                   # net -> [t0, t1, tx, tc, last_value, last_time]
        t_first, t_end = None, 0
        t = 0
        for line in f:
            c = line[0]
            if c == "#":
                t = int(line[1:])
                if t_first is None:
                    t_first = t
                t_end = t
                continue
            if c in "01xzXZ":
                i, vals = line[1:].strip(), c
            elif c == "b":
                vals, i = line[1:].split()
            else:
                continue
            nm_list = vars_.get(i)
            if nm_list is None:
                continue
            if len(vals) < len(nm_list):
                vals = vals.rjust(len(nm_list), "0")
            for nm, v in zip(nm_list, vals):
                v = v.lower()
                e = st.get(nm)
                if e is None:
                    st[nm] = [0, 0, 0, 0, v, t]
                    continue
                dt = t - e[5]
                if e[4] == "0":
                    e[0] += dt
                elif e[4] == "1":
                    e[1] += dt
                else:
                    e[2] += dt
                if v != e[4] and v in "01" and e[4] in "01":
                    e[3] += 1
                e[4], e[5] = v, t
    t0 = t_first or 0
    dur = max(t_end - t0, 1)
    out = ["(SAIFILE", '(SAIFVERSION "2.0")', '(DIRECTION "backward")', '(DESIGN "cim_neurohdc_top")', '(VENDOR "cim_neurohdc")', '(PROGRAM_NAME "vcd_to_saif")', '(VERSION "1.0")', "(DIVIDER /)",
           f"(TIMESCALE 1 {'ps' if ts_ps == 1 else 'ns' if ts_ps == 1000 else 'ps'})", f"(DURATION {int(dur * (ts_ps if ts_ps in (1, 1000) else 1) / (1 if ts_ps in (1, 1000) else 1))})", "(INSTANCE hdc_gate_tb", "(INSTANCE dut", "(NET"]
    for nm, e in st.items():
        dt = t_end - e[5]
        if e[4] == "0":
            e[0] += dt
        elif e[4] == "1":
            e[1] += dt
        else:
            e[2] += dt
        esc = nm.replace("[", "\\[").replace("]", "\\]")
        out.append(f"({esc} (T0 {e[0]}) (T1 {e[1]}) (TX {e[2]}) (TC {e[3]}) (IG 0))")
    def act(e):
        return f"(T0 {e[0]}) (T1 {e[1]}) (TX {e[2]}) (TC {e[3]}) (IG 0)"

    out.append(")")                                  # closes (NET of the top-level nets
    n_pin = 0
    if netlist is not None:
        # OpenSTA's SAIF reader annotates PINS: a flat design needs one INSTANCE per cell, whose NETs are the cell's pins, carrying the activity of the net they connect to
        txt = re.sub(r"/\*.*?\*/", "", Path(netlist).read_text(), flags=re.S)
        body = txt[txt.index("module cim_neurohdc_top"):]
        body = body[body.index(");") + 2:]
        ref = re.compile(r"\.(\w+)\s*\(\s*((?:\\\S+\s*(?:\[\d+\])?)|(?:[\w$.]+\s*(?:\[\d+\])?))\s*\)")
        for stmt in body.split(";"):
            stmt = stmt.strip()
            if not stmt or stmt.startswith(("wire", "input", "output", "inout", "assign", "endmodule", "supply")):
                continue
            m = re.match(r"(\w+)\s+(\\\S+|\w+)\s*\((.*)\)\s*$", stmt, re.S)
            if not m:
                continue
            inst = m.group(2).lstrip("\\")
            pins = []
            for pn, net in ref.findall(m.group(3)):
                key = re.sub(r"\s+", "", net.lstrip("\\"))
                e = st.get(key)
                if e is not None:
                    pins.append(f"({pn} {act(e)})")
            if pins:
                n_pin += len(pins)
                out.append("(INSTANCE " + inst.replace("[", "\\[").replace("]", "\\]") + " (NET " + " ".join(pins) + "))")
    out.append("))")
    out.append(")")
    saif.write_text("\n".join(out) + "\n")
    return n_pin or len(st)


def sta_power(run: Path, stage: str, w: str, vcd: Path, lib: str, instances: bool = False) -> dict:
    saif = run / "an" / f"{w}.saif"
    (run / "an").mkdir(exist_ok=True)
    n_saif = vcd_to_saif(vcd, saif, run / (stage + '.v'))
    inst = f"report_power -instances [get_cells *] > {run}/an/inst_{w}_{lib}.rpt\n" if instances else ""
    spef = run / f"{stage}_{'fast' if lib == 'fast' else 'slow'}.spef"
    tcl = f"""
read_liberty {PDK / 'lib' / (lib + '_vdd1v0_basicCells.lib')}
foreach l [glob {run}/macro/*.lib] {{ read_liberty $l }}
read_verilog {run / (stage + '.v')}
link_design cim_neurohdc_top
read_sdc {SYNTH / 'constraints' / 'cim_neurohdc_top.sdc'}
set_propagated_clock [all_clocks]
read_spef {spef}
read_saif -scope hdc_gate_tb/dut {saif}
report_activity_annotation > {run}/an/ann_{w}_{lib}.rpt
report_power -digits 7 > {run}/an/power_{w}_{lib}.rpt
{inst}"""
    (run / "an").mkdir(exist_ok=True)
    f = run / "an" / f"pw_{w}_{lib}.tcl"
    f.write_text(tcl)
    r = subprocess.run([str(ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(f)], capture_output=True, text=True)
    (run / "an" / f"pw_{w}_{lib}.log").write_text(r.stdout + r.stderr)
    txt = (run / "an" / f"power_{w}_{lib}.rpt").read_text()
    ann = (run / "an" / f"ann_{w}_{lib}.rpt").read_text()
    tot = re.search(r"^Total\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)
    grp = {m.group(1): [float(m.group(i)) for i in (2, 3, 4, 5)] for m in re.finditer(r"^(Sequential|Combinational|Clock|Macro|Pad)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)}
    # annotation: "Annotated: N  Unannotated: M" style lines
    nums = {k.strip(): int(v) for k, v in re.findall(r"^\s*([A-Za-z ]+?)\s+(\d+)\s*$", ann, re.M)}
    return dict(lib=lib, total_w=float(tot.group(4)), internal_w=float(tot.group(1)), switching_w=float(tot.group(2)), leakage_w=float(tot.group(3)), groups_internal_switching_leakage_total_w=grp, annotation=nums, annotation_report=ann.strip()[-600:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--build", default="full")
    ap.add_argument("--cols", type=int, default=40)
    ap.add_argument("--stage", default="routed")
    ap.add_argument("--row", type=int, default=46)
    ap.add_argument("--ts", type=int, default=10)
    ap.add_argument("--windows", nargs="+", default=["ing", "mvm"])
    ap.add_argument("--no-slow", action="store_true")
    ap.add_argument("--keep-vcd", action="store_true")
    ap.add_argument("--instances", action="store_true", help="also write report_power -instances (per-cell table) of the fast library")
    a = ap.parse_args()
    run = SYNTH / "work" / "opt" / a.tag
    win = windows(a.row, a.ts, build=a.build, cols=a.cols)
    # gate-level netlist for simulation = the stage netlist with the constant outputs removed already (synth_opt)
    const = json.loads((run / "syn" / "const_ports.json").read_text())
    res = dict(tag=a.tag, stage=a.stage, sample_row=a.row, timestep=a.ts, windows=win, power={})
    for w in a.windows:
        d = GS.run(a.build, run / f"gs_{w}", run / f"{a.stage}.v", const, a.row, win[w]["start"], win[w]["length"], theta=BUILD_ARGS[a.build][3], cols=a.cols, vcd_name=f"{w}.vcd")
        pw = {"fast": sta_power(run, a.stage, w, Path(d["vcd"]), "fast", a.instances)}
        if not a.no_slow:
            pw["slow"] = sta_power(run, a.stage, w, Path(d["vcd"]), "slow")
        pw["boundary"] = boundary_toggles(Path(d["vcd"]))
        pw["gate_level_matches_golden"], pw["timesteps_checked"], pw["vcd_mb"] = d["matches_golden"], d["timesteps_checked"], d["vcd_mb"]
        if not a.keep_vcd:
            Path(d["vcd"]).unlink(missing_ok=True)
        res["power"][w] = pw
        print(w, win[w], {k: (round(v["total_w"] * 1e3, 4) if isinstance(v, dict) else v) for k, v in pw.items() if k in ("fast", "slow")}, "golden", d["matches_golden"], flush=True)
    (run / f"power_{a.stage}.json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
