#!/usr/bin/env python3
"""Chip energy / area of the FULL design at every operating point that has a detail-routed layout (S1 c): digital from the layout's gate-level window powers, crossbar from the sweep
(`operating_point_sweep_report.json`, comparators before / after S2), die from the floorplan, timing and residual DRC from the routed run.
  python opt/sweep_chip.py 541.8=f_full 1500=s_1500b 3000=s_3000 5000=s_5000"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import final as F  # noqa: E402
import final2 as F2  # noqa: E402

SYNTH = HERE.parent
REPO = SYNTH.parents[2]
sw = json.loads((REPO / "studies/crossbar/results/macro_512x32/operating_point_sweep_report.json").read_text())
rg = F2.regress("ab_full_g4", "hdc_final2")
rows = []
for kv in sys.argv[1:]:
    ron, tag = kv.split("=")
    r = next(x for x in sw["rows"] if abs(x["ron"] - float(ron)) < 1e-6)
    run = SYNTH / "work/opt" / tag
    pw = json.loads((run / "power_routed.json").read_text())
    P = {w: pw["power"][w]["fast"]["total_w"] for w in ("ing", "mvm")}
    n_ing, n_rest = rg["events"], rg["cycles"] - rg["events"]
    dig = (P["ing"] * n_ing + P["mvm"] * n_rest) / F.F * 1e6
    xa, xb = r["energy_uJ"]["total_after"], r["energy_uJ"]["total_before"]
    fp = F.fp(tag)
    t = F.timing(tag)
    drc = sum(1 for ln in (run / "reports/drc_route.rpt").read_text().splitlines() if ln.startswith("violation type")) if (run / "reports/drc_route.rpt").exists() else None
    rows.append(dict(ron=float(ron), tag=tag, w_F=r["w_F"], macro_mm2=r["area_mm2"]["macro_160_s2"], die_mm2=fp["DIE_W"] * fp["DIE_H"] * 1e-6, P_ing_mW=P["ing"] * 1e3, P_scan_mW=P["mvm"] * 1e3, digital_uJ=dig, crossbar_after_uJ=xa, crossbar_before_uJ=xb,
                     total_after_uJ=dig + xa + 0.0036, total_before_uJ=dig + xb + 0.0036, slow=t["slow"], fast=t["fast"], drc=drc, cycles_per_pass=r["cycles_per_pass"], sigma_lnG_limit=r["sigma_lnG_limit"]))
(SYNTH / "work/opt/sweep_chip.json").write_text(json.dumps(rows, indent=1))
print("| LRS | cell | macro mm2 | die mm2 | ingest / scan mW | digital uJ | crossbar uJ (before / after S2) | total uJ (before / after S2) | slow setup / hold | fast setup / hold | residual DRC | sigma_lnG limit |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for x in rows:
    print(f"| {x['ron']:g} | {x['w_F']:.1f} F | {x['macro_mm2']:.3f} | {x['die_mm2']:.3f} | {x['P_ing_mW']:.3f} / {x['P_scan_mW']:.2f} | {x['digital_uJ']:.2f} | {x['crossbar_before_uJ']:.2f} / {x['crossbar_after_uJ']:.2f} | {x['total_before_uJ']:.2f} / {x['total_after_uJ']:.2f} | "
          f"{x['slow']['setup_wns']:+.3f} / {x['slow']['hold_wns']:+.3f} | {x['fast']['setup_wns']:+.3f} / {x['fast']['hold_wns']:+.3f} | {x['drc']} | {x['sigma_lnG_limit']:.2f} |")
