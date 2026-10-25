#!/usr/bin/env python3
"""Energy / power / area of the four optimised builds from the detail-routed layouts (reports/optimised_ppa.md).

  digital   window power of the gate-level activity of the routed netlist (opt/power.py; FAST library, as every earlier number, slow next to it)
            E = P_ing x (events ingested) / f + P_mvm x (cycles - events ingested) / f      (phase-resolved; cycles and events are the RTL regression's means over 720 samples)
  crossbar  sense/energy_opt.py chain (items 7, 8, 9) at the RTL's mean non-zero group reads per inference
  interface level shifters, [ASSUM] 4 fF x V^2 per toggle of the macro-boundary nets (the wires themselves are in the routed netlist's power)
  class-HV arrays   Phase 5 model (results/ppa/phase5_tables.json), unchanged
  area      die area of the floorplan (no pads) and its parts

  python opt/final.py        -> work/opt/final_summary.json and markdown on stdout"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYNTH = HERE.parent
ROOT = SYNTH.parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO / "studies" / "crossbar"))
from sense import energy_opt as EO  # noqa: E402

F = 100e6
V = 1.1
C_LS = 4e-15
NEURO = dict(energy_uJ=3.01, area_mm2=0.399)
BUILDS = {"full": ("f_full", "full_g4", "ab_full_g4"), "ee_off": ("f_ee_off", "ee_off_g4", "ab_eeoff_g4"),
          "fact_off": ("f_fact_off", "fact_off_g4", "ab_factoff_g4"), "both_off": ("f_both_off", "both_off_g4", "ab_bothoff_g4")}


def fp(tag: str) -> dict:
    d = {}
    for ln in (SYNTH / "work/opt" / tag / "fp.tcl").read_text().splitlines():
        p = ln.split()
        if len(p) == 3 and p[0] == "set":
            d[p[1]] = float(p[2]) if p[2].replace(".", "").isdigit() else p[2]
    return d


def timing(tag: str, stage: str = "routed") -> dict:
    out = {}
    for ln in (SYNTH / "work/opt" / tag / "reports" / f"summary_{stage}.txt").read_text().splitlines():
        if ln.startswith("SCENE"):
            p = ln.split()
            out[p[1]] = dict(setup_wns=float(p[3]), hold_wns=float(p[5]), setup_tns=float(p[7]), hold_tns=float(p[9]))
    return out


def regress(prefix: str) -> dict:
    sm, cyc, ev, rd, ext, acc, n = [], [], [], [], [], [], 0
    for s in (0, 1, 2):
        d = json.loads((ROOT / "results/hdc_final" / f"{prefix}_s{s}.json").read_text())
        for r in d["samples"]:
            cyc.append(r["cycles_inf"]); ev.append(r["events_ingested"]); rd.append(r["group_reads_allcols"]); ext.append(r["exit_tstep"] + 1); acc.append(r["correct"])
        sm.append(d["summary"]["mismatching_samples"])
        n += d["summary"]["samples"]
    m = lambda x: sum(x) / len(x)  # noqa: E731
    return dict(samples=n, mismatching=sum(sm), cycles=m(cyc), events=m(ev), nz_reads=m(rd), exit_ts=m(ext), accuracy=m([1.0 if a else 0.0 for a in acc]))


def main() -> None:
    ph5 = json.loads((ROOT / "results/ppa/phase5_tables.json").read_text())
    res = {}
    for name, (tag, p5, ab) in BUILDS.items():
        run = SYNTH / "work/opt" / tag
        pj = run / "power_routed.json"
        if not pj.exists():
            continue
        pw = json.loads(pj.read_text())
        rg = regress(ab)
        P = {w: {l: pw["power"][w][l]["total_w"] for l in ("fast", "slow")} for w in ("ing", "mvm")}
        ann = {w: {l: pw["power"][w][l]["annotation"] for l in ("fast", "slow")} for w in ("ing", "mvm")}
        n_ing, n_rest = rg["events"], rg["cycles"] - rg["events"]
        dig = {l: (P["ing"][l] * n_ing + P["mvm"][l] * n_rest) / F * 1e6 for l in ("fast", "slow")}
        # level shifters: boundary toggles per cycle of each window x cycles
        tog = {w: sum(pw["power"][w]["boundary"]["toggles"].values()) / pw["windows"][w]["length"] for w in ("ing", "mvm")}
        split = dict(ingest_uJ=P['ing']['fast'] * n_ing / F * 1e6, scan_uJ=P['mvm']['fast'] * n_rest / F * 1e6, ingest_cycles=n_ing, scan_cycles=n_rest)
        ls = (tog["ing"] * n_ing + tog["mvm"] * n_rest) * C_LS * V * V * 1e6
        xb = EO.compute(rg["nz_reads"])
        steps = xb["steps"]
        xb1 = steps[-1]["crossbar_total_uJ"]
        xb0 = xb1 - steps[-1]["threshold_uJ"]
        hv = ph5["builds"][p5]["energy_uJ"]["hdc_array"]
        f_ = fp(tag)
        mac = json.loads((run / "macro/macros.json").read_text())
        e1 = dig["fast"] + xb1 + ls + hv
        e0 = dig["fast"] + xb0 + ls + hv
        lat_ms = rg["cycles"] / F * 1e3
        res[name] = dict(tag=tag, regress=rg, windows=pw["windows"], power_w=P, annotation=ann, golden=dict(ing=pw["power"]["ing"]["gate_level_matches_golden"], mvm=pw["power"]["mvm"]["gate_level_matches_golden"]),
                         digital_uJ=dig, digital_split=split, level_shifter_uJ=ls, crossbar_uJ=dict(rank1=xb1, rank0=xb0, baseline_1F=steps[0]["crossbar_total_uJ"], steps=steps), hdc_array_uJ=hv,
                         energy_uJ=dict(rank1=e1, rank0=e0), latency_ms=lat_ms, avg_power_mW=dict(rank1=e1 / lat_ms, rank0=e0 / lat_ms),
                         die=dict(w=f_["DIE_W"], h=f_["DIE_H"], mm2=f_["DIE_W"] * f_["DIE_H"] * 1e-6), macros={k: v["area_um2"] * 1e-6 for k, v in mac.items() if isinstance(v, dict) and "area_um2" in v},
                         timing=timing(tag))
    Path(SYNTH / "work/opt/final_summary.json").write_text(json.dumps(res, indent=1, default=str))
    print("| build | accuracy | exit t | cycles | latency ms | digital uJ (fast / slow lib) | crossbar uJ (rank 1 / rank 0) | level shifters | class HV | **energy uJ (rank 1 / rank 0)** | avg power mW | die mm2 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n, r in res.items():
        g = r["regress"]
        print(f"| {n} | {100 * g['accuracy']:.2f}% | {g['exit_ts']:.1f} | {g['cycles']:,.0f} | {r['latency_ms']:.2f} | {r['digital_uJ']['fast']:.2f} / {r['digital_uJ']['slow']:.2f} | {r['crossbar_uJ']['rank1']:.2f} / {r['crossbar_uJ']['rank0']:.2f} | "
              f"{r['level_shifter_uJ']:.4f} | {r['hdc_array_uJ']:.4f} | **{r['energy_uJ']['rank1']:.2f} / {r['energy_uJ']['rank0']:.2f}** | {r['avg_power_mW']['rank1']:.2f} / {r['avg_power_mW']['rank0']:.2f} | {r['die']['mm2']:.3f} |")


if __name__ == "__main__":
    main()
