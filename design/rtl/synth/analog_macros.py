#!/usr/bin/env python3
"""D2: the analog macros as seen by the digital flow - their AREA at both cell assumptions, and their LEF and (timing-only) Liberty.

AREA (writes synth/results/analog_area.json). Three numbers, with the assumption each rests on:
  1C analytic   : studies/crossbar/results/sense_frontend/area_table_1f.json, 'c_dec=1nF|mid' (20 F^2 cell, 1 nF supply decoupling, +20 % overhead) = 0.4289 mm^2. Phase 5's number.
  NeuroSim, A2  : NeuroSim's smallest feasible cell (40 F x 4 F; it refuses 20 F^2 - see run_neurosim.py) - the closest NeuroSim comes to 1C's assumption.
  NeuroSim, B   : 128 F x 4 F cell = the select-transistor width the write path needs (1D). THE CHIP-LEVEL NUMBER USES THIS ONE (the larger).
Composition of the NeuroSim-based numbers (NeuroSim for the array, 1F for the front-end, as the brief says):
  5 x NeuroSim (cell array + word-line switch matrix + source-line switch matrix + column mux + mux decoder)      <- NeuroSim
  + 1F's ladder / gain storage, sense front-ends, calibration storage, supply straps (1C 'mid')                    <- 1F (NeuroSim's generic MLSA / ADC / adders are NOT used)
  + 1F's 1 nF decoupling (166,667 um^2 at 'mid'); + 20 % overhead on everything, exactly as 1C does.
The PDK has no decap cells (only FILL1..FILL64), so place-and-route inserts no decap of its own and 1F's decoupling is not double counted.

LEF / LIB (writes synth/macro/*.lef, *.lib): a bounding box of that area, the pins of the RTL black box (ports taken from the Yosys port list of this very elaboration), pins on Metal4
(outputs) and Metal6 (inputs) along the bottom edge, supply pins on Metal6/Metal10 stripes, blockage Metal1-10 over the macro (Metal11 stays free: the power grid's top layer crosses the macro's Metal10 supply stripes). The Liberty is timing only: clk -> output
0.3 ns (Phase 5's constraint, ARRAY_CLK_TO_Q_NS) and zero power - the macro's energy is 1F's 186 pJ per non-zero read, kept as a separate term.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import synth_ppa as S  # noqa: E402

RES = HERE / "results"
MACRO = HERE / "macro"
AREA_TABLE = REPO / "studies" / "crossbar" / "results" / "sense_frontend" / "area_table_1f.json"
NEUROSIM = RES / "neurosim.json"
PHASE5 = ROOT / "results" / "ppa" / "phase5_tables.json"
N_MACROS = 5
GRID = 0.005


def area_options() -> dict:
    t = json.loads(AREA_TABLE.read_text())["c_dec=1nF|mid"]["parts_um2"]
    ns = json.loads(NEUROSIM.read_text())["variants"]
    f1 = {k: t[k] for k in ("ladder_and_gain_storage", "sense_front_ends_1f", "calibration_storage", "supply_ground_straps")}
    decap = t["decoupling"]
    out = {"1C_analytic_20F2": dict(assumption="20 F^2 1T1R cell (1A-1C), 1 nF decap, 'mid' periphery", total_um2=sum(t.values()), parts_um2=t)}
    for tag, name in (("A2_40F", "NeuroSim, smallest feasible cell (40 F x 4 F)"), ("B_128F", "NeuroSim, 128 F x 4 F cell (select transistor the write path needs)")):
        v = ns[tag]
        m = v["area_modules_um2"]
        side = {"cell_array": v["area_array_um2"], "wl_switch_matrix": m["wlNewSwitchMatrix"] + m["wlSwitchMatrix"], "sl_switch_matrix": m["slSwitchMatrix"], "column_mux": m["mux"] + m["muxDecoder"]}
        side5 = {k: N_MACROS * x for k, x in side.items()}
        parts = {**side5, **f1, "decoupling": decap}
        base = sum(parts.values())
        parts["overhead_20pct"] = 0.2 * base
        out[tag] = dict(assumption=name, neurosim_macro_um2=v["area_macro_um2"], neurosim_cell_array_per_macro_um2=v["area_array_um2"], total_um2=base * 1.2, parts_um2=parts)
    out["chip_level_choice"] = dict(variant="B_128F", reason="the select-transistor width the write path requires (1D); the larger of the NeuroSim variants, as the brief requires - not quietly the smaller")
    return out


def hdc_area_mm2(build: str) -> float:
    t = json.loads(PHASE5.read_text())["builds"]
    return t[f"{build}_g4"]["area_mm2"]["hdc_array"]


def snap(x: float) -> float:
    return round(round(x / GRID) * GRID, 3)


def lef_for(name: str, ports: dict, area_um2: float, aspect: float = 1.0) -> tuple[str, float, float]:
    ROW = 1.71                                                       # site-row height of the standard-cell library: the macro spans a whole number of rows (flush placement)
    h = round(math.ceil(math.sqrt(area_um2 / aspect) / ROW) * ROW, 3)
    w = round(math.ceil(area_um2 / h / 0.2) * 0.2, 3)               # width on the 0.2 um site grid
    ins = [(n, p) for n, p in ports.items() if p["direction"] == "input" and n not in ("clk_i",)]
    outs = [(n, p) for n, p in ports.items() if p["direction"] == "output"]
    L = ["VERSION 5.7 ;", 'BUSBITCHARS "[]" ;', 'DIVIDERCHAR "/" ;', "", f"MACRO {name}", "  CLASS BLOCK ;", "  ORIGIN 0 0 ;", f"  FOREIGN {name} 0 0 ;", f"  SIZE {w} BY {h} ;", "  SYMMETRY X Y R90 ;"]
    nbits = lambda items: sum(len(p["bits"]) for _, p in items)          # noqa: E731
    pitch, y1 = 0.4, 1.0
    top_inputs = False
    if max(nbits(outs), nbits(ins)) * pitch > w - 3.0:
        pitch = 0.2                                                       # one routing track per pin (tight but legal on Metal4 / Metal6)
    if max(nbits(outs), nbits(ins)) * pitch > w - 3.0:
        top_inputs = True                                                 # small macro: outputs on the bottom edge, inputs on the top edge
    cap = int((w - 2.0) / pitch)

    def pins(items, layer, x0, top=False):
        k = 0
        res = []
        for n, p in items:
            width = len(p["bits"])
            for b in range(width):
                pn = n if width == 1 else f"{n}[{b}]"
                x = x0 + k * pitch
                assert x + 0.1 < w, f"{name}: {len(ports)} ports do not fit the bottom edge"
                ya, yb = (h - y1, h) if top else (0, y1)
                res += [f"  PIN {pn}", f"    DIRECTION {'INPUT' if (n, p) in ins else 'OUTPUT'} ;", "    USE SIGNAL ;", "    PORT", f"      LAYER {layer} ;", f"        RECT {x:.3f} {ya:.3f} {x + 0.08:.3f} {yb:.3f} ;",
                        "    END", f"  END {pn}"]
                k += 1
        return res, k

    clk = ["  PIN clk_i", "    DIRECTION INPUT ;", "    USE CLOCK ;", "    PORT", "      LAYER Metal6 ;", f"        RECT {w - 2:.3f} 0 {w - 1.92:.3f} {y1} ;", "    END", "  END clk_i"]
    po, n_out = pins(outs, "Metal4", 1.0)
    pi, n_in = pins(ins, "Metal6", 1.2 if not top_inputs else 1.0, top=top_inputs)
    assert n_out <= cap and n_in <= cap, f"{name}: {n_out} outputs / {n_in} inputs exceed the {cap} positions of the bottom edge"
    L += clk + po + pi
    for nm, use in (("VDD", "POWER"), ("VSS", "GROUND")):
        L += [f"  PIN {nm}", "    DIRECTION INOUT ;", f"    USE {use} ;", "    PORT"]
        off = 5.0 if nm == "VDD" else 9.0
        x = off
        while x + 1.0 < w:
            L += ["      LAYER Metal10 ;", f"        RECT {x:.3f} {y1 + 1:.3f} {x + 1.0:.3f} {h - 1:.3f} ;"]
            x += 16.0
        L += ["    END", f"  END {nm}"]
    L += ["  OBS"]
    for i in range(1, 11):
        L += [f"    LAYER Metal{i} ;", f"      RECT 0 {y1 + 0.2:.3f} {w} {h} ;"]
    L += ["  END", f"END {name}", "", "END LIBRARY"]
    return "\n".join(L) + "\n", w, h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="B_128F", choices=["B_128F", "A2_40F", "1C_analytic_20F2"], help="which area the CIM macro LEF uses (default: the chip-level choice)")
    a = ap.parse_args()
    RES.mkdir(parents=True, exist_ok=True)
    MACRO.mkdir(parents=True, exist_ok=True)
    opts = area_options()
    (RES / "analog_area.json").write_text(json.dumps(opts, indent=1))
    for k in ("1C_analytic_20F2", "A2_40F", "B_128F"):
        print(f"{k:18s} {opts[k]['total_um2'] * 1e-6:.4f} mm^2   ({opts[k]['assumption']})")
    summary = {}
    for build, (f, e) in S.BUILDS.items():
        if build not in ("full", "fact_off"):
            continue                                                        # the two black-box port sets (factorized or not); ee_off / both_off share them
        work = RES / "ports" / build
        work.mkdir(parents=True, exist_ok=True)
        S.CFG.update(gate=4, rtl_gating=1, isolate=1, instr=0)
        lib = S.stub_liberty(work, f, e)
        mods = json.loads((work / "ports.json").read_text())["modules"]
        for m in S.ANALOG:
            if m not in mods:
                continue
            area = (opts[a.variant]["total_um2"] if m == "cim_macro" else hdc_area_mm2(build) * 1e6)
            suffix = "" if m == "cim_macro" else ("_fact" if f else "_unfact")
            nm = m + suffix
            ports = mods[m]["ports"]
            lef, w, h = lef_for(m, ports, area)
            (MACRO / f"{nm}.lef").write_text(lef)
            txt = lib.read_text()
            cell = re.search(rf"  cell \({m}\) \{{.*?\n  \}}\n", txt, re.S).group(0).replace("area : 0;", f"area : {area:.3f};")
            head = txt[: txt.index("  cell (")]
            (MACRO / f"{nm}.lib").write_text(head + cell + "}\n")
            summary[nm] = dict(build_ports_from=build, area_um2=area, width_um=w, height_um=h, n_ports=len(ports), n_bits=sum(len(p["bits"]) for p in ports.values()))
            print(f"{nm:16s} {w:8.1f} x {h:8.1f} um  {area * 1e-6:.4f} mm^2  {summary[nm]['n_bits']} pin bits")
    (RES / "analog_macros.json").write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
