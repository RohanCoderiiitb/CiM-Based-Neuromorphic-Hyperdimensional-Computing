#!/usr/bin/env python3
"""LEF + Liberty (timing / leakage / per-access energy) of the three macros of the optimised design, from the port lists of the CURRENT RTL (Yosys elaboration of the repository RTL):
  cim_macro        analog crossbar: area from the NeuroSim 128 F variant (results/analog_area.json) + the group decoder it now contains (item 6: the 512 row wires became g row bits + a group index)
  hdc_class_array  class-hypervector arrays (Phase 5 model), fact / unfact
  count_sram       the event-counter SRAM (item 3): CACTI 7 (HP Labs), 45 nm, ITRS low-operating-power cells and periphery, scratch RAM, 1 kB (512 x 16 b), 1 read/write port, 350 K,
                   minimum-area objective: area 3,745 um^2, read 0.632 pJ, write 0.635 pJ per access, leakage 15.5 uW, access 0.479 ns, cycle 0.396 ns.  [ASSUM] (generic ITRS 45 nm, not this PDK's SRAM).
Pins: bottom edge, pitch --pitch um (default 1.2 = three Metal4/Metal6 tracks; the earlier macro had 0.4 um for 2,178 pins). Macro inputs get SETUP/HOLD arcs against clk_i ([ASSUM] 0.5 / 0.1 ns for the
crossbar - the group decoder and row-driver enable sit behind the pins - 0.2 / 0.05 ns for the SRAM); outputs launch 0.3 ns (crossbar) / 0.6 ns (SRAM, CACTI 0.48 ns access + margin) after the clock.
  python opt/gen_macros.py --out work/opt/<tag>/macro [--build full] [--pitch 1.2] [--cim-area-um2 N]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
sys.path.insert(0, str(ROOT / "scripts"))
import synth_ppa as S  # noqa: E402

GRID = 0.005
ROW = 1.71
CACTI = dict(area_um2=3745.0, read_pj=0.632, write_pj=0.635, leak_uw=15.5, access_ns=0.479, cycle_ns=0.396)
CACTI_SIGN = dict(area_um2=1130.0, read_pj=0.284, write_pj=0.340, leak_uw=4.64, access_ns=0.394)      # 256 B (128 x 16 b), same CACTI settings
DECODER_UM2 = 3000.0           # [ASSUM] 7-bit group decode + 512 AND2 row-enable gates inside the crossbar macro (item 6)
TIMING = {"cim_macro": dict(clk_to_q=0.3, setup=0.5, hold=0.1), "hdc_class_array": dict(clk_to_q=0.3, setup=0.5, hold=0.1), "count_sram": dict(clk_to_q=0.6, setup=0.2, hold=0.05), "sign_sram": dict(clk_to_q=0.6, setup=0.2, hold=0.05)}


def lef(name: str, ports: dict, w: float, h: float, pitch: float, y1: float = 1.0) -> str:
    ins = [(n, p) for n, p in ports.items() if p["direction"] == "input" and n != "clk_i"]
    outs = [(n, p) for n, p in ports.items() if p["direction"] == "output"]
    L = ["VERSION 5.7 ;", 'BUSBITCHARS "[]" ;', 'DIVIDERCHAR "/" ;', "", f"MACRO {name}", "  CLASS BLOCK ;", "  ORIGIN 0 0 ;", f"  FOREIGN {name} 0 0 ;", f"  SIZE {w} BY {h} ;", "  SYMMETRY X Y R90 ;"]
    nb = lambda items: sum(len(p["bits"]) for _, p in items)          # noqa: E731
    top_inputs = False
    if (nb(outs) + nb(ins)) * pitch + 4.0 >= w:                      # small macro: inputs go to the top edge, the pitch shrinks to what the edge holds (not below 0.2 um)
        top_inputs = True
        pitch = max(0.2, min(pitch, (w - 4.0) / max(nb(outs), nb(ins), 1)))
        pitch = math.floor(pitch / 0.2) * 0.2
    assert max(nb(outs), nb(ins)) * pitch + 3.0 < w if top_inputs else (nb(outs) + nb(ins)) * pitch + 4.0 < w, f"{name}: pins do not fit"

    def pins(items, layer, x0, direction, top=False):
        k, res = 0, []
        for n, p in items:
            width = len(p["bits"])
            for b in range(width):
                pn = n if width == 1 else f"{n}[{b}]"
                x = x0 + k * pitch
                ya, yb = (h - y1, h) if top else (0.0, y1)
                res += [f"  PIN {pn}", f"    DIRECTION {direction} ;", "    USE SIGNAL ;", "    PORT", f"      LAYER {layer} ;", f"        RECT {x:.3f} {ya:.3f} {x + 0.08:.3f} {yb:.3f} ;", "    END", f"  END {pn}"]
                k += 1
        return res, k

    clk = ["  PIN clk_i", "    DIRECTION INPUT ;", "    USE CLOCK ;", "    PORT", "      LAYER Metal6 ;", f"        RECT 0.400 0 0.480 {y1}", "    END", "  END clk_i"]
    clk[5] = clk[5] + " ;"
    both_top = top_inputs and w > 200                              # a large macro (the unfactorised class array) sits with its top edge towards the logic: outputs (Metal4) interleave with the inputs (Metal6) there instead of going to the far, blocked bottom edge
    po, n_out = pins(outs, "Metal4", 1.4 if both_top else 1.2, "OUTPUT", top=both_top)
    pi, n_in = pins(ins, "Metal6", 1.0 if top_inputs else 1.2 + (n_out + 1) * pitch, "INPUT", top=top_inputs)
    L += clk + po + pi
    for nm, use in (("VDD", "POWER"), ("VSS", "GROUND")):
        L += [f"  PIN {nm}", "    DIRECTION INOUT ;", f"    USE {use} ;", "    PORT"]
        x = 5.0 if nm == "VDD" else 9.0
        while x + 1.0 < w:
            L += ["      LAYER Metal10 ;", f"        RECT {x:.3f} {y1 + 1:.3f} {x + 1.0:.3f} {h - 1:.3f} ;"]
            x += 16.0
        L += ["    END", f"  END {nm}"]
    L += ["  OBS"]
    for i in range(1, 11):
        L += [f"    LAYER Metal{i} ;", f"      RECT 0 {y1 + 0.2:.3f} {w} {h} ;"]
    L += ["  END", f"END {name}", "", "END LIBRARY"]
    return "\n".join(L) + "\n"


def lib(name: str, ports: dict, area: float, leak_pw: float = 0.0, energy: dict | None = None) -> str:
    t = TIMING[name]
    widths = sorted({len(p["bits"]) for p in ports.values() if len(p["bits"]) > 1})
    L = [f"library ({name}_lib) {{", "  delay_model : table_lookup;", '  time_unit : "1ns";', "  capacitive_load_unit (1,pf);", '  voltage_unit : "1V";', '  current_unit : "1mA";',
         '  leakage_power_unit : "1pW";', '  pulling_resistance_unit : "1kohm";', "  nom_voltage : 1.0;", "  default_cell_leakage_power : 0;",
         '  lu_table_template (scalar) { variable_1 : input_net_transition; index_1 ("0.1"); }',
         '  lu_table_template (cons) { variable_1 : constrained_pin_transition; index_1 ("0.1"); }',
         '  power_lut_template (pscalar) { variable_1 : input_transition_time; index_1 ("0.1"); }']
    L += [f"  type (bus{w}) {{ base_type : array; data_type : bit; bit_width : {w}; bit_from : {w - 1}; bit_to : 0; }}" for w in widths]
    L += [f"  cell ({name}) {{", f"    area : {area:.3f};", "    dont_touch : true;", f"    cell_leakage_power : {leak_pw:.1f};"]
    for n, p in ports.items():
        w = len(p["bits"])
        head = f"{'bus' if w > 1 else 'pin'} ({n})" + (f" {{ bus_type : bus{w};" if w > 1 else " {")
        if p["direction"] == "input":
            body = [f"    {head} direction : input; capacitance : 0.002;"]
            if n == "clk_i":
                if energy:
                    for cond, e in energy.items():
                        body.append(f'      internal_power () {{ when : "{cond}"; rise_power (pscalar) {{ index_1 ("0.1"); values ("{e}"); }} fall_power (pscalar) {{ index_1 ("0.1"); values ("0"); }} }}')
            else:
                fall = energy is not None and name == "count_sram" and n in ("we_i", "wa_i", "wd_i")           # the SRAM's write port is captured on the falling edge
                for typ, val in (("setup", t["setup"]), ("hold", t["hold"])):
                    body.append(f'      timing () {{ related_pin : "clk_i"; timing_type : {typ}_{"falling" if fall else "rising"}; rise_constraint (cons) {{ index_1 ("0.1"); values ("{val}"); }} fall_constraint (cons) {{ index_1 ("0.1"); values ("{val}"); }} }}')
            body.append("    }")
            L += body
        else:
            L += [f"    {head} direction : output; capacitance : 0;",
                  f'      timing () {{ related_pin : "clk_i"; timing_type : rising_edge; timing_sense : non_unate; cell_rise (scalar) {{ index_1 ("0.1"); values ("{t["clk_to_q"]}"); }} cell_fall (scalar) {{ index_1 ("0.1"); values ("{t["clk_to_q"]}"); }}'
                  ' rise_transition (scalar) { index_1 ("0.1"); values ("0.1"); } fall_transition (scalar) { index_1 ("0.1"); values ("0.1"); } }', "    }"]
    L += ["  }", "}"]
    return "\n".join(L) + "\n"


def dims(area: float, aspect: float = 1.0) -> tuple[float, float]:
    h = round(math.ceil(math.sqrt(area / aspect) / ROW) * ROW, 3)
    w = round(math.ceil(area / h / 0.2) * 0.2, 3)
    return w, h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--build", default="full")
    ap.add_argument("--pitch", type=float, default=1.2)
    ap.add_argument("--cim-area-um2", type=float, default=None, help="crossbar macro area incl. the group decoder (default: NeuroSim 128 F + DECODER_UM2)")
    ap.add_argument("--g", type=int, default=4)
    ap.add_argument("--cols", type=int, default=40, help="N_PARALLEL_COLS of the digital design (width of the macro result bus)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f, e = S.BUILDS[a.build]
    S.CFG.update(gate=4, rtl_gating=1, isolate=1, instr=0)
    S.ANALOG = ("cim_macro", "hdc_class_array", "count_sram", "sign_sram")
    work = out / "ports"
    work.mkdir(exist_ok=True)
    S.params_cmd = (lambda orig: (lambda fz, ee: orig(fz, ee).replace(S.TOP, f"-set ROWS_PER_GROUP {a.g} -set N_PARALLEL_COLS {a.cols} " + S.TOP)))(S.params_cmd)
    S.stub_liberty(work, f, e)
    mods = json.loads((work / "ports.json").read_text())["modules"]
    area_opts = json.loads((SYNTH / "results" / "analog_area.json").read_text())
    hdc_json = json.loads((SYNTH / "results" / "analog_macros.json").read_text())
    summary = {}
    for m in ("cim_macro", "hdc_class_array", "count_sram", "sign_sram"):
        ports = mods[m]["ports"]
        if m == "cim_macro":
            area = a.cim_area_um2 or (area_opts["B_128F"]["total_um2"] + DECODER_UM2)
            w, h = dims(area)
        elif m == "hdc_class_array":
            key = "hdc_class_array_fact" if f else "hdc_class_array_unfact"
            area = hdc_json[key]["area_um2"]
            w, h = dims(area)
        elif m == "sign_sram":
            area = CACTI_SIGN["area_um2"]
            w, h = dims(area, aspect=1.4)
            w = max(w, round(((sum(len(p["bits"]) for p in ports.values()) + 2) * a.pitch + 6) / 0.2 + 0.5) * 0.2)
        else:
            area = CACTI["area_um2"]
            w, h = dims(area, aspect=1.4)
            w = max(w, round(((sum(len(p["bits"]) for p in ports.values()) + 2) * a.pitch + 6) / 0.2 + 0.5) * 0.2)
        (out / f"{m}.lef").write_text(lef(m, ports, w, h, a.pitch))
        if m == "count_sram":
            txt = lib(m, ports, w * h, leak_pw=CACTI["leak_uw"] * 1e6, energy={"re_i": CACTI["read_pj"], "we_i": CACTI["write_pj"]})
        elif m == "sign_sram":
            txt = lib(m, ports, w * h, leak_pw=CACTI_SIGN["leak_uw"] * 1e6, energy={"re_i": CACTI_SIGN["read_pj"], "we_i": CACTI_SIGN["write_pj"]})
        else:
            txt = lib(m, ports, area)
        (out / f"{m}.lib").write_text(txt)
        summary[m] = dict(area_um2=area, width_um=w, height_um=h, n_pin_bits=sum(len(p["bits"]) for p in ports.values()), pitch_um=a.pitch)
        print(f"{m:16s} {w:8.1f} x {h:8.1f} um  {area * 1e-6:.5f} mm^2  {summary[m]['n_pin_bits']} pin bits")
    (out / "macros.json").write_text(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
