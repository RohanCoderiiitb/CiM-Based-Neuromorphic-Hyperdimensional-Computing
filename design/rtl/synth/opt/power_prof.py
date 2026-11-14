#!/usr/bin/env python3
"""Post-layout power BY MODULE. Needs a layout whose netlist was synthesised with `run_flow.py --hier-names` (every module mapped on its own, flattened afterwards), so each cell
keeps its module path in its instance name. One gate-level window per spec -> SAIF -> OpenSTA (stage netlist + SPEF, fast library) with `report_power -instances`; the instance powers
are summed by module path. Cells the layout added are grouped by what they are: clock-tree buffers (clkbuf / clkload), timing / slew repair buffers (wire, fanout, rebuffer, max_cap,
load_slew, split, place), port buffers (input / output), hold buffers.
  spec = dataset:row:start:length   (dataset dvs | nm);   the name `idle` runs the DVS sample with the intake closed (ingest_en = 0): nothing but the always-on activity
  python opt/power_prof.py --tag p1 --stage groute --spec idle dvs:46:60000:4000 nm:7:200:2500"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gatesim as GS  # noqa: E402
import power as PW  # noqa: E402
from tb.common import hdc_golden as H  # noqa: E402
import nm_power as NP  # noqa: E402
import power2 as P2  # noqa: E402

SYNTH = PW.SYNTH
LAYOUT_CELLS = (("clkbuf", "clock tree buffers"), ("clkload", "clock tree buffers"), ("wire", "repair buffers"), ("fanout", "repair buffers"), ("rebuffer", "repair buffers"),
                ("max_cap", "repair buffers"), ("load_slew", "repair buffers"), ("split", "repair buffers"), ("place", "repair buffers"), ("hold", "hold buffers"),
                ("input", "port buffers"), ("output", "port buffers"))


def module_of(name: str, depth: int) -> str:
    n = name.replace("\\", "")
    for pre, lab in LAYOUT_CELLS:
        if n.startswith(pre) and re.match(rf"{pre}\d", n):
            return lab
    parts = n.split(".")
    parts = [p for p in parts[:-1] if not p.startswith("$") and not p.startswith("_")]
    if not parts:
        return "(top)"
    return ".".join(parts[:depth])


def run_window(run: Path, stage: str, build: str, name: str, spec: str, mdls: dict) -> dict:
    const = json.loads((run / "syn" / "const_ports.json").read_text())
    idle = spec == "idle"
    ds, row, start, length = ("dvs", 46, 300, 1500) if idle else (spec.split(":")[0], *map(int, spec.split(":")[1:]))
    if ds not in mdls:
        mdls[ds] = NP.nm_model() if ds == "nm" else H.load_model("r1", 0, "dvsgesture")
    orig = GS.make_tb
    if idle:
        def patched(work, const_ports):
            p = orig(work, const_ports)
            p.write_text(p.read_text().replace("ingest_en = 1'b1", "ingest_en = 1'b0", 1))       # the intake stays closed: no event is accepted, nothing is scanned
            return p
        GS.make_tb = patched
    vcd = run / f"gs_{name}" / f"{name}.vcd"
    try:
        GS.run(build, run / f"gs_{name}", run / (stage + ".v"), const, row, start, length, theta=4095, cols=40, mdl=mdls[ds], vcd_name=f"{name}.vcd")
    except IndexError:
        if not idle:           # the idle run logs no timestep, which the output parser does not expect; the VCD is complete
            raise
    finally:
        GS.make_tb = orig
    pw = PW.sta_power(run, stage, name, vcd, "fast", instances=True)
    cnt = P2.count_window(vcd, 0, 1 << 62)
    vcd.unlink(missing_ok=True)
    return dict(spec=spec, power_w=pw["total_w"], groups=pw["groups_internal_switching_leakage_total_w"], **cnt)


def aggregate(run: Path, name: str, depth: int) -> dict:
    agg = collections.defaultdict(float)
    for l in open(run / "an" / f"inst_{name}_fast.rpt"):
        f = l.split()
        if len(f) == 5 and re.match(r"[\d.e+-]+$", f[3]):
            agg[module_of(f[4], depth)] += float(f[3])
    return dict(agg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--build", default="ee_off")
    ap.add_argument("--stage", default="groute")
    ap.add_argument("--depth", type=int, default=2, help="levels of the module path kept")
    ap.add_argument("--spec", nargs="+", required=True)
    a = ap.parse_args()
    run = SYNTH / "work" / "opt" / a.tag
    mdls, out = {}, {}
    for k, sp in enumerate(a.spec):
        name = f"prof{k}"
        w = run_window(run, a.stage, a.build, name, sp, mdls)
        w["modules_uW"] = {m: v * 1e6 for m, v in sorted(aggregate(run, name, a.depth).items(), key=lambda kv: -kv[1])}
        out[sp] = w
        print(f"== {sp}: {w['power_w'] * 1e3:.3f} mW  cycles {w['cycles']} events {w['events']} passes {w['reads']}   clock group {w['groups'].get('Clock', [0, 0, 0, 0])[3] * 1e6:.0f} uW", flush=True)
        for m, v in list(w["modules_uW"].items())[:22]:
            print(f"   {m:44s} {v:8.1f} uW  {100 * v / (w['power_w'] * 1e6):5.1f} %")
    (run / f"power_prof_{a.stage}.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
