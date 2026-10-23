#!/usr/bin/env python3
"""Phase 5(a): synthesis of the complete digital design (Phase 1E SNN + Phase 2 query + Phase 4 exit) at 45 nm, for the four ablation builds.

The flow is the one the FFT project used (ASIC-Optimization-FFT-Hardware/fp16_baseline/synth/run_fp16_synthesis.py), step for step:
  1. Yosys: read the RTL, black-box the analog arrays, elaborate, FLATTEN, proc / opt -purge / memory / async2sync / techmap / dfflibmap / abc -liberty (no timing-driven
     mapping unless --abc-d is given) / opt_clean -purge / setundef -zero -undriven, `stat -liberty` -> chip area.
  2. OpenSTA, timing: read the standard-cell liberty, create a clock, input/output delay = period/4, reset input false-pathed, report_checks -path_delay max.
  3. Power: Yosys again WITHOUT flatten (hierarchy kept so the RTL instance names survive), the testbench's switching activity captured as a VCD (Icarus, one window of a real
     inference) and annotated with OpenSTA before report_power. Done by synth_power.py; this script only builds the netlists.
Standard cells: Cadence 45 nm `fast_vdd1v0_basicCells.lib` (1.1 V, nominal temperature 0 C) - the FFT project's choice, so the numbers are comparable; `--lib slow` also runs timing
at the slow corner. NO PDK file is copied into this repository: the library is read from the sibling FFT project (override with --lib-dir).

The analog arrays (cim_macro, hdc_class_array) are black boxes. OpenSTA needs a cell for them, so a stub liberty is GENERATED from the port lists: zero area, zero power, outputs
launched by clk_i with a clk->Q arc of ARRAY_CLK_TO_Q_NS (the analog read finishes inside its own window and the digital side sees registered counts, 1E's MACRO_LAT = 1).
Their area / energy are the analog models' business (Phase 5(b)); everything reported by this script is DIGITAL.

Usage:  python design/rtl/scripts/synth_ppa.py [--builds full ee_off fact_off both_off] [--period 10] [--lib fast slow]
Output: design/rtl/results/ppa/<build>/ (yosys log, netlists, STA reports) and design/rtl/results/ppa/synthesis_summary.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = ROOT / "results" / "ppa"
DEFAULT_LIB_DIR = REPO.parent / "ASIC-Optimization-FFT-Hardware" / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lib"
LIBS = {"fast": "fast_vdd1v0_basicCells.lib", "slow": "slow_vdd1v0_basicCells.lib"}
RTL = (sorted((ROOT / "rtl" / "pkg").glob("*.sv")) + sorted((ROOT / "rtl" / "phase1_snn").glob("*.sv")) + sorted((ROOT / "rtl" / "phase2_hdc").glob("*.sv"))
       + sorted((ROOT / "rtl" / "phase4_exit").glob("*.sv")) + sorted((ROOT / "rtl" / "phase3_top").glob("*.sv")))
TOP = "cim_neurohdc_top"
BUILDS = {"full": (1, 1), "ee_off": (1, 0), "fact_off": (0, 1), "both_off": (0, 0)}      # name -> (FACTORIZED, EARLY_EXIT_EN)
ANALOG = ("cim_macro", "hdc_class_array")
ARRAY_CLK_TO_Q_NS = 0.3          # [ASSUM] launch time of the black boxes' outputs after the clock edge
CLK = "clk_i"


def run(cmd, cwd=None, log=None, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if log:
        Path(log).write_text(r.stdout + r.stderr)
    return r


def params_cmd(factorized: int, early: int) -> str:
    return f"chparam -set FACTORIZED {factorized} -set EARLY_EXIT_EN {early} -set INSTRUMENT_EN 0 -set CHECK_UNIPOLAR 0 {TOP}"


def read_cmds() -> str:
    return "\n".join(f"read_verilog -sv {f}" for f in RTL)         # cim_macro / hdc_class_array are (* blackbox *) under the SYNTHESIS define that Yosys sets itself


def stub_liberty(work: Path, factorized: int, early: int) -> Path:
    """A liberty stub for every analog black box, generated from the port lists Yosys reports for this very elaboration."""
    js = work / "ports.json"
    run(["yosys", "-q", "-p", f"{read_cmds()}\n{params_cmd(factorized, early)}\nhierarchy -check -top {TOP}\nproc\nwrite_json {js}"], log=work / "ports.log")
    mods = json.loads(js.read_text())["modules"]
    lines = ["library (analog_blackboxes) {", "  delay_model : table_lookup;", "  time_unit : \"1ns\";", "  capacitive_load_unit (1,pf);", "  voltage_unit : \"1V\";", "  current_unit : \"1mA\";",
             "  leakage_power_unit : \"1pW\";", "  pulling_resistance_unit : \"1kohm\";", "  nom_voltage : 1.1;", "  default_cell_leakage_power : 0;",
             "  lu_table_template (scalar) { variable_1 : input_net_transition; index_1 (\"0.1\"); }"]
    widths = sorted({len(p["bits"]) for m in ANALOG if m in mods for p in mods[m]["ports"].values() if len(p["bits"]) > 1})
    for w in widths:
        lines.append(f"  type (bus{w}) {{ base_type : array; data_type : bit; bit_width : {w}; bit_from : {w - 1}; bit_to : 0; }}")
    for m in ANALOG:
        if m not in mods:
            continue
        lines += [f"  cell ({m}) {{", "    area : 0;", "    dont_touch : true;"]
        for name, p in mods[m]["ports"].items():
            w = len(p["bits"])
            kind = "bus" if w > 1 else "pin"
            head = f"{kind} ({name})" + (f" {{ bus_type : bus{w};" if w > 1 else " {")
            if p["direction"] == "input":
                lines.append(f"    {head} direction : input; capacitance : 0.002; }}")
            else:
                lines.append(f"    {head} direction : output; capacitance : 0;")
                lines.append(f"      timing () {{ related_pin : \"{CLK}\"; timing_type : rising_edge; timing_sense : non_unate;"
                             f" cell_rise (scalar) {{ index_1 (\"0.1\"); values (\"{ARRAY_CLK_TO_Q_NS}\"); }} cell_fall (scalar) {{ index_1 (\"0.1\"); values (\"{ARRAY_CLK_TO_Q_NS}\"); }}"
                             f" rise_transition (scalar) {{ index_1 (\"0.1\"); values (\"0.1\"); }} fall_transition (scalar) {{ index_1 (\"0.1\"); values (\"0.1\"); }} }} }}")
        lines.append("  }")
    lines.append("}")
    out = work / "analog_blackboxes.lib"
    out.write_text("\n".join(lines) + "\n")
    return out


def synth(work: Path, lib: Path, factorized: int, early: int, flatten: bool, tag: str, abc_d: float | None, buffer: bool = False) -> tuple[Path, Path, float | None, str]:
    """Yosys -> netlist. Returns (netlist, log, chip area um^2, stat text)."""
    net, log = work / f"{TOP}_{tag}.v", work / f"yosys_{tag}.log"
    abc = f"abc -liberty {lib} -g cmos" + (f" -D {int(abc_d * 1000)}" if abc_d else "")
    if buffer:                                   # -constr switches Yosys' abc script to "...; buffer -c; topo; stime -c; upsize -c; dnsize -c": fanout buffering and gate sizing
        constr = work / "abc.constr"
        constr.write_text("set_driving_cell BUFX2\nset_load 0.02\n")
        abc += f" -constr {constr}"
    script = textwrap.dedent(f"""\
        {read_cmds()}
        {params_cmd(factorized, early)}
        hierarchy -check -top {TOP}
        {"flatten -noscopeinfo" if flatten else ""}
        proc
        opt -purge
        memory
        opt -purge
        async2sync
        techmap
        opt -purge
        dfflibmap -liberty {lib}
        {abc}
        opt_clean -purge
        setundef -zero -undriven
        tee -o {work}/stat_{tag}.txt stat -liberty {lib}
        write_verilog -noattr {net}
        """)
    (work / f"synth_{tag}.ys").write_text(script)
    r = run(["yosys", "-l", str(log), str(work / f"synth_{tag}.ys")], cwd=work, timeout=7200)
    if r.returncode != 0:
        raise SystemExit(f"yosys failed ({tag}): {r.stderr[-800:]}")
    raw = net.with_name(net.stem + "_raw.v")                       # as Yosys wrote it: the black boxes keep their parameter overrides (gate-level simulation instantiates the behavioural models)
    net.replace(raw)
    v = raw.read_text()
    net.write_text(re.sub(r"\b(cim_macro|hdc_class_array) #\((?:\s*\.\w+\([^)]*\),?)+\s*\)", r"\1", v))      # for OpenSTA: no overrides (the stub liberty has no parameters)
    txt = (work / f"stat_{tag}.txt").read_text()
    m = re.findall(r"Chip area for (?:top )?module\s+'?\\?[^':\n]+'?\s*:\s*([\d.eE+\-]+)", txt)
    return net, log, float(m[-1]) if m else None, txt


def sta_timing(sta: str, work: Path, net: Path, libs: list[Path], period: float, tag: str) -> dict:
    rpt = work / f"timing_{tag}.rpt"
    tcl = textwrap.dedent(f"""\
        {''.join(f'read_liberty {l}' + chr(10) for l in libs)}
        read_verilog {net}
        link_design {TOP}
        create_clock -name clk -period {period} [get_ports {CLK}]
        set_input_delay  [expr {period} / 4.0] -clock clk [all_inputs]
        set_output_delay [expr {period} / 4.0] -clock clk [all_outputs]
        set_false_path -from [get_ports rst_n_i]
        report_checks -path_delay max -format full_clock_expanded -digits 3 > {rpt}
        report_checks -path_delay max -group_path_count 12 -unique_paths_to_endpoint -format end -digits 3 > {work}/endpoints_{tag}.rpt
        report_clock_min_period > {work}/minperiod_{tag}.rpt
        exit
        """)
    (work / f"sta_{tag}.tcl").write_text(tcl)
    r = run([sta, "-no_init", "-no_splash", "-exit", str(work / f"sta_{tag}.tcl")], cwd=work, log=work / f"sta_{tag}.log", timeout=1800)
    text = rpt.read_text() if rpt.exists() else ""
    slack = re.findall(r"([-+]?\d+\.\d+)\s+slack", text)
    arr = re.findall(r"([-+]?\d+\.\d+)\s+data arrival time", text)
    mp = (work / f"minperiod_{tag}.rpt").read_text() if (work / f"minperiod_{tag}.rpt").exists() else ""
    m = re.search(r"period_min\s*=\s*([\d.]+)", mp) or re.search(r"([\d.]+)\s*(?:ns)?\s*fmax", mp)
    path_cells = len(re.findall(r"\(\w+X\d+\w*\)|\(\w+XL\)", text))
    return dict(returncode=r.returncode, slack_ns=float(slack[-1]) if slack else None, arrival_ns=float(arr[-1]) if arr else None, min_period_report=mp.strip()[:300],
                period_min_ns=float(m.group(1)) if m else None, cells_on_worst_path=path_cells, report=str(rpt))


def parse_stat(txt: str) -> dict:
    """Cell counts from `stat`: total, flip-flops (DFF*/EDFF*/SDFF*), combinational."""
    total = None
    ff = 0
    for m in re.finditer(r"^\s+(\d+)\s+([\d.eE+\-]+)\s+(\S+)\s*$", txt, flags=re.M):
        n, _, name = int(m.group(1)), m.group(2), m.group(3)
        if name == "cells":
            total = n
        elif re.match(r"(DFF|EDFF|SDFF|SEDFF|DLL|DLH|TLAT)", name):
            ff += n
    return dict(cells=total, flip_flops=ff, combinational=None if total is None else total - ff)


VARIANTS = {                      # name -> (library corner, fanout buffering + sizing)
    "plain_fast": ("fast", False),    # the FFT project's mapping, unchanged: abc without buffering (area/timing comparable with the FFT numbers)
    "buf_fast": ("fast", True),       # the same library, abc timing-driven with fanout buffering and sizing (-D period, -constr): the PPA reported in phase5_ppa.md
    "buf_slow": ("slow", True),       # the slow corner of the same library
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", nargs="+", default=list(BUILDS))
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    ap.add_argument("--period", type=float, default=10.0, help="clock period, ns (NeuroHDC: 100 MHz)")
    ap.add_argument("--lib-dir", default=str(DEFAULT_LIB_DIR))
    ap.add_argument("--sta", default=None, help="path to the OpenSTA binary (default: design/rtl/tools/sta)")
    ap.add_argument("--hier", action="store_true", help="also write the hierarchy-preserving netlist (for the VCD power step)")
    a = ap.parse_args()
    sta = a.sta or str(ROOT / "tools" / "sta")
    OUT.mkdir(parents=True, exist_ok=True)
    for b in a.builds:
        f, e = BUILDS[b]
        work = OUT / b
        work.mkdir(parents=True, exist_ok=True)
        stub = stub_liberty(work, f, e)
        rec = json.loads((work / "summary.json").read_text()) if (work / "summary.json").exists() else {}
        rec.update(build=b, FACTORIZED=f, EARLY_EXIT_EN=e, period_ns=a.period)
        for v in a.variants:
            corner, buf = VARIANTS[v]
            lib = Path(a.lib_dir) / LIBS[corner]
            t0 = time.time()
            net, log, area, stat = synth(work, lib, f, e, True, f"flat_{v}", a.period if buf else None, buf)
            r = dict(corner=corner, buffered=buf, area_um2=area, **parse_stat(stat), yosys_s=round(time.time() - t0, 1))
            r["timing"] = sta_timing(sta, work, net, [lib, stub], a.period, f"flat_{v}")
            r["reg2reg"] = sta_reg2reg(sta, work, net, [lib, stub], a.period, f"flat_{v}")
            rec[v] = r
            print(f"[{b}/{v}] area {area} um^2, {r['flip_flops']} FF + {r['combinational']} comb cells, worst slack {r['timing']['slack_ns']} ns (reg->reg {r['reg2reg']['slack_ns']} ns) @ {a.period} ns", flush=True)
            (work / "summary.json").write_text(json.dumps(rec, indent=1))
        if a.hier:
            lib = Path(a.lib_dir) / LIBS["fast"]
            net, _, area, stat = synth(work, lib, f, e, False, "hier_buf_fast", a.period, True)
            rec["hier"] = dict(area_um2=area, modules=parse_module_areas(stat))
            (work / "summary.json").write_text(json.dumps(rec, indent=1))
    return 0


def parse_module_areas(txt: str) -> dict:
    """Cell area per module BASE name (children excluded), summed over its parameterised variants/instances, from a hierarchical `stat -liberty`. Yosys names the variants
    `$paramod\\name\\PARAMS` or `$paramod$hash\\name`; `count` is the number of module variants summed."""
    out: dict[str, dict] = {}
    for sec in re.split(r"\n=== ", txt)[1:]:
        m = re.search(r"Chip area for module '(.*)':\s*([\d.eE+\-]+)\s*$", sec, re.M)
        if not m:
            continue
        name = m.group(1).lstrip("\\")
        b = re.match(r"\$paramod(?:\$[0-9a-f]+)?\\([A-Za-z_0-9]+)", name)
        base = b.group(1) if b else name
        d = out.setdefault(base, dict(area_um2=0.0, count=0))
        d["area_um2"] += float(m.group(2))
        d["count"] += 1
    return out


def sta_reg2reg(sta: str, work: Path, net: Path, libs: list[Path], period: float, tag: str) -> dict:
    """Worst register-to-register path (the analog arrays' outputs count as clocked start points): what the clock period must cover."""
    tcl = textwrap.dedent(f"""\
        {''.join(f'read_liberty {l}' + chr(10) for l in libs)}
        read_verilog {net}
        link_design {TOP}
        create_clock -name clk -period {period} [get_ports {CLK}]
        report_checks -path_delay max -from [all_registers -clock_pins] -to [all_registers -data_pins] -format full -digits 3 > {work}/r2r_{tag}.rpt
        exit
        """)
    (work / f"r2r_{tag}.tcl").write_text(tcl)
    run([sta, "-no_init", "-no_splash", "-exit", str(work / f"r2r_{tag}.tcl")], cwd=work, log=work / f"r2r_{tag}.log", timeout=1800)
    text = (work / f"r2r_{tag}.rpt").read_text() if (work / f"r2r_{tag}.rpt").exists() else ""
    slack = re.findall(r"([-+]?\d+\.\d+)\s+slack", text)
    arr = re.findall(r"([-+]?\d+\.\d+)\s+data arrival time", text)
    start = re.findall(r"Startpoint: (\S+)", text)
    return dict(slack_ns=float(slack[-1]) if slack else None, arrival_ns=float(arr[0]) if arr else None, startpoint=start[0] if start else None,
                min_period_ns=round(float(arr[0]) + 0.022, 3) if arr else None, cells_on_path=len(re.findall(r"\(\w+X\w+\)", text)), report=str(work / f"r2r_{tag}.rpt"))


if __name__ == "__main__":
    raise SystemExit(main())
