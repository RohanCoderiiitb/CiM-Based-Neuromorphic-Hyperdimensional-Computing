#!/usr/bin/env python3
"""Analysis of a stage of the OpenROAD run (run_flow.tcl): area, timing at both corners, clock skew, and power from a gate-level simulation of THAT stage's netlist (three windows, as the
pre-route numbers), all inside OpenROAD's own OpenSTA with parasitics estimated from the PDK's tech LEF. Writes synth/results/layout/<build>/<stage>/summary.json in the schema
final_ppa.py reads (the same as layout_analysis.py's), plus tool = 'OpenROAD'.

  python analyze_openroad.py --stage pre_cts|post_cts|routed --build full [--skip-power] [--windows all ing mvm]
Parasitics: set_wire_rc from the LEF layers (Metal3 signal, Metal5 clock), estimate_parasitics -placement (pre_cts, post_cts) / -global_routing (routed). Not a Quantus extraction.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(SYNTH))
import layout_analysis as LA  # noqa: E402
import synth_power as P  # noqa: E402
import synth_ppa as S  # noqa: E402

DB = {"pre_cts": ("place.odb", "pre_cts.v"), "post_cts": ("cts.odb", "post_cts.v"), "groute": ("groute.odb", "groute.v"), "routed": ("routed.odb", "routed.v")}
PDK = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm"
OPENROAD = os.environ.get("OPENROAD", str(Path("/private/tmp/claude-501/openroad_src/build/bin/openroad")))


def or_run(work: Path, name: str, tcl: str) -> str:
    (work / f"{name}.tcl").write_text(tcl)
    r = S.run([OPENROAD, "-no_init", "-no_splash", "-exit", str(work / f"{name}.tcl")], cwd=work, log=work / f"{name}.log", timeout=7200)
    return r.stdout + r.stderr


def prelude(build: str, stage: str, lib: Path, macro_dir: Path, outd: Path) -> str:
    db = DB[stage][0]
    prop = "set_propagated_clock [all_clocks]" if stage in ("post_cts", "groute", "routed") else ""
    est = "-global_routing" if stage in ("groute", "routed") else "-placement"
    return "\n".join([f"read_lef {SYNTH / 'work' / 'tech_openroad.lef'}", f"read_lef {PDK / 'lef' / 'gsclib045_macro.lef'}", f"read_lef {macro_dir / 'cim_macro.lef'}", f"read_lef {macro_dir / 'hdc_class_array.lef'}",
                      f"read_liberty {lib}", f"read_liberty {macro_dir / 'cim_macro.lib'}", f"read_liberty {macro_dir / 'hdc_class_array.lib'}", f"read_db {outd / db}",
                      f"read_sdc {SYNTH / 'constraints' / 'cim_neurohdc_top.sdc'}", prop, "set_wire_rc -signal -layer Metal3", "set_wire_rc -clock -layer Metal5", f"estimate_parasitics {est}"])


def timing(work: Path, tag: str, build: str, stage: str, lib: Path, macro_dir: Path, outd: Path) -> dict:
    t = prelude(build, stage, lib, macro_dir, outd) + "\n" + "\n".join([
        f"report_worst_slack -max -digits 3 > {work}/ws_{tag}.rpt", f"report_worst_slack -min -digits 3 > {work}/hs_{tag}.rpt", f"report_tns -digits 3 > {work}/tns_{tag}.rpt",
        f"report_clock_skew -setup -digits 3 > {work}/skew_{tag}.rpt", f"report_clock_skew -hold -digits 3 > {work}/skewh_{tag}.rpt",
        f"report_checks -path_delay max -from [all_registers -clock_pins] -to [all_registers -data_pins] -digits 3 > {work}/r2r_{tag}.rpt", "exit"]) + "\n"
    or_run(work, f"sta_{tag}", t)
    rd = lambda n: (work / n).read_text() if (work / n).exists() else ""                       # noqa: E731
    num = lambda pat, s: (float(re.search(pat, s).group(1)) if re.search(pat, s) else None)       # noqa: E731
    r2r = rd(f"r2r_{tag}.rpt")
    slack = re.findall(r"([-+]?\d+\.\d+)\s+slack", r2r)
    return dict(worst_slack_ns=num(r"worst slack (?:max )?([-+]?\d+\.\d+)", rd(f"ws_{tag}.rpt")), hold_worst_slack_ns=num(r"worst slack (?:min )?([-+]?\d+\.\d+)", rd(f"hs_{tag}.rpt")),
                tns_ns=num(r"tns (?:max )?([-+]?\d+\.\d+)", rd(f"tns_{tag}.rpt")), reg2reg_slack_ns=float(slack[-1]) if slack else None,
                clock_skew_report=rd(f"skew_{tag}.rpt").strip()[:700], clock_skew_hold_report=rd(f"skewh_{tag}.rpt").strip()[:400],
                clock_skew_numbers=re.findall(r"(?:skew|Skew)\s+([-+]?\d+\.\d+)|^\s*([-+]?\d+\.\d+)\s*$", rd(f"skew_{tag}.rpt"), re.M)[:4], propagated_clock=stage in ("post_cts", "groute", "routed"), parasitics="LEF-derived RC estimate")


def power(work: Path, w: str, build: str, stage: str, lib: Path, macro_dir: Path, outd: Path, vcd: Path) -> dict:
    t = prelude(build, stage, lib, macro_dir, outd) + "\n" + f"read_vcd -scope hdc_gate_tb/dut {vcd}\nreport_activity_annotation > {work}/ann_{w}.rpt\nreport_power > {work}/power_{w}.rpt\nexit\n"
    or_run(work, f"pw_{w}", t)
    txt = (work / f"power_{w}.rpt").read_text() if (work / f"power_{w}.rpt").exists() else ""
    ann = (work / f"ann_{w}.rpt").read_text() if (work / f"ann_{w}.rpt").exists() else ""
    tot = re.search(r"^Total\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)
    grp = {m.group(1): [float(m.group(i)) for i in (2, 3, 4, 5)] for m in re.finditer(r"^(Sequential|Combinational|Clock|Macro|Pad)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)", txt, re.M)}
    return dict(total_w=float(tot.group(4)) if tot else None, internal_w=float(tot.group(1)) if tot else None, switching_w=float(tot.group(2)) if tot else None,
                leakage_w=float(tot.group(3)) if tot else None, groups_internal_switching_leakage_total_w=grp, annotation={k: int(v) for k, v in re.findall(r"^\s*(vcd|saif|unannotated|input)\s+(\d+)", ann, re.M)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=list(DB))
    ap.add_argument("--build", default="full")
    ap.add_argument("--skip-power", action="store_true")
    ap.add_argument("--windows", nargs="+", default=["all", "ing", "mvm"], choices=list(LA.WINDOWS))
    ap.add_argument("--row", type=int, default=46)
    a = ap.parse_args()
    S.CFG.update(gate=4, rtl_gating=1, isolate=1, instr=0)
    f, e = S.BUILDS[a.build]
    outd = SYNTH / "results" / "openroad" / a.build
    macro_dir = SYNTH / "work" / a.build
    work = SYNTH / "results" / "layout" / a.build / a.stage
    work.mkdir(parents=True, exist_ok=True)
    fast, slow = PDK / "lib" / S.LIBS["fast"], PDK / "lib" / S.LIBS["slow"]
    net_raw = outd / DB[a.stage][1]
    t0 = time.time()
    res: dict = dict(stage=a.stage, build=a.build, tool="OpenROAD (place, CTS, global+detail route); RC from the PDK tech LEF", netlist=str(net_raw), propagated_clocks=a.stage in ("post_cts", "groute", "routed"))
    res["area"] = LA.netlist_area(net_raw, LA.liberty_areas(fast))
    log = outd / {"pre_cts": "place.log", "post_cts": "cts.log", "groute": "groute.log", "routed": "route.log"}[a.stage]
    hits = re.findall(r"Design area ([\d.]+) um\^2 ([\d.]+)% utilization", log.read_text(errors="replace")) if log.exists() else []
    if hits:
        # the stage's own figure: pre_cts = the last report before CTS (2nd in place.log: floorplan has none), post_cts / routed = the last in their log
        area_um2, util = hits[-1]
        res["floorplan"] = dict(design_area_um2=float(area_um2), utilisation_of_core_pct=float(util), note="all instances incl. the two macros, over the core area")
    res["timing"] = {c: timing(work, c, a.build, a.stage, lib, macro_dir, outd) for c, lib in (("fast", fast), ("slow", slow))}
    if not a.skip_power:
        cells = P.liberty_models(fast, work / "cells_fast.v")
        res["power"] = {}
        for w in a.windows:
            start, length = LA.WINDOWS[w]
            wk = work / f"power_{w}"
            wk.mkdir(exist_ok=True)
            g = P.gate_sim(a.build, wk, net_raw, cells, a.row, start, length, 4095)
            pw = power(wk, w, a.build, a.stage, fast, macro_dir, outd, g["vcd"])
            pw.update(window_start=start, window_cycles=length, gate_level_matches_golden=g["gate_level_matches_golden"], timesteps_checked=g["timesteps_checked"])
            g["vcd"].unlink()
            res["power"][w] = pw
            print(f"[{a.build}/{a.stage}] power window {w}: {pw['total_w'] * 1e3:.4f} mW, golden {pw['gate_level_matches_golden']}", flush=True)
    res["wall_s"] = round(time.time() - t0)
    old = work / "summary.json"
    if old.exists():                                  # keep the windows measured by an earlier call (e.g. mvm first, ing later)
        prev = json.loads(old.read_text()).get("power", {})
        res["power"] = {**prev, **res.get("power", {})}
    old.write_text(json.dumps(res, indent=1))
    t = res["timing"]
    print(f"[{a.build}/{a.stage}] cell area {res['area']['std_cell_area_um2']:,.0f} um^2, {res['area']['icgs']} ICGs; worst slack fast {t['fast']['worst_slack_ns']} / slow {t['slow']['worst_slack_ns']} ns; "
          f"hold {t['fast']['hold_worst_slack_ns']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
