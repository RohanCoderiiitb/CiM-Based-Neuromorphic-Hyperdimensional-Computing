#!/usr/bin/env python3
"""D3: the analog/digital interface, which every number so far counted as zero. Writes synth/results/interface.json.

Activity is MEASURED: the gate-level VCD of the final netlist (a read-phase window of a real DVS-Gesture sample, `synth_power.py --keep-vcd --tag _vcd`) gives, per read (cycle with m_valid_o),
  - the toggles of the count outputs m_o (160 columns x W_MATCH bits; only the LOW bits can be non-zero in the g = 4 chip: counts 0..4 -> 3 bits per column = 480 physical wires; the
    behavioural model of the g = 8 netlist emits up to 8 -> its 4th bit is ignored here, which slightly OVERstates the toggling of a g = 4 array),
  - the toggles of the row-select vector rd_bitrow_i (512 wires; changes once per count bit-row, not once per read).
Wire capacitance comes from the PDK's tech LEF (Metal4 / Metal6: CPERSQDIST x width + 2 x EDGECAPACITANCE per um), lengths from the macro/digital-core dimensions (analog_macros.py), the
supply is the digital 1.1 V (the wires sit in the digital domain on both sides of the level shifters).
LEVEL SHIFTERS: the PDK ships LSHL (high->low) and LSLH (low->high) cells in the LEF but NO Liberty for them, so their area is the LEF size and their energy is an ASSUMPTION
([ASSUM]: 4 fF of switched internal capacitance per transition, E = C V^2); synthesis/STA cannot see them, they are inserted at the macro boundary by the owner's floorplan script.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RES = HERE / "results"
PDK = ROOT.parents[1] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lef"
VDD = 1.1
G = 4
BITS_PER_COL = 3                   # ceil(log2(g + 1)) at g = 4
COLS = 160
LS_FJ_PER_TOGGLE = 4.0e-15 * VDD ** 2 * 1e15      # [ASSUM] 4 fF x V^2, in fJ


def lef_cap_ff_per_um(layer: str) -> float:
    t = (PDK / "gsclib045_tech.lef").read_text()
    m = re.search(rf"LAYER {layer}\n(.*?)\nEND {layer}", t, re.S).group(1)
    width = float(re.search(r"^\s*WIDTH ([\d.]+) ;", m, re.M).group(1))
    cps = float(re.search(r"CAPACITANCE CPERSQDIST ([\d.eE+-]+)", m).group(1))
    edge = float(re.search(r"EDGECAPACITANCE ([\d.eE+-]+)", m).group(1))
    return (cps * width + 2 * edge) * 1e3          # pF/um -> fF/um


def lef_size(cell: str) -> float:
    t = (PDK / "gsclib045_macro.lef").read_text()
    m = re.search(rf"MACRO {cell}\n.*?SIZE ([\d.]+) BY ([\d.]+) ;", t, re.S)
    return float(m.group(1)) * float(m.group(2))


def vcd_activity(vcd: Path) -> dict:
    want = {"m_o": 1600, "rd_bitrow_i": 512, "m_valid_o": 1, "clk_i": 1}
    ids: dict[str, str] = {}
    in_defs = True
    last: dict[str, int | None] = {}
    tog = {k: [0] * w for k, w in want.items()}
    reads = 0
    t_prev_valid = 0
    cycles_with_edge = 0
    with open(vcd, errors="replace") as fh:
        for line in fh:
            if in_defs:
                if line.startswith("$var"):
                    f = line.split()
                    nm = f[4].lstrip("\\")
                    if nm in want and int(f[2]) == want[nm] and nm not in ids.values():
                        ids[f[3]] = nm
                elif line.startswith("$enddefinitions"):
                    in_defs = False
                continue
            c = line[0]
            if c in "bB":
                val, vid = line[1:].split()
                nm = ids.get(vid)
                if nm is None or any(ch in "xXzZ" for ch in val):
                    if nm:
                        last[nm] = None
                    continue
                v = int(val, 2)
                old = last.get(nm)
                if old is not None:
                    d = old ^ v
                    i = 0
                    while d:
                        if d & 1:
                            tog[nm][i] += 1
                        d >>= 1
                        i += 1
                last[nm] = v
            elif c in "01":
                nm = ids.get(line[1:].strip())
                if nm == "m_valid_o":
                    last[nm] = int(c)
                elif nm == "clk_i":
                    if c == "1" and last.get("clk_i") == 0:
                        cycles_with_edge += 1
                        if last.get("m_valid_o") == 1:
                            reads += 1                       # a read is a clock edge at which the macro's valid is high (it stays high across back-to-back reads)
                    last["clk_i"] = int(c)
    return dict(clock_edges=cycles_with_edge, reads=reads, m_o_bit_toggles=tog["m_o"], rd_bitrow_bit_toggles=tog["rd_bitrow_i"], m_valid_found="m_valid_o" in ids.values())


def main() -> int:
    vcd = next((ROOT / "results" / "ppa_digital" / "full" / "power_vcd").glob("*.vcd"))
    act = vcd_activity(vcd)
    cyc = json.loads((ROOT / "results" / "ppa_digital" / "full" / "power_vcd" / "power_summary.json").read_text())["window_cycles"]
    reads = max(act["reads"], 1)
    mo = act["m_o_bit_toggles"]
    low = sum(mo[j * 10 + b] for j in range(COLS) for b in range(BITS_PER_COL))
    row_tog = sum(act["rd_bitrow_bit_toggles"])
    alpha_out = low / (COLS * BITS_PER_COL * reads)             # toggles per output wire per read
    alpha_in = row_tog / (512 * reads)                           # toggles per row-select wire per read
    macro = json.loads((RES / "analog_macros.json").read_text())["cim_macro"]
    digital_um2 = json.loads((ROOT / "results" / "ppa_digital" / "full" / "summary.json").read_text())["buf_fast"]["area_um2"]
    util = 0.70                                                  # [ASSUM] standard-cell utilisation, to be replaced by the Innovus number
    core_side = (digital_um2 / util) ** 0.5
    edge = macro["width_um"]
    results = {}
    for tag, L in (("short", 300.0), ("nominal", 500.0), ("long", 700.0)):
        c4, c6 = lef_cap_ff_per_um("Metal4"), lef_cap_ff_per_um("Metal6")
        c_wire = L * (c4 + c6) / 2 + 4.0                         # + pin capacitance on the two ends (~2 fF each)
        e_out = alpha_out * COLS * BITS_PER_COL * (c_wire * VDD ** 2 + LS_FJ_PER_TOGGLE)           # fJ per read
        e_in = alpha_in * 512 * (c_wire * VDD ** 2 + LS_FJ_PER_TOGGLE)
        results[tag] = dict(length_um=L, wire_cap_fF=c_wire, energy_out_fJ_per_read=e_out, energy_in_fJ_per_read=e_in, energy_pJ_per_read=(e_out + e_in) * 1e-3)
    n_ls_lh, n_ls_hl = COLS * BITS_PER_COL, 512 + 8 + 7 + 3 + 9 + 32 + 4                         # outputs up-shifted; row select + plane mask + group + write port down-shifted
    ls_area = n_ls_lh * lef_size("LSLHX1_TO") + n_ls_hl * lef_size("LSHLX1_FROM")
    out = dict(vcd=str(vcd), window_cycles=cyc, reads_in_window=act["reads"], clock_edges_in_window=act["clock_edges"], alpha_output_toggles_per_wire_per_read=alpha_out, alpha_rowselect_toggles_per_wire_per_read=alpha_in,
               wires=dict(outputs=COLS * BITS_PER_COL, row_select=512, other_inputs=n_ls_hl - 512, total=COLS * BITS_PER_COL + n_ls_hl), wire_cap_fF_per_um=dict(Metal4=lef_cap_ff_per_um("Metal4"), Metal6=lef_cap_ff_per_um("Metal6")),
               level_shifters=dict(low_to_high=n_ls_lh, high_to_low=n_ls_hl, area_um2=ls_area, area_mm2=ls_area * 1e-6, energy_fJ_per_toggle_ASSUMED=LS_FJ_PER_TOGGLE,
                                   lef_sizes_um2=dict(LSLHX1_TO=lef_size("LSLHX1_TO"), LSHLX1_FROM=lef_size("LSHLX1_FROM"))),
               geometry=dict(macro_um=[macro["width_um"], macro["height_um"]], digital_core_side_um_at_util=core_side, util_assumed=util, edge_pin_span_um=edge), energy=results,
               note="g = 8 netlist activity applied to the g = 4 chip; level-shifter energy is an assumption; wire length is a floorplan assumption (300/500/700 um) until Innovus reports the real routes")
    (RES / "interface.json").write_text(json.dumps(out, indent=1))
    n = results["nominal"]
    print(f"reads in window {act['reads']}; alpha_out {alpha_out:.3f}/wire/read, alpha_rowsel {alpha_in:.4f}; nominal {n['energy_pJ_per_read']:.2f} pJ/read "
          f"(range {results['short']['energy_pJ_per_read']:.2f}-{results['long']['energy_pJ_per_read']:.2f}); LS area {ls_area:,.0f} um^2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
