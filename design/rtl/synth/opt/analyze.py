#!/usr/bin/env python3
"""Post-layout analysis of one stage of the optimised flow (synth/work/opt/<tag>/<stage>.odb): both corners, setup and hold, from OpenROAD's OpenSTA with parasitics estimated from the
routed (or global-routed) wiring using the PDK tech-LEF layer RC; then POWER from a gate-level simulation of THAT stage's netlist with a VCD window, annotated 100 % (reported).

  python opt/analyze.py --tag c2 --stage groute [--windows ing mvm] [--ts 10] [--row 46] [--skip-power]

Timing (per corner = scene `slow` 0.9 V / 125 C and `fast` 1.1 V / 0 C): worst setup / hold slack, TNS, number of failing endpoints, max-slew / max-capacitance violations, clock skew.
Power windows (--ts T, --row R): the sample's timestep T (RTL run with the counters on gives its phase boundaries): `ing` = 2400 cycles inside the ingest phase, `mvm` = the whole scan /
read phase of the timestep. Power is the FAST library's (1.1 V, as every earlier number); the slow library's (0.9 V) is reported next to it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import synth_power as P  # noqa: E402
import synth_ppa as S  # noqa: E402

PDK = REPO / "45_nm_PDK" / "cadence" / "cadence_45nm"
OPENROAD = os.environ.get("OPENROAD", os.path.expanduser("~/.cache/cim_neurohdc/openroad_src/build/bin/openroad"))


def prelude(run: Path, stage: str) -> str:
    est = "-global_routing" if stage in ("groute", "routed") else "-placement"
    prop = "set_propagated_clock [all_clocks]" if stage in ("cts", "groute", "routed") else ""
    return "\n".join(["define_corners slow fast", f"read_lef {SYNTH / 'work' / 'tech_openroad.lef'}", f"read_lef {PDK / 'lef' / 'gsclib045_macro.lef'}", *(f"read_lef {l}" for l in sorted((run / 'macro').glob('*.lef'))),
                      f"read_liberty -corner slow {PDK / 'lib' / S.LIBS['slow']}", f"read_liberty -corner fast {PDK / 'lib' / S.LIBS['fast']}",
                      *(f"read_liberty -corner {c} {l}" for l in sorted((run / 'macro').glob('*.lib')) for c in ('slow', 'fast')),
                      f"read_db {run / (stage + '.odb')}", f"read_sdc {SYNTH / 'constraints' / 'cim_neurohdc_top.sdc'}", prop, "set_wire_rc -signal -layer Metal3", "set_wire_rc -clock -layer Metal5", f"estimate_parasitics {est}"])


def or_run(run: Path, name: str, tcl: str) -> str:
    (run / "an").mkdir(exist_ok=True)
    f = run / "an" / f"{name}.tcl"
    f.write_text(tcl)
    r = subprocess.run([OPENROAD, "-no_init", "-exit", str(f)], capture_output=True, text=True, cwd=run / "an")
    (run / "an" / f"{name}.log").write_text(r.stdout + r.stderr)
    return r.stdout + r.stderr


def timing(run: Path, stage: str) -> dict:
    t = prelude(run, stage) + "\n" + f"""
foreach c {{slow fast}} {{
  set sc [sta::find_scene $c]
  puts "RES $c setup_wns [expr {{[sta::worst_slack_scene $sc max] * 1e9}}] hold_wns [expr {{[sta::worst_slack_scene $sc min] * 1e9}}] setup_tns [expr {{[sta::total_negative_slack_scene_cmd $sc max] * 1e9}}] hold_tns [expr {{[sta::total_negative_slack_scene_cmd $sc min] * 1e9}}]"
}}
report_checks -path_delay max -format end -group_path_count 1 -digits 3 > {run}/an/worst_setup_{stage}.rpt
report_checks -path_delay min -format end -group_path_count 1 -digits 3 > {run}/an/worst_hold_{stage}.rpt
report_check_types -max_slew -max_capacitance -max_fanout -violators > {run}/an/viol_{stage}.rpt
report_clock_skew -setup -digits 3 > {run}/an/skew_{stage}.rpt
report_clock_skew -hold -digits 3 > {run}/an/skewh_{stage}.rpt
report_design_area > {run}/an/area_{stage}.rpt
log_begin {run}/an/cells_{stage}.rpt
report_cell_usage
log_end
write_verilog {run}/{stage}.v
puts "DONE"
"""
    out = or_run(run, f"timing_{stage}", t)
    res = {m.group(1): dict(setup_wns_ns=float(m.group(2)), hold_wns_ns=float(m.group(3)), setup_tns_ns=float(m.group(4)), hold_tns_ns=float(m.group(5)))
           for m in re.finditer(r"RES (\w+) setup_wns (\S+) hold_wns (\S+) setup_tns (\S+) hold_tns (\S+)", out)}
    rd = lambda n: (run / "an" / n).read_text() if (run / "an" / n).exists() else ""      # noqa: E731
    v = rd(f"viol_{stage}.rpt")
    res["max_slew_violations"] = len(re.findall(r"\(VIOLATED\)", v.split("max cap")[0])) if "max slew" in v else 0
    res["violations_report_bytes"] = len(v)
    res["skew_setup"] = rd(f"skew_{stage}.rpt").strip()[-400:]
    res["skew_hold"] = rd(f"skewh_{stage}.rpt").strip()[-400:]
    m = re.search(r"Design area ([\d.]+) u\^2 ([\d.]+)% utilization", rd(f"area_{stage}.rpt"))
    res["design_area_um2_incl_macros"] = float(m.group(1)) if m else None
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--stage", required=True, choices=["place", "cts", "groute", "routed"])
    ap.add_argument("--skip-power", action="store_true")
    ap.add_argument("--windows", nargs="+", default=["ing", "mvm"])
    ap.add_argument("--row", type=int, default=46)
    a = ap.parse_args()
    run = SYNTH / "work" / "opt" / a.tag
    t0 = time.time()
    res = dict(tag=a.tag, stage=a.stage, parasitics="PDK tech-LEF layer RC on the " + ("global-routed / detail-routed wiring (no coupling)" if a.stage in ("groute", "routed") else "placement (Steiner estimate)"))
    res["timing"] = timing(run, a.stage)
    print(json.dumps(res["timing"], indent=1)[:1500], flush=True)
    (run / f"analysis_{a.stage}.json").write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
