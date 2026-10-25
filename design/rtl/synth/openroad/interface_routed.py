#!/usr/bin/env python3
"""D3 with the ROUTED / placed wires: the energy of the nets that cross the analog/digital boundary (the macro's pins), from
  - the wire capacitance OpenROAD estimates for each of those nets (set_wire_rc from the PDK LEF, estimate_parasitics on the stage's database), and
  - the transitions of the same nets in the gate-level VCD (m_o count outputs, rd_bitrow_i row selects), per read.
It replaces interface_model.py's assumed 300/500/700 um wires by the real lengths, and it is the part of the routed digital power that final_ppa.py must NOT count twice: the macro's behavioural
model drives these nets in the gate-level simulation, so their switching is already inside the routed 'combinational switching' power. Level-shifter energy is still the assumption of interface_model.py.

  python interface_routed.py --stage post_cts|routed --build full
Writes synth/results/interface_routed_<stage>.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
sys.path.insert(0, str(SYNTH))
sys.path.insert(0, str(HERE))
import analyze_openroad as AO  # noqa: E402
import interface_model as IM  # noqa: E402

PDK = AO.PDK
VDD = 1.1


def net_caps(stage: str, build: str, work: Path) -> dict[str, float]:
    """wire capacitance (fF) of every net on a pin of the analog macros, by 'pin' name (e.g. m_o[12], rd_bitrow_i[3])"""
    outd = SYNTH / "results" / "openroad" / build
    macro_dir = SYNTH / "work" / build
    tcl = AO.prelude(build, stage, PDK / "lib" / "fast_vdd1v0_basicCells.lib", macro_dir, outd) + """
set block [ord::get_db_block]
set fh [open %s/macro_net_caps.txt w]
foreach inst [$block getInsts] {
  set mn [[$inst getMaster] getName]
  if {$mn ne "cim_macro"} continue
  foreach it [$inst getITerms] {
    set net [$it getNet]
    if {$net eq "NULL"} continue
    if {[$net getSigType] ne "SIGNAL"} continue
    set nn [$net getName]
    sta::redirect_string_begin
    report_net -digits 6 $nn
    set s [sta::redirect_string_end]
    if {[regexp {Wire capacitance: ([0-9.eE+-]+)} $s -> r]} { puts $fh "[[$it getMTerm] getName] $nn $r" }
  }
}
close $fh
exit
""" % work
    AO.or_run(work, "netcaps", tcl)
    caps = {}
    for line in (work / "macro_net_caps.txt").read_text().splitlines():
        pin, net, c = line.rsplit(None, 2)
        caps[pin] = float(re.match(r"[0-9.eE+]+", c).group(0))
    return caps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="routed", choices=["post_cts", "groute", "routed"])
    ap.add_argument("--build", default="full")
    a = ap.parse_args()
    work = SYNTH / "results" / "layout" / a.build / a.stage / "interface"
    work.mkdir(parents=True, exist_ok=True)
    caps = net_caps(a.stage, a.build, work)                                    # pF -> in OpenSTA units: capacitance printed in pF (library unit)
    act = json.loads((SYNTH / "results" / "interface.json").read_text())
    reads = act["reads_in_window"]
    # per-bit toggles come from the same VCD analysis as interface_model.py
    vcd = next((ROOT / "results" / "ppa_digital" / "full" / "power_vcd").glob("*.vcd"))
    va = IM.vcd_activity(vcd)
    mo, rb = va["m_o_bit_toggles"], va["rd_bitrow_bit_toggles"]
    e_out = e_in = 0.0
    c_out = c_in = 0.0
    n_out = n_in = 0
    for j in range(160):
        for b in range(IM.BITS_PER_COL):
            k = j * 10 + b
            c = caps.get(f"m_o[{k}]")
            if c is None:
                continue
            n_out += 1
            c_out += c
            e_out += 0.5 * c * 1e-12 * VDD ** 2 * mo[k]                       # 0.5 C V^2 per transition (J)
    for k in range(512):
        c = caps.get(f"rd_bitrow_i[{k}]")
        if c is None:
            continue
        n_in += 1
        c_in += c
        e_in += 0.5 * c * 1e-12 * VDD ** 2 * rb[k]
    out = dict(stage=a.stage, build=a.build, reads_in_window=reads, nets_counted=dict(outputs=n_out, row_select=n_in),
               mean_wire_cap_fF=dict(outputs=1e3 * c_out / max(n_out, 1), row_select=1e3 * c_in / max(n_in, 1)),
               energy_pJ_per_read=dict(wires_outputs=e_out * 1e12 / reads, wires_row_select=e_in * 1e12 / reads, wires_total=(e_out + e_in) * 1e12 / reads),
               note="wire energy only (0.5 C V^2 per transition, OpenROAD-estimated wire C, VCD transitions); pin capacitance of the digital loads and the level shifters are not included here")
    (SYNTH / "results" / f"interface_routed_{a.stage}.json").write_text(json.dumps(out, indent=1))
    print(f"[{a.build}/{a.stage}] boundary nets: {n_out} outputs, {n_in} row selects; mean wire C {out['mean_wire_cap_fF']['outputs']:.0f} / {out['mean_wire_cap_fF']['row_select']:.0f} fF; "
          f"{out['energy_pJ_per_read']['wires_total']:.2f} pJ per read (assumed-length model: {act['energy']['nominal']['energy_pJ_per_read']:.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
