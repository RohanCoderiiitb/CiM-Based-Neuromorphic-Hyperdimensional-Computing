#!/usr/bin/env python3
"""D1(c)-(e): the numbers from a placed / clock-tree / routed netlist - computed HERE, with the same tools and method as the pre-route numbers, so that pre- and post-route differ only by the
layout. Innovus (the owner's) produces the netlists, SPEF and DEF; nothing below needs a licence.

  python design/rtl/synth/layout_analysis.py --stage pre_cts|post_cts|routed --build full --netlist <v> [--spef <spef>] [--def <def>] [--out-tag X]
  python design/rtl/synth/layout_analysis.py --stage baseline --build full           # the Yosys netlist of results/ppa_digital through the very same code (pipeline check, and the pre-route column)

Per stage and build it writes synth/results/layout/<build>/<stage>/summary.json with
  AREA      standard-cell area from the netlist (Liberty areas; cells and ICGs and clock buffers counted separately), die / core area and utilisation from the DEF when given
  TIMING    OpenSTA at the fast and the slow corner: worst slack, worst reg->reg slack, min period; with the SPEF when given; ideal clocks for pre_cts / baseline, PROPAGATED clocks for post_cts / routed
  CLOCK     clock skew (OpenSTA report_clock_skew), ICG count and CLKBUF/CLKINV count (NOTE: the mapper also uses CLKBUF/CLKINV as ordinary logic buffers/inverters - 4,442 of them in the pre-route netlist - so the clock-tree buffers are the DIFFERENCE between the post_cts and pre_cts counts, which final_ppa.py takes), and the clock-group power (the 'Clock' row of report_power)
  POWER     gate-level simulation of THIS netlist (zero delay; Icarus; Liberty cells as Verilog models, the analog arrays behavioural) on the regression's testbench and a real sample, three windows
            (whole 8,000-cycle window; ingest-only; read phase) -> VCD -> OpenSTA report_power with the SPEF read, i.e. wire capacitance included in the switching power;
            gate level checked against the golden model in each window.
The activity is zero-delay (no glitches, no SDF); the SDF-annotated alternative needs Verilog models with specify blocks, which the PDK does not ship (Liberty only).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import synth_power as P  # noqa: E402
import synth_ppa as S  # noqa: E402

OUT = HERE / "results" / "layout"
PDK_LIB = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lib"
WINDOWS = {"all": (12000, 8000), "ing": (12000, 2400), "mvm": (14580, 560)}       # the windows of the pre-route power runs
CELL_RE = re.compile(r"^\s*(\\?[A-Za-z_][\w$]*)\s+(?:#\([^;]*?\)\s*)?(\\?\S+)\s*\(", re.M)


def liberty_areas(lib: Path) -> dict[str, float]:
    t = lib.read_text()
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"cell \((\w+)\)\s*\{\s*area : ([\d.]+);", t)}


def netlist_area(net: Path, areas: dict[str, float]) -> dict:
    txt = net.read_text()
    cnt: dict[str, int] = {}
    for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]*[A-Z0-9])\s+(\\?\S+)\s*\(", txt, re.M):
        if m.group(1) in areas:
            cnt[m.group(1)] = cnt.get(m.group(1), 0) + 1
    tot = sum(areas[c] * n for c, n in cnt.items())
    pick = lambda pred: sum(areas[c] * n for c, n in cnt.items() if pred(c))                       # noqa: E731
    npick = lambda pred: sum(n for c, n in cnt.items() if pred(c))                                 # noqa: E731
    return dict(std_cell_area_um2=tot, cells=sum(cnt.values()), flip_flops=npick(lambda c: re.match(r"(E|S|SE)?DFF", c)), icgs=npick(lambda c: c.startswith("TLATNCAX")),
                icg_area_um2=pick(lambda c: c.startswith("TLATNCAX")), clock_buffers=npick(lambda c: c.startswith(("CLKBUF", "CLKINV"))), clock_buffer_area_um2=pick(lambda c: c.startswith(("CLKBUF", "CLKINV"))),
                filler_cells=npick(lambda c: c.startswith("FILL")), by_cell=cnt)


def def_area(deff: Path) -> dict:
    t = deff.read_text(errors="replace")
    u = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", t).group(1))
    m = re.search(r"DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", t)
    x0, y0, x1, y1 = (int(v) / u for v in m.groups())
    comps = re.findall(r"^\s*-\s+(\S+)\s+(\S+)\s+\+\s+(?:FIXED|PLACED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)", t, re.M)
    return dict(die_w_um=x1 - x0, die_h_um=y1 - y0, die_area_um2=(x1 - x0) * (y1 - y0), components=len(comps))


def sta(work: Path, tag: str, libs: list[Path], net: Path, spef: Path | None, propagated: bool, period: float = 10.0) -> dict:
    rpt = work / f"timing_{tag}.rpt"
    tcl = "\n".join([*(f"read_liberty {l}" for l in libs), f"read_verilog {net}", f"link_design {S.TOP}", f"create_clock -name clk -period {period} [get_ports {S.CLK}]",
                     f"set_input_delay [expr {period} / 4.0] -clock clk [all_inputs]", f"set_output_delay [expr {period} / 4.0] -clock clk [all_outputs]", "set_false_path -from [get_ports rst_n_i]",
                     *([f"read_spef {spef}"] if spef else []), *(["set_propagated_clock [all_clocks]"] if propagated else []),
                     f"report_checks -path_delay max -format full_clock_expanded -digits 3 > {rpt}", f"report_checks -path_delay max -group_path_count 1 -format end -digits 3 > {work}/end_{tag}.rpt",
                     f"report_worst_slack -max -digits 3 > {work}/worst_{tag}.rpt", f"report_tns -digits 3 > {work}/tns_{tag}.rpt", f"report_clock_skew -setup -digits 3 > {work}/skew_{tag}.rpt",
                     f"report_clock_min_period > {work}/minperiod_{tag}.rpt", "exit"]) + "\n"
    (work / f"sta_{tag}.tcl").write_text(tcl)
    r = S.run([str(ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(work / f"sta_{tag}.tcl")], cwd=work, log=work / f"sta_{tag}.log", timeout=3600)
    rd = lambda n: (work / n).read_text() if (work / n).exists() else ""                         # noqa: E731
    ws = re.search(r"worst slack\s+(max\s+)?([-+]?\d+\.\d+)", rd(f"worst_{tag}.rpt"))
    tns = re.search(r"tns\s+(max\s+)?([-+]?\d+\.\d+)", rd(f"tns_{tag}.rpt"))
    sk = rd(f"skew_{tag}.rpt")
    skew = re.findall(r"^\s*(?:Latency|Skew|skew)?.*?([-+]?\d+\.\d+)\s*$", sk, re.M)
    slack_paths = re.findall(r"([-+]?\d+\.\d+)\s+slack", rd(f"timing_{tag}.rpt"))
    mp = re.search(r"period_min\s*=\s*([\d.]+)", rd(f"minperiod_{tag}.rpt"))
    return dict(returncode=r.returncode, worst_slack_ns=float(ws.group(2)) if ws else None, tns_ns=float(tns.group(2)) if tns else None,
                worst_path_slack_ns=float(slack_paths[-1]) if slack_paths else None, period_min_ns=float(mp.group(1)) if mp else None, clock_skew_report=sk.strip()[:600],
                clock_skew_numbers=skew[:8], propagated_clock=propagated, spef=str(spef) if spef else None)


def sta_power(work: Path, libs: list[Path], net: Path, spef: Path | None, vcd: Path, propagated: bool, tag: str, period: float = 10.0) -> dict:
    rpt, ann = work / f"power_{tag}.rpt", work / f"annotation_{tag}.rpt"
    tcl = "\n".join([*(f"read_liberty {l}" for l in libs), f"read_verilog {net}", f"link_design {S.TOP}", f"create_clock -name clk -period {period} [get_ports {S.CLK}]",
                     *([f"read_spef {spef}"] if spef else []), *(["set_propagated_clock [all_clocks]"] if propagated else []),
                     f"read_vcd -scope hdc_gate_tb/dut {vcd}", f"report_activity_annotation > {ann}", f"report_power > {rpt}", "exit"]) + "\n"
    (work / f"power_{tag}.tcl").write_text(tcl)
    r = S.run([str(ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(work / f"power_{tag}.tcl")], cwd=work, log=work / f"power_{tag}.log", timeout=7200)
    txt = rpt.read_text() if rpt.exists() else ""
    a = ann.read_text() if ann.exists() else ""
    tot = re.search(r"^Total\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)
    grp = {m.group(1): [float(m.group(i)) for i in (2, 3, 4, 5)] for m in re.finditer(r"^(Sequential|Combinational|Clock|Macro|Pad)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)}
    return dict(returncode=r.returncode, total_w=float(tot.group(4)) if tot else None, internal_w=float(tot.group(1)) if tot else None, switching_w=float(tot.group(2)) if tot else None,
                leakage_w=float(tot.group(3)) if tot else None, groups_internal_switching_leakage_total_w=grp, annotation={k: int(v) for k, v in re.findall(r"^\s*(vcd|saif|unannotated|input)\s+(\d+)", a, re.M)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["baseline", "pre_cts", "post_cts", "routed"])
    ap.add_argument("--build", default="full", choices=list(S.BUILDS))
    ap.add_argument("--netlist", help="Verilog netlist from Innovus (write_netlist); not needed for --stage baseline")
    ap.add_argument("--spef", help="SPEF for this stage (rcOut -spef); optional for pre_cts")
    ap.add_argument("--def", dest="deff", help="DEF of this stage (defOut): die area / utilisation")
    ap.add_argument("--lib-dir", default=str(PDK_LIB))
    ap.add_argument("--skip-power", action="store_true")
    ap.add_argument("--windows", nargs="+", default=["all", "ing", "mvm"], choices=list(WINDOWS))
    ap.add_argument("--row", type=int, default=46)
    a = ap.parse_args()
    S.CFG.update(gate=4, rtl_gating=1, isolate=1, instr=0)
    f, e = S.BUILDS[a.build]
    libd = Path(a.lib_dir)
    fast, slow = libd / S.LIBS["fast"], libd / S.LIBS["slow"]
    work = OUT / a.build / a.stage
    work.mkdir(parents=True, exist_ok=True)
    stub = S.stub_liberty(work, f, e)
    if a.stage == "baseline":
        base = ROOT / "results" / "ppa_digital" / a.build
        net, net_raw, spef = base / "cim_neurohdc_top_flat_buf_fast.v", base / "cim_neurohdc_top_flat_buf_fast_raw.v", None
    else:
        net_raw = Path(a.netlist)
        net = work / "netlist_for_sta.v"
        net.write_text(re.sub(r"\b(cim_macro|hdc_class_array)\s*#\((?:\s*\.\w+\([^)]*\),?)+\s*\)", r"\1", net_raw.read_text()))
        spef = Path(a.spef) if a.spef else None
    propagated = a.stage in ("post_cts", "routed")
    t0 = time.time()
    res: dict = dict(stage=a.stage, build=a.build, netlist=str(net_raw), propagated_clocks=propagated)
    res["area"] = netlist_area(net_raw, liberty_areas(fast))
    if a.deff:
        res["floorplan"] = def_area(Path(a.deff))
        res["floorplan"]["std_cell_utilisation"] = res["area"]["std_cell_area_um2"] / res["floorplan"]["die_area_um2"]
    res["timing"] = {c: sta(work, c, [lib, stub], net, spef, propagated) for c, lib in (("fast", fast), ("slow", slow))}
    if not a.skip_power:
        cells = P.liberty_models(fast, work / "cells_fast.v")
        res["power"] = {}
        for w in a.windows:
            start, length = WINDOWS[w]
            wk = work / f"power_{w}"
            wk.mkdir(exist_ok=True)
            g = P.gate_sim(a.build, wk, net_raw, cells, a.row, start, length, 4095)
            pw = sta_power(wk, [fast, stub], net, spef, g["vcd"], propagated, w)
            pw.update(window_start=start, window_cycles=length, gate_level_matches_golden=g["gate_level_matches_golden"], timesteps_checked=g["timesteps_checked"])
            g["vcd"].unlink()
            res["power"][w] = pw
            print(f"[{a.build}/{a.stage}] power window {w}: {pw['total_w'] * 1e3:.4f} mW (clock group {pw['groups_internal_switching_leakage_total_w'].get('Clock', [0, 0, 0, 0])[3] * 1e3:.4f} mW), "
                  f"golden {pw['gate_level_matches_golden']}", flush=True)
    res["wall_s"] = round(time.time() - t0)
    (work / "summary.json").write_text(json.dumps(res, indent=1))
    t = res["timing"]
    print(f"[{a.build}/{a.stage}] std-cell area {res['area']['std_cell_area_um2']:,.0f} um^2, {res['area']['cells']:,} cells, {res['area']['icgs']} ICGs, {res['area']['clock_buffers']} clock buffers; "
          f"worst slack fast {t['fast']['worst_slack_ns']} / slow {t['slow']['worst_slack_ns']} ns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
