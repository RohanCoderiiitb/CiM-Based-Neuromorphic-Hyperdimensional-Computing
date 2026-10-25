#!/usr/bin/env python3
"""Digital energy pass: Phase 5's energy per inference, recomputed with the clock-gated digital design. Everything that is not the digital power is Phase 5's model, unchanged and imported from
phase5_ppa.py (crossbar read energy per non-zero read from 1F, class-HV arrays, the cycle model, the cycles / reads / exit timesteps measured on the RTL regression); only the digital power
(window average, gate-level activity, OpenSTA - the same window and sample as Phase 5) comes from the new netlists. Writes <ppa dir>/digital_tables.json.

  python design/rtl/scripts/digital_energy.py [--ppa ppa_digital] [--phase5 ppa]

Also computed here, because gating makes a single window average a weaker proxy than it was when every cycle cost the same:
  * a phase-resolved digital energy (event-ingest cycles x the power of an ingest-only window + all other cycles x the power of a read-phase window), when those windows exist;
  * the a = 0 read skip, bounded: the saving cannot exceed (empty reads x the energy of an average read-phase cycle) and cannot be below zero.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import phase5_ppa as P5  # noqa: E402

BUILDS = list(P5.BUILDS)


def load(ppa: Path) -> tuple[dict, dict, dict]:
    synth = {b: json.loads((ppa / b / "summary.json").read_text()) for b in BUILDS}
    power_full = {b: json.loads((ppa / b / "power" / "power_summary.json").read_text()) for b in BUILDS}
    power = {b: power_full[b]["total_w"] * 1e3 for b in BUILDS}
    return synth, power_full, power


def phase_energy(build: str, g: int, ppa: Path, nb: dict) -> dict | None:
    """Digital energy with two phase powers: P_ingest (an ingest-only window) for the cycles in which an event is accepted, P_other (a window inside the read phase) for every other cycle
    (drain, crossbar reads, update, query hold). Cycle counts per inference: Phase 5's, from the RTL logs (events ingested = accepted-event cycles)."""
    fi, fm = ppa / build / "power_ing" / "power_summary.json", ppa / build / "power_mvm" / "power_summary.json"
    if not (fi.exists() and fm.exists()):
        return None
    pi, pm = json.loads(fi.read_text()), json.loads(fm.read_text())
    t = P5.T_CYCLE_NS * 1e-9
    n_ev = nb["mean_events_ingested"]
    n_all = nb["mean_cycles"]
    e = pi["total_w"] * n_ev * t + pm["total_w"] * (n_all - n_ev) * t
    return dict(P_ingest_mW=pi["total_w"] * 1e3, P_other_mW=pm["total_w"] * 1e3, event_cycles=n_ev, other_cycles=n_all - n_ev, digital_uJ=e * 1e6,
                window_ingest=dict(start=pi["window_start"], cycles=pi["window_cycles"]), window_other=dict(start=pm["window_start"], cycles=pm["window_cycles"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ppa", default="ppa_digital", help="results directory of the gated flow (under design/rtl/results)")
    ap.add_argument("--phase5", default="ppa", help="results directory of Phase 5 (the ungated numbers)")
    a = ap.parse_args()
    ppa, ppa5 = ROOT / "results" / a.ppa, ROOT / "results" / a.phase5
    synth, power_full, power = load(ppa)
    t5 = json.loads((ppa5 / "phase5_tables.json").read_text())
    res: dict = {"phase5_reference": {k: t5[k] for k in ("neurohdc_small", "digital_power_mW")}, "digital_power_mW": power, "builds": {}}
    for g in (4, 8):
        for b in BUILDS:
            nb = P5.build_numbers(b, g, power, synth, power_full)
            for k in ("flop_activity_alpha", "digital_power_gated_bound_mW"):         # Phase 5's ideal-gating BOUND: meaningless for a netlist that is already gated
                nb.pop(k, None)
            nb["scenarios_total_uJ"].pop("clock_gated_bound", None)
            nb["scenarios_total_uJ"].pop("a0_skip_and_clock_gated_bound", None)
            nb["digital_uJ_scenarios"].pop("clock_gated_bound", None)
            nb["digital_uJ_scenarios"].pop("a0_skip_and_clock_gated_bound", None)
            hd = t5["builds"][f"{b}_g{g}"]
            hd_area = hd["area_mm2"]["hdc_array"]
            nb["area_mm2"] = dict(digital=nb["area_digital_mm2"], snn_array_1nF=hd["area_mm2"]["snn_array_1nF"], hdc_array=hd_area, total=nb["area_digital_mm2"] + hd["area_mm2"]["snn_array_1nF"] + hd_area)
            nb["phase5"] = dict(energy_uJ=hd["energy_uJ"], scenarios_total_uJ=hd["scenarios_total_uJ"], digital_power_mW=hd["digital_power_mW"], area_mm2=hd["area_mm2"], mean_cycles=hd["mean_cycles"])
            ph = phase_energy(b, g, ppa, nb)
            if ph:
                nb["phase_resolved"] = ph
            # the a = 0 skip, bounded. Upper bound: every removed read cycle costs as much as an average non-event cycle of the gated design. Lower bound: zero (the gated empty read already
            # clocks almost nothing). The analog side draws nothing for an empty read in Phase 5's model, so only the digital term is at stake.
            saved_cycles = nb["mean_cycles"] - nb["mean_cycles_a0_skip"]
            p_other = (ph or {}).get("P_other_mW", power[b]) * 1e-3
            nb["a0_skip_digital_saving_uJ"] = dict(upper_bound=saved_cycles * P5.T_CYCLE_NS * 1e-9 * p_other * 1e6, lower_bound=0.0, cycles_removed=saved_cycles,
                                                   window_average_model_uJ=nb["energy_uJ"]["digital"] - nb["digital_uJ_scenarios"]["a0_skip"])
            res["builds"][f"{b}_g{g}"] = nb
    (ppa / "digital_tables.json").write_text(json.dumps(res, indent=1, default=float))
    for k, v in res["builds"].items():
        if k.endswith("g4"):
            pr = v.get("phase_resolved")
            print(f"{k:12s} acc {v['accuracy_mean'] * 100:5.2f}%  exit t {v['mean_exit_timestep']:6.2f}  E {v['energy_uJ']['total']:.3f} uJ (snn {v['energy_uJ']['snn_array']:.3f}, dig {v['energy_uJ']['digital']:.3f}, "
                  f"hdc {v['energy_uJ']['hdc_array']:.4f})  [Phase 5: {v['phase5']['energy_uJ']['total']:.3f}]  P {v['digital_power_mW']:.3f} mW  area {v['area_mm2']['total']:.3f} mm2"
                  + (f"  phase-resolved dig {pr['digital_uJ']:.3f} uJ" if pr else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
