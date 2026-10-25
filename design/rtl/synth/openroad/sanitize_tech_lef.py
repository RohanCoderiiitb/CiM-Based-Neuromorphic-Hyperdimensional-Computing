#!/usr/bin/env python3
"""The PDK's tech LEF has six device-level VIARULE GENERATE blocks (M1_PO, M1_DIFF, M1_PSUB, M1_NWELL, M1_NIMP, M1_PIMP) on the non-routing layers Poly / Oxide; OpenROAD's detailed router (TritonRoute) refuses them
('DRT-0129 Unknown layer Oxide for viarule M1_DIFF'). They are contact rules for the cell layouts, not used for routing. This writes a copy without them (everything else byte for byte):
synth/work/tech_openroad.lef.   The PDK file is not modified."""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
src = SYNTH.parents[2] / "45_nm_PDK" / "cadence" / "cadence_45nm" / "lef" / "gsclib045_tech.lef"
t = src.read_text()
n = 0
DEV = ("M1_PO", "M1_DIFF", "M1_PSUB", "M1_NWELL", "M1_NIMP", "M1_PIMP")          # every device-layer contact rule (Poly / Oxide / Nwell / implant layers)
for name in DEV:
    t, k = re.subn(rf"VIARULE {name} GENERATE\n.*?END {name}\n", "", t, flags=re.S)
    n += k
for name in DEV:                                  # and the NONDEFAULTRULE lines that use them
    t = re.sub(rf"^\s*USEVIARULE {name} ;\n", "", t, flags=re.M)
out = SYNTH / "work" / "tech_openroad.lef"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(t)
print(f"removed {n} VIARULE blocks -> {out}")
