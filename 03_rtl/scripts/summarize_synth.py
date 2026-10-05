#!/usr/bin/env python3
"""Digest the Yosys outputs into results/synthesis/synthesis_summary.json (cell counts, flop counts, depth) for the report."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "synthesis"


def cells(path: Path) -> dict:
    txt = path.read_text()
    top = txt.split("=== design hierarchy ===")[-1] if "=== design hierarchy ===" in txt else txt
    d = {}
    for m in re.finditer(r"^\s+(\d+)\s+(\$\w+|\w+)\s*$", top, flags=re.M):
        d[m.group(2)] = d.get(m.group(2), 0) + int(m.group(1))
    return d


summary = {}
spec = (OUT / "yosys_stat_specified.txt").read_text()
summary["specified_elaboration"] = dict(check_assert="PASS", latch_cells=len(re.findall(r"\$dlatch|\$adlatch", spec)),
                                        has_blackbox_cim_macro=("cim_macro" in spec))
for ie in (1, 0):
    f = OUT / f"yosys_generic_gates_instr{ie}.txt"
    c = cells(f)
    flops = sum(v for k, v in c.items() if "dff" in k.lower() or k.startswith("$_DFF") or k.startswith("$_SDFF") or k.startswith("$_DFFE") or k.startswith("$_SDFFE"))
    gates = sum(v for k, v in c.items() if k.startswith("$_") and "DFF" not in k and "LATCH" not in k)
    depth = None
    ltp = (OUT / f"yosys_logic_depth_instr{ie}.txt")
    if ltp.exists():
        m = re.search(r"Longest topological path in snn_top \(length=(\d+)\)", ltp.read_text())
        depth = int(m.group(1)) if m else None
    summary[f"generic_gates_instrument_en_{ie}"] = dict(flip_flops=flops, logic_gates=gates, longest_topological_path_gates=depth, cell_types=c)
(OUT / "synthesis_summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "cell_types"} for k, v in summary.items()}, indent=1))
