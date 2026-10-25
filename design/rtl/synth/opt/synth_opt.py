#!/usr/bin/env python3
"""Optimised-flow synthesis (reports/optimised_ppa.md, item 2a): Yosys against the SLOW library (the corner the design is graded in), abc constrained to it with the driving cell and the
load of the SDC, minimum-drive XL cells excluded from the mapping, structural ICG as in the earlier flow, the analog macros as black boxes.

  python synth/opt/synth_opt.py --build full --out work/opt/<tag> [--g 4] [--lib slow] [--period 10] [--dont-use 'XL']
Writes <out>/netlist.v (cells + hierarchy flattened, macros black boxes with their parameters stripped), <out>/netlist_raw.v (as Yosys wrote it, for gate-level simulation), stat.txt.
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

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
sys.path.insert(0, str(ROOT / "scripts"))
import synth_ppa as S  # noqa: E402

PDK_LIB = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lib"


DEBUG_OUTPUTS = ("x_o", "v_o", "scores_o", "top1_idx_o", "top1_o", "top2_o", "margin_o", "group_idx_o", "bitrow_idx_o", "rd_valid_o", "q_rows_gated_o")


def strip_constant_outputs(v: str) -> tuple[str, dict]:
    """Primary outputs that synthesis proved constant (the 32-bit instrumentation counters at INSTRUMENT_EN = 0, the simulation-only assertion bits) are not pins of the laid-out chip: a pin, a
    tie cell and an output buffer each for 489 bits of nothing. They are removed from the module and recorded (value, width); the gate-level testbench ties them off at its end."""
    i0 = v.index("module cim_neurohdc_top(")
    i1 = v.index("endmodule", i0) + len("endmodule")
    head, body, tail = v[:i0], v[i0:i1], v[i1:]
    v_all, v = v, body
    ports = {}
    for m in re.finditer(r"^  assign (\w+) = (\d+)'[hd]([0-9a-f]+);\n", v, re.M):
        name, width, val = m.group(1), int(m.group(2)), int(m.group(3), 16 if m.group(0).find("'h") > 0 else 10)
        if re.search(rf"^  output (?:\[\d+:\d+\] )?{name};", v, re.M):
            ports[name] = dict(width=width, value=val)
    for name in ports:
        v = re.sub(rf"^  assign {name} = [^;]*;\n", "", v, flags=re.M)
        v = re.sub(rf"^  output (?:\[\d+:\d+\] )?{name};\n", "", v, flags=re.M)
        v = re.sub(rf"^  wire (?:\[\d+:\d+\] )?{name};\n", "", v, flags=re.M)
        v = re.sub(rf"(module cim_neurohdc_top\([^)]*?)(?:, {name}\b|\b{name}, )", r"\1", v, count=1, flags=re.S)
    # observation-only outputs of the verification harness (internal state a chip would not bring out): X, V, the class scores, the leader / second score / margin, the read side-band, the access counters
    for name in DEBUG_OUTPUTS:
        m = re.search(rf"^  output (\[\d+:\d+\] )?{name};\n", v, re.M)
        if not m or name in ports:
            continue
        rng = m.group(1) or ""
        v = v.replace(m.group(0), "" if re.search(rf"^  wire (\[\d+:\d+\] )?{name};", v, re.M) else f"  wire {rng}{name};\n")
        v = re.sub(rf"(module cim_neurohdc_top\([^)]*?)(?:, {name}\b|\b{name}, )", r"\1", v, count=1, flags=re.S)
        ports[name] = dict(width=int(re.search(r"\[(\d+):0\]", rng).group(1)) + 1 if rng else 1, value=0, unobserved=True)
    return head + v + tail, ports


def set_rtl_root(root: Path) -> None:
    """Synthesise the RTL of another tree (a snapshot taken at an earlier optimisation step) instead of the repository's."""
    r = root / "rtl"
    S.RTL = (sorted((r / "pkg").glob("*.sv")) + sorted((r / "common").glob("*.sv")) + sorted((r / "phase1_snn").glob("*.sv")) + sorted((r / "phase2_hdc").glob("*.sv"))
             + sorted((r / "phase4_exit").glob("*.sv")) + sorted((r / "phase3_top").glob("*.sv")))


def synth(build: str, out: Path, g: int, lib_corner: str, period: float, dont_use: list[str], extra_params: str = "", hier: bool = False, abc_extra: str = "", gate_min: int = 4) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    lib = PDK_LIB / S.LIBS[lib_corner]
    f, e = S.BUILDS[build]
    S.CFG.update(gate=4, rtl_gating=1, isolate=1, instr=0)
    stub = S.stub_liberty(out, f, e)
    constr = out / "abc.constr"
    constr.write_text("set_driving_cell BUFX2\nset_load 0.02\n")
    du = " ".join(f"-dont_use {c}" for c in dont_use)
    flat = "" if hier else "flatten -noscopeinfo"
    script = textwrap.dedent(f"""\
        {S.read_cmds()}
        {S.params_cmd(f, e).replace(S.TOP, f"-set ROWS_PER_GROUP {g} {extra_params} " + S.TOP)}
        hierarchy -check -top {S.TOP}
        techmap -map {SYNTH / 'icg_map.v'}
        {flat}
        proc
        opt -purge -nosdff
        memory
        opt -purge -nosdff
        async2sync
        techmap
        opt -purge -nosdff
        clockgate -liberty {lib} -min_net_size {gate_min}
        dfflibmap -liberty {lib}
        abc -liberty {lib} -g cmos -D {int(period * 1000)} -constr {constr} {du} {abc_extra}
        opt_clean -purge
        setundef -zero -undriven
        tee -o {out}/stat.txt stat -liberty {lib}
        write_verilog -noattr {out}/netlist_y.v
        """)
    (out / "synth.ys").write_text(script)
    t0 = time.time()
    r = subprocess.run(["yosys", "-l", str(out / "yosys.log"), str(out / "synth.ys")], capture_output=True, text=True, cwd=out)
    if r.returncode:
        raise SystemExit("yosys failed: " + (r.stdout + r.stderr)[-1500:])
    raw = out / "netlist_raw.v"
    (out / "netlist_y.v").replace(raw)
    v, const_ports = strip_constant_outputs(raw.read_text())
    v = re.sub(r"\b(wire|reg|output|input) signed\b", r"\1", v)           # the P&R readers do not take `signed` in net declarations
    raw.write_text(v)
    (out / "const_ports.json").write_text(json.dumps(const_ports, indent=1))
    (out / "netlist.v").write_text(re.sub(r"\b(cim_macro|hdc_class_array|sign_sram) #\((?:\s*\.\w+\([^)]*\),?)+\s*\)", r"\1", v))
    txt = (out / "stat.txt").read_text()
    m = re.findall(r"Chip area for (?:top )?module\s+'?\\?[^':\n]+'?\s*:\s*([\d.eE+\-]+)", txt)
    d = dict(area_um2=float(m[-1]) if m else None, wall_s=round(time.time() - t0), **S.parse_stat(txt), stub=str(stub))
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="full")
    ap.add_argument("--out", required=True)
    ap.add_argument("--g", type=int, default=4)
    ap.add_argument("--lib", default="slow")
    ap.add_argument("--period", type=float, default=10.0)
    ap.add_argument("--dont-use", nargs="*", default=["*XL"])
    ap.add_argument("--rtl-root", default=None)
    ap.add_argument("--set", default="", help="extra chparam settings, e.g. '-set A0_SKIP_EN 0'")
    a = ap.parse_args()
    if a.rtl_root:
        set_rtl_root(Path(a.rtl_root))
    print(synth(a.build, Path(a.out).resolve(), a.g, a.lib, a.period, a.dont_use, a.set))
