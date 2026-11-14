#!/usr/bin/env python3
"""Chip energy / power / area of the four builds at the CHOSEN operating point (second optimisation pass; reports/operating_point.md).

  digital   the detail-routed layout's gate-level window powers (opt/power.py, fast library, slow next to it) x the RTL regression's cycles and events (3 seeds x 240 samples), as opt/final.py
  crossbar  studies/crossbar `operating_point_sweep_report.json` at the chosen LRS (select transistor, front-end, comparators re-costed in S2), per non-zero group read x that build's reads
  level shifters / class-HV arrays   as opt/final.py
  area      die of the layout
  python opt/final2.py --ron 5000 --tags full=s_5000 ee_off=e5k_ee fact_off=e5k_fa both_off=e5k_bo [--results hdc_final2]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(HERE))
import final as F  # noqa: E402

PREFIX = {"full": "ab_full_g4", "ee_off": "ab_eeoff_g4", "fact_off": "ab_factoff_g4", "both_off": "ab_bothoff_g4"}
P5 = {"full": "full_g4", "ee_off": "ee_off_g4", "fact_off": "fact_off_g4", "both_off": "both_off_g4"}


def regress(prefix: str, results: str) -> dict:
    cyc, ev, rd, ext, acc = [], [], [], [], []
    mism = 0
    for s in (0, 1, 2):
        d = json.loads((ROOT / "results" / results / f"{prefix}_s{s}.json").read_text())
        for r in d["samples"]:
            cyc.append(r["cycles_inf"]); ev.append(r["events_ingested"]); rd.append(r["group_reads_allcols"]); ext.append(r["exit_tstep"] + 1); acc.append(1.0 if r["correct"] else 0.0)
        mism += d["summary"]["mismatching_samples"]
    m = lambda x: sum(x) / len(x)  # noqa: E731
    return dict(samples=len(cyc), mismatching=mism, cycles=m(cyc), events=m(ev), nz_reads=m(rd), exit_ts=m(ext), accuracy=m(acc))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ron", type=float, required=True)
    ap.add_argument("--tags", nargs="+", required=True)
    ap.add_argument("--results", default="hdc_final2")
    ap.add_argument("--out", default="final2_summary.json")
    ap.add_argument("--comparators", choices=["after", "before"], default="after")
    a = ap.parse_args()
    ph5 = json.loads((ROOT / "results/ppa/phase5_tables.json").read_text())
    sweep = json.loads((REPO / "studies/crossbar/results/macro_512x32/operating_point_sweep_report.json").read_text())
    row = next(r for r in sweep["rows"] if abs(r["ron"] - a.ron) < 1e-6)
    e = row["energy_uJ"]
    xb_per_read = (e["total_after"] if a.comparators == "after" else e["total_before"]) / sweep["reads"]
    res = {}
    for kv in a.tags:
        name, tag = kv.split("=")
        run = SYNTH / "work/opt" / tag
        pw = json.loads((run / "power_routed.json").read_text())
        rg = regress(PREFIX[name], a.results)
        P = {w: {l: pw["power"][w][l]["total_w"] for l in ("fast", "slow")} for w in ("ing", "mvm")}
        n_ing, n_rest = rg["events"], rg["cycles"] - rg["events"]
        dig = {l: (P["ing"][l] * n_ing + P["mvm"][l] * n_rest) / F.F * 1e6 for l in ("fast", "slow")}
        split = dict(ingest_uJ=P["ing"]["fast"] * n_ing / F.F * 1e6, scan_uJ=P["mvm"]["fast"] * n_rest / F.F * 1e6)
        tog = {w: sum(pw["power"][w]["boundary"]["toggles"].values()) / pw["windows"][w]["length"] for w in ("ing", "mvm")}
        ls = (tog["ing"] * n_ing + tog["mvm"] * n_rest) * F.C_LS * F.V * F.V * 1e6
        xb = xb_per_read * rg["nz_reads"]
        hv = ph5["builds"][P5[name]]["energy_uJ"]["hdc_array"]
        f_ = F.fp(tag)
        lat_ms = rg["cycles"] / F.F * 1e3
        tot = dig["fast"] + xb + ls + hv
        t = F.timing(tag)
        ann = {w: pw["power"][w]["fast"]["annotation"] for w in ("ing", "mvm")}
        res[name] = dict(tag=tag, regress=rg, windows=pw["windows"], power_w=P, annotation=ann, golden=dict(ing=pw["power"]["ing"]["gate_level_matches_golden"], mvm=pw["power"]["mvm"]["gate_level_matches_golden"]),
                         digital_uJ=dig, digital_split=split, crossbar_uJ=xb, level_shifter_uJ=ls, hdc_array_uJ=hv, energy_uJ=tot, latency_ms=lat_ms, avg_power_mW=tot / lat_ms,
                         die=dict(w=f_["DIE_W"], h=f_["DIE_H"], mm2=f_["DIE_W"] * f_["DIE_H"] * 1e-6), timing=t)
    Path(SYNTH / "work/opt" / a.out).write_text(json.dumps(res, indent=1, default=str))
    print("| build | accuracy | exit t | cycles | latency ms | digital uJ (fast / slow) | crossbar uJ | other | **energy uJ** | avg power mW | die mm2 | slow setup / hold | fast setup / hold |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, r in res.items():
        g, t = r["regress"], r["timing"]
        print(f"| {n} | {100 * g['accuracy']:.2f}% | {g['exit_ts']:.1f} | {g['cycles']:,.0f} | {r['latency_ms']:.2f} | {r['digital_uJ']['fast']:.2f} / {r['digital_uJ']['slow']:.2f} | {r['crossbar_uJ']:.2f} | {r['level_shifter_uJ'] + r['hdc_array_uJ']:.4f} | "
              f"**{r['energy_uJ']:.2f}** | {r['avg_power_mW']:.2f} | {r['die']['mm2']:.3f} | {t['slow']['setup_wns']:+.3f} / {t['slow']['hold_wns']:+.3f} | {t['fast']['setup_wns']:+.3f} / {t['fast']['hold_wns']:+.3f} |")


if __name__ == "__main__":
    main()
