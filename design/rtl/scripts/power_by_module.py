#!/usr/bin/env python3
"""Power of the synthesized digital design BY MODULE: hierarchy-preserving synthesis (so the combinational cells keep their module), the same gate-level activity run as synth_power.py
(real DVS-Gesture sample, same window), OpenSTA `report_power -instances` on every leaf cell, summed per module path. Writes <out>/<build>/power_by_module<tag>/modules.json.

The hierarchical mapping differs slightly from the flattened one the headline numbers use (no cross-module optimisation), so the per-module numbers are a breakdown of a nearby netlist: the
report states the total of this netlist next to the flat total.

  python design/rtl/scripts/power_by_module.py --builds full --gate 4 --instr 0 --out ppa_gated
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import synth_ppa as S  # noqa: E402
import synth_power as P  # noqa: E402

ROW = re.compile(r"^\s*([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+(\S+)\s*$")


def sta_instances(work: Path, net: Path, libs: list[Path], period: float, vcd: Path, scope: str, tag: str) -> dict:
    rpt = work / f"power_inst_{tag}.rpt"
    tot = work / f"power_total_{tag}.rpt"
    tcl = "\n".join([*(f"read_liberty {l}" for l in libs), f"read_verilog {net}", f"link_design {S.TOP}", f"create_clock -name clk -period {period} [get_ports {S.CLK}]",
                     f"read_vcd -scope {scope} {vcd}", f"report_power > {tot}",
                     'set leaf [get_cells -hierarchical -filter "is_hierarchical == 0" *]', f"report_power -instances $leaf > {rpt}",
                     f'set fh [open {work}/refs_{tag}.txt w]', 'foreach c $leaf { puts $fh "[get_full_name $c] [get_property $c ref_name]" }', "close $fh", "exit"]) + "\n"
    (work / f"power_inst_{tag}.tcl").write_text(tcl)
    r = S.run([str(ROOT / "tools" / "sta"), "-no_init", "-no_splash", "-exit", str(work / f"power_inst_{tag}.tcl")], cwd=work, log=work / f"power_inst_{tag}.log", timeout=7200)
    rows = []
    refs = dict(l.split() for l in (work / f"refs_{tag}.txt").read_text().splitlines() if l.strip()) if (work / f"refs_{tag}.txt").exists() else {}
    for line in rpt.read_text().splitlines():
        m = ROW.match(line)
        if m:
            rows.append((m.group(5), *(float(m.group(i)) for i in (1, 2, 3, 4)), refs.get(m.group(5), "?")))        # name, internal, switching, leakage, total, library cell
    return dict(rows=rows, returncode=r.returncode, total_report=tot.read_text() if tot.exists() else "")


def module_of(path: str, depth: int) -> str:
    parts = path.split("/")[:-1]
    return ".".join(parts[:depth]) if parts else "(top glue)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", nargs="+", default=["full"])
    ap.add_argument("--row", type=int, default=46)
    ap.add_argument("--start", type=int, default=12000)
    ap.add_argument("--len", type=int, default=8000)
    ap.add_argument("--theta", type=int, default=4095)
    ap.add_argument("--period", type=float, default=10.0)
    ap.add_argument("--lib-dir", default=str(S.DEFAULT_LIB_DIR))
    ap.add_argument("--tag", default="")
    ap.add_argument("--init-flops", action="store_true", help="start every library flip-flop model at 0 instead of X (4-state reconvergence pessimism: an ABC cone such as ~((q & k) | ~(a | q)) is 0 for any "
                    "known q but X for q = X, so a reset that is correct in silicon never clears the X in a zero-delay gate-level run); used only for measurement baselines")
    S.add_flow_args(ap)
    a = ap.parse_args()
    S.apply_flow_args(a)
    lib = Path(a.lib_dir) / S.LIBS["fast"]
    gl = S.OUT / "gl"
    gl.mkdir(parents=True, exist_ok=True)
    cells = P.liberty_models(lib, gl / "cells_fast.v")
    if a.init_flops:
        import re
        txt = cells.read_text()
        out_txt = re.sub(r"(module E?DFF\w*\(.*?endmodule)", lambda m: re.sub(r"^(\s*reg \w+);", r"\1 = 1'b0;", m.group(1), flags=re.M), txt, flags=re.S)
        cells = cells.with_name("cells_fast_init0.v")
        cells.write_text(out_txt)
    for b in a.builds:
        f, e = S.BUILDS[b]
        work = S.OUT / b / ("power_by_module" + a.tag)
        work.mkdir(parents=True, exist_ok=True)
        stub = S.stub_liberty(work, f, e)
        t0 = time.time()
        net, _, area, stat = S.synth(work, lib, f, e, False, "hier_buf_fast", a.period, True)
        net_raw = net.with_name(net.stem + "_raw.v")
        g = P.gate_sim(b, work, net_raw, cells, a.row, a.start, a.len, a.theta)
        r = sta_instances(work, net, [lib, stub], a.period, g["vcd"], "hdc_gate_tb/dut", "hier")
        g["vcd"].unlink()
        out = {}
        for depth in (1, 2):
            agg: dict[str, list] = {}
            for name, i, sw, lk, tt, ref in r["rows"]:
                m = module_of(name, depth)
                d = agg.setdefault(m, [0.0, 0.0, 0.0, 0.0, 0])
                d[0] += i; d[1] += sw; d[2] += lk; d[3] += tt; d[4] += 1
            out[f"depth{depth}"] = {m: dict(internal_w=v[0], switching_w=v[1], leakage_w=v[2], total_w=v[3], cells=v[4]) for m, v in sorted(agg.items(), key=lambda kv: -kv[1][3])}
        bytype: dict[str, dict] = {}
        for name, i, sw, lk, tt, ref in r["rows"]:
            m = module_of(name, 2)
            kind = "ICG" if ref.startswith("TLAT") else "flop" if re.match(r"(E?DFF|SDFF)", ref) else "comb"
            d = bytype.setdefault(m, {}).setdefault(kind, [0.0, 0.0, 0.0, 0.0, 0])
            d[0] += i; d[1] += sw; d[2] += lk; d[3] += tt; d[4] += 1
        out["by_kind_depth2"] = {m: {k: dict(internal_w=v[0], switching_w=v[1], leakage_w=v[2], total_w=v[3], cells=v[4]) for k, v in kinds.items()} for m, kinds in bytype.items()}
        res = dict(build=b, gate=S.CFG["gate"], instr=S.CFG["instr"], rtl_gating=S.CFG["rtl_gating"], isolate=S.CFG["isolate"], area_um2_hier=area, window=dict(row=a.row, start=a.start, len=a.len), gate_level_matches_golden=g["gate_level_matches_golden"],
                   timesteps_checked=g["timesteps_checked"], sum_of_instances_w=sum(x[4] for x in r["rows"]), total_report=r["total_report"], modules=out, wall_s=round(time.time() - t0))
        (work / "modules.json").write_text(json.dumps(res, indent=1))
        print(f"[{b}] gate {S.CFG['gate']} rtl-gating {S.CFG['rtl_gating']} instr {S.CFG['instr']}: sum of leaf cells {res['sum_of_instances_w'] * 1e3:.4f} mW; golden {g['gate_level_matches_golden']}")
        for m, v in list(out["depth2"].items())[:12]:
            kinds = out["by_kind_depth2"].get(m, {})
            print(f"   {m:24s} {v['total_w'] * 1e6:8.1f} uW  (internal {v['internal_w'] * 1e6:7.1f}, switching {v['switching_w'] * 1e6:7.1f}, leakage {v['leakage_w'] * 1e6:5.1f})  {v['cells']:6d} cells   " +
                  "  ".join(f"{k} {x['total_w'] * 1e6:.1f}" for k, x in sorted(kinds.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
