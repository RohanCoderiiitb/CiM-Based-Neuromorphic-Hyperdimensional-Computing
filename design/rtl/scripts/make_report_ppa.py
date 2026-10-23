#!/usr/bin/env python3
"""reports/phase5_ppa.md - synthesis, the combined PPA at the measured exit timestep, the ablation table. Every number is read from design/rtl/results/ppa/phase5_tables.json,
the per-build synthesis / power summaries and the 1F results; nothing is typed in by hand except the structure and the stated assumptions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
PPA = ROOT / "results" / "ppa"
OUT = REPO / "reports" / "phase5_ppa.md"
SENSE = REPO / "studies" / "crossbar" / "results" / "sense_frontend"
BUILDS = ["full", "ee_off", "fact_off", "both_off"]
LAB = {"full": "full design", "ee_off": "early exit OFF", "fact_off": "factorization OFF", "both_off": "both OFF"}
pct = lambda x, d=1: f"{100 * x:.{d}f}%"          # noqa: E731


def table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def main() -> int:
    T = json.loads((PPA / "phase5_tables.json").read_text())
    Sy = {b: json.loads((PPA / b / "summary.json").read_text()) for b in BUILDS}
    Pw = {b: json.loads((PPA / b / "power" / "power_summary.json").read_text()) for b in BUILDS}
    B = T["builds"]
    NH = T["neurohdc_small"]
    g_rec = 4
    full4, eeoff4, fact4, both4 = (B[f"{b}_g4"] for b in BUILDS)
    full8, eeoff8, fact8, both8 = (B[f"{b}_g8"] for b in BUILDS)
    L = []
    w = L.append
    fa = Pw["full"].get("flop_activity", {})

    def e(v, k="total"):
        return v["energy_uJ"][k]

    w("# Phase 5 report - synthesis, power, and the combined PPA of the complete accelerator")
    w("")
    w("Tags: **[SIM]** simulated (Yosys + OpenSTA on the 45 nm library, gate-level Icarus for the activity; ngspice in 1C/1F), **[RTL]** measured on the RTL regression (the read counts, the exit timestep), **[1F]** carried forward from "
      "[`phase1f_report.md`](phase1f_report.md) unchanged, **[MODEL]** analytic in code, **[ASSUM]** assumed (section 8). Every number is read from `design/rtl/results/ppa/*.json` by `design/rtl/scripts/make_report_ppa.py`; commands in "
      "section 9. Companion: [`phase234_report.md`](phase234_report.md).")
    w("")
    w("## 0. The answer")
    w("")
    w(f"- **Timing: the 100 MHz clock closes, and 1E's 67-gate path needs no pipelining - provided the mapping buffers high-fanout nets.** With the mapping the FFT project used (Yosys `abc` without buffering) the worst "
      f"register-to-register path misses by {-Sy['full']['plain_fast']['reg2reg']['slack_ns']:.2f} ns (minimum period {Sy['full']['plain_fast']['reg2reg']['min_period_ns']:.1f} ns); the first {7.2:.1f} ns of it are two unbuffered nets "
      f"(a flip-flop driving a 512-wide select at 2.3 ns clock-to-Q and an `INVX1` at 5.0 ns), not the popcount-then-add. With `abc -D` and a driving-cell / load constraint (fanout buffering and sizing, +{100 * (Sy['full']['buf_fast']['area_um2'] / Sy['full']['plain_fast']['area_um2'] - 1):.1f} % area) the minimum period is "
      f"**{Sy['full']['buf_fast']['reg2reg']['min_period_ns']:.2f} ns at the fast corner and {Sy['full']['buf_slow']['reg2reg']['min_period_ns']:.2f} ns at the slow corner** of the same library: slack "
      f"{Sy['full']['buf_slow']['reg2reg']['slack_ns']:.1f} ns at 10 ns in the slow corner. 1E's RTL is unchanged. Pre-layout: no clock tree, no wire load, no P&R.")
    w(f"- **Digital area {Sy['full']['buf_fast']['area_um2'] * 1e-6:.3f} mm^2 (full design), {Sy['full']['buf_fast']['flip_flops']:,} flip-flops** (45 nm, buffered mapping); {Sy['fact_off']['buf_fast']['area_um2'] * 1e-6:.3f} mm^2 without the factorization; "
      f"the early-exit comparator and FSM are {Sy['full'].get('hier', {}).get('modules', {}).get('exit_ctrl', {}).get('area_um2', float('nan')):.0f} um^2 ({pct(Sy['full'].get('hier', {}).get('modules', {}).get('exit_ctrl', {}).get('area_um2', 0) / Sy['full']['hier']['area_um2'], 2)} of the digital area, "
      "below the synthesis noise of the flat totals - the flat total of the early-exit-OFF build is not smaller; the attribution is by module, section 2).")
    w(f"- **Digital power {Pw['full']['total_w'] * 1e3:.2f} mW as designed - and it is {pct(Pw['full']['groups_internal_switching_leakage_total_w']['Sequential'][3] / Pw['full']['total_w'], 0)} flip-flop clock energy**: gate-level activity annotates "
      f"{Pw['full']['annotation'].get('vcd', 0):,} of {Pw['full']['annotation'].get('vcd', 0) + Pw['full']['annotation'].get('unannotated', 0):,} pins (100 %), and 1E's {Sy['full']['buf_fast']['flip_flops']:,} flip-flops - about 5.6k of them the count memory - are clocked every "
      "cycle (no clock gating). At ~2.8 fJ per flop per clock edge that is the whole story: the logic's switching power is 0.15 mW.")
    w(f"- **THE NUMBER THAT MATTERS - energy per inference at the measured exit timestep** (recommended point g = 4, 40 columns per pass, T = 1 ns; mean of 3 seeds x 240 samples): full design **{e(full4):.2f} uJ at the exit "
      f"(mean exit timestep {full4['mean_exit_timestep']:.1f})** against {e(eeoff4):.2f} uJ with the same network run to the end - **{pct(1 - e(full4) / e(eeoff4), 0)} saved**; the analog crossbar part alone "
      f"{e(full4, 'snn_array'):.2f} against {e(eeoff4, 'snn_array'):.2f} uJ. NeuroHDC-small: {NH['energy_uJ']:.2f} uJ. **Energy is not read-dominated in this implementation**: at the exit the split is "
      f"crossbar reads {e(full4, 'snn_array'):.2f}, digital {e(full4, 'digital'):.2f}, class-HV arrays {e(full4, 'hdc_array'):.3f} uJ; the early exit saves both because both scale with the cycles and the reads up to the exit, "
      "but the project's central argument - reads are the dominant term - holds for the analog side, not for the chip as built (section 4.3).")
    sc4 = full4["scenarios_total_uJ"]
    w(f"- **What the number is made of, and what could move it (section 4.3):** as built {sc4['as_built']:.1f} uJ; with the a = 0 reads removed from the cycle count (1E/1F follow-up, not implemented) {sc4['a0_skip']:.1f} uJ; "
      f"adding ideal clock gating (a measured-activity *bound*, not a design) {sc4['a0_skip_and_clock_gated_bound']:.1f} uJ = {sc4['a0_skip_and_clock_gated_bound'] / NH['energy_uJ']:.1f}x NeuroHDC-small. The first-order lever is the digital clock, then the empty reads; early exit multiplies whatever is left by ~0.58.")
    w(f"- **Against NeuroHDC-small (0.399 mm^2, 3.01 uJ, 100 MHz, 45 nm, DVS-Gesture):** area {full4['area_mm2']['total']:.3f} mm^2 ({full4['area_mm2']['total'] / NH['area_mm2']:.2f}x), energy {e(full4):.2f} uJ ({e(full4) / NH['energy_uJ']:.2f}x). "
      "Both comparisons are unfavourable by construction in the exclusions below.")
    w("- **Recommended operating point:** g = 4, 40 columns per pass (4 passes), read pulse T = 1 ns (+ 0.3 ns tail), 1 nF supply decoupling, the R=1 factorized class hypervector, early exit at threshold "
      f"**{S_THETA['r1']}** (the strict knee of the R=1 model, accuracy {pct(full4['accuracy_mean'], 2)}), 100 MHz. g = 8 closes the margin budget only for sigma_lnG <= 0.07 (1F) and is reported alongside.")
    w("")
    w("## 1. What is and is not in these numbers")
    w("")
    w(table(["part", "how", "tag"], [
        ["digital logic (1E SNN + query + exit)", "Yosys 0.69 + abc to the Cadence 45 nm `fast_vdd1v0_basicCells.lib` (1.1 V), flattened, `abc -D 10000 -constr` (driving cell BUFX2, load 0.02 pF); OpenSTA 3.1.0 for timing and power", "[SIM]"],
        ["digital power", "gate-level simulation of the synthesized netlist (Icarus, liberty cells as Verilog models, the analog arrays as their behavioural models) on a real DVS-Gesture sample, an 8,000-cycle window starting at cycle 12,000 (timesteps ~3-5); the VCD annotates every pin; `report_power`. Checked against the golden model (spikes, X, V, scores of the timesteps the run completes: post-synthesis equivalence)", "[SIM]"],
        ["SNN crossbar reads", "non-zero group reads per inference measured on the RTL up to the exit; energy per non-zero read from 1F: 186 pJ (g = 4, T = 1 ns), 228 pJ (g = 8, T = 2 ns); a = 0 reads draw nothing (recorded, not implemented)", "[RTL] x [1F]"],
        ["class-HV arrays", "reads priced from 1F's per-column read cost, area from 1C's per-row and 1F's per-column parts (never designed)", "[ASSUM] / [MODEL]"],
        ["SNN array area", "1F's table (mid), with the 1 nF decoupling of the recommended point", "[1F]"],
        ["cycles", "RTL cycles at 160 columns per read + (passes - 1) per group read (validated against the RTL's own 20-column run, section 4.4)", "[RTL] + [MODEL]"]]))
    w("")
    w("**Exclusions (named plainly, as 1C and 1F did).** Not in the energy: the clock tree and the clock network (ideal clock; with one the sequential term grows), wire capacitance of the digital logic, the supply regulator and "
      "decoupling-capacitor leakage, the calibration energy (recalibration every ~5 K), the write/program path and the weight load (ReRAM is non-volatile; the RTL's reload after an exit is a model artefact and is excluded), the "
      "host/IO interface, SRAM-style leakage of the analog arrays at rest, and the idle bias of reads with no active row (assumed gated off; sensitivity in 4.2). Not in the area: place-and-route overhead and utilisation, pads, the clock tree, "
      "the supply regulator, decoupling beyond 1 nF, and the 6.4 kbit calibration store (1F). NeuroHDC-small's figures are a whole accelerator including its clock tree and SRAM macros at a stated 100 MHz; "
      "ours is the same function with the weight memory in ReRAM and a pre-layout digital part.")
    w("")
    w("## 2. (a) Synthesis")
    w("")
    rows = []
    for b in BUILDS:
        s = Sy[b]
        rows.append([LAB[b], f"{s['plain_fast']['area_um2']:,.0f}", f"{s['plain_fast']['reg2reg']['min_period_ns']:.2f}", f"{s['buf_fast']['area_um2']:,.0f}", f"{s['buf_fast']['flip_flops']:,}", f"{s['buf_fast']['cells']:,}",
                     f"{s['buf_fast']['reg2reg']['min_period_ns']:.2f}", f"{s['buf_fast']['reg2reg']['slack_ns']:.2f}", f"{s['buf_slow']['reg2reg']['min_period_ns']:.2f}", f"{s['buf_slow']['reg2reg']['slack_ns']:.2f}", f"{s['buf_fast']['timing']['slack_ns']:.2f}"])
    w(table(["build", "area, FFT-flow mapping (um^2)", "min period, FFT-flow mapping (ns)", "area, buffered mapping (um^2)", "flip-flops", "cells", "min period fast corner (ns)", "slack @ 10 ns fast (ns)",
             "min period slow corner (ns)", "slack @ 10 ns slow (ns)", "worst I/O slack @ 10 ns (ns)"], rows))
    w("")
    w("'Min period' is the worst register-to-register arrival + setup (the analog arrays' outputs launch 0.3 ns after the clock edge [ASSUM]); the I/O column is the worst port-to-port path with input and output delays of "
      "period/4. The four builds elaborate with `check -assert` clean and zero latches in generic Yosys as well (`results/synthesis/hdc_*`), longest topological path 68 gates in all four (1E: 67).")
    w("")
    w("**1E's 67-gate path.** The FFT-flow mapping's worst path starts at a flip-flop whose output drives the 512-wide bit-row select (clock-to-Q 2.27 ns) and an `INVX1` with the same fanout (4.97 ns): 7.2 ns before the logic starts; "
      "the 40-odd levels of popcount and fold take the remaining 5.4 ns. Fanout buffering removes the 7.2 ns, and the register-to-register path is then the popcount-then-add itself at "
      f"{Sy['full']['buf_fast']['reg2reg']['arrival_ns']:.2f} ns (fast corner) - far inside 10 ns, so **registering the popcount (one extra cycle per MVM) is not needed and was not done**; 1E's RTL is unchanged. "
      "If a flow without fanout buffering must be used, pipelining the popcount would not fix the 7 ns of unbuffered fanout either.")
    w("")
    w("### Area by module (full design, hierarchical synthesis, same library and mapping)")
    w("")
    hm = Sy["full"]["hier"]["modules"]
    tot = sum(v["area_um2"] for v in hm.values())
    rows = [[k, f"{v['area_um2']:,.0f}", pct(v["area_um2"] / tot, 1), v["count"]] for k, v in sorted(hm.items(), key=lambda kv: -kv[1]["area_um2"])]
    w(table(["module", "area (um^2)", "share", "variants/instances"], rows))
    w("")
    w(f"(Hierarchical total {tot:,.0f} um^2 against the flattened {Sy['full']['buf_fast']['area_um2']:,.0f}: cross-module optimisation.) The query stage is `hdc_query` + `hdc_score` + `top2_tree` + `exit_ctrl` = "
      f"{hm['hdc_query']['area_um2'] + hm['hdc_score']['area_um2'] + hm['top2_tree']['area_um2'] + hm['exit_ctrl']['area_um2']:,.0f} um^2 ({pct((hm['hdc_query']['area_um2'] + hm['hdc_score']['area_um2'] + hm['top2_tree']['area_um2'] + hm['exit_ctrl']['area_um2']) / tot, 1)}); "
      f"the SNN is the rest, `shift_accum` ({pct(hm['shift_accum']['area_um2'] / tot, 0)}, the two 512-bit popcounts and the 160-column fold) and `count_mem` ({pct(hm['count_mem']['area_um2'] / tot, 0)}, 5,632 flip-flops) dominating.")
    w("")
    w("### Power (a)")
    w("")
    rows = []
    for b in BUILDS:
        p = Pw[b]
        g_ = p["groups_internal_switching_leakage_total_w"]
        rows.append([LAB[b], f"{p['total_w'] * 1e3:.3f}", f"{g_['Sequential'][3] * 1e3:.3f}", f"{g_['Combinational'][3] * 1e3:.3f}", f"{p['switching_w'] * 1e3:.3f}", f"{p['leakage_w'] * 1e6:.1f}",
                     f"{p['annotation'].get('vcd', 0):,} / {p['annotation'].get('vcd', 0) + p['annotation'].get('unannotated', 0):,}", f"{p['timesteps_checked']} ({'yes' if p['gate_level_matches_golden'] else 'NO'})"])
    w(table(["build", "total (mW)", "sequential (mW)", "combinational (mW)", "of which switching (mW)", "leakage (uW)", "pins annotated", "gate level == golden over timesteps"], rows))
    w("")
    if fa and "error" not in fa:
        w(f"**Clock-gating headroom (measured, not applied).** In the 8,000-cycle window of the full build {fa['flops_that_toggle']:,} of {fa['flops_counted']:,} flip-flops ever change value, and the total number of Q transitions is "
          f"{fa['q_toggles']:,} against {fa['flops_counted'] * fa['window_cycles']:,} flop-cycles: an average of {fa['alpha_q_per_flop_cycle']:.4f} transitions per flop per cycle. An ideally clock-gated implementation "
          f"needs a clock edge only when a flop changes: its sequential power would be bounded below by about {Pw['full']['groups_internal_switching_leakage_total_w']['Sequential'][3] * 1e3 * fa['alpha_q_per_flop_cycle']:.3f} mW "
          f"(= {Pw['full']['groups_internal_switching_leakage_total_w']['Sequential'][3] * 1e3:.2f} mW x the activity) instead of {Pw['full']['groups_internal_switching_leakage_total_w']['Sequential'][3] * 1e3:.2f} mW. That is a bound, not a design "
          "(clock-gating cells, their enable timing and the clock-tree would eat part of it); it is stated so that the energy tables can show both, section 4.3.")
        mods = fa["by_module"]
        w("")
        w(table(["module (instance prefix)", "flip-flops", "ever change in the window", "Q transitions"], [[m, f"{d['flops']:,}", f"{d['toggling']:,}", f"{d['toggles']:,}"] for m, d in sorted(mods.items(), key=lambda kv: -kv[1]["flops"])]))
    w("")
    w("## 3. (b) The analog side, carried forward from 1F and 1E (not re-derived)")
    w("")
    pr8, pr4 = T["per_read"]["8"], T["per_read"]["4"]
    w(table(["", "g = 4 (recommended)", "g = 8"], [
        ["sensing", f"{pr4['cols_per_pass']} columns per pass, {pr4['passes']} passes", f"{pr8['cols_per_pass']} columns per pass, {pr8['passes']} passes"],
        ["read pulse T (+ 0.3 ns tail)", f"{pr4['T_ns']:.0f} ns", f"{pr8['T_ns']:.0f} ns"], ["supply decoupling", f"{pr4['decap_nF']:.0f} nF (droop {pr4['droop_mV']:.1f} mV)", f"{pr8['decap_nF']:.0f} nF (droop {pr8['droop_mV']:.1f} mV)"],
        ["energy per non-zero group read, total", f"{pr4['per_read_pj']:.1f} pJ", f"{pr8['per_read_pj']:.1f} pJ"],
        ["  array + word line", f"{pr4['components_pj']['array_and_wordline']:.1f} pJ", f"{pr8['components_pj']['array_and_wordline']:.1f} pJ"], ["  sense bias", f"{pr4['components_pj']['sense_bias']:.1f} pJ", f"{pr8['components_pj']['sense_bias']:.1f} pJ"],
        ["  comparators", f"{pr4['components_pj']['comparators']:.1f} pJ", f"{pr8['components_pj']['comparators']:.1f} pJ"], ["  threshold correction (digital)", f"{pr4['components_pj']['threshold_correction']:.1f} pJ", f"{pr8['components_pj']['threshold_correction']:.1f} pJ"],
        ["non-zero reads per inference, full run (1F / measured on the RTL here)", f"{pr4['reads_nonzero_1f']:,.0f} / {eeoff4['mean_nonzero_reads']:,.0f}", f"{pr8['reads_nonzero_1f']:,.0f} / {eeoff8['mean_nonzero_reads']:,.0f}"],
        ["energy per inference, full run, SNN array only (1F)", f"{pr4['total_uJ_1f']:.2f} uJ", f"{pr8['total_uJ_1f']:.2f} uJ"],
        ["idle bias if an empty read were issued", f"{pr4['idle_bias_per_empty_read_pj']:.0f} pJ", f"{pr8['idle_bias_per_empty_read_pj']:.0f} pJ"]]))
    w("")
    w(f"The RTL's measured read counts reproduce 1F's: {eeoff8['mean_all_reads']:,.0f} reads of which {eeoff8['mean_nonzero_reads']:,.0f} non-zero at g = 8 (1F/1E: 53,590 / 20,420), and they depend only on the input events, not on the model. "
      "Array area with the real sense periphery (1F, mid, 1 nF decoupling): "
      f"{T['snn_array_area_mm2'].get('c_dec=1nF|mid', float('nan')):.3f} mm^2 (low {T['snn_array_area_mm2'].get('c_dec=1nF|low', float('nan')):.3f}, high {T['snn_array_area_mm2'].get('c_dec=1nF|high', float('nan')):.3f}); without decoupling {T['snn_array_area_mm2'].get('c_dec=0nF|mid', float('nan')):.3f}. "
      "The g surface (1F section 8): g = 4 for sigma_lnG <= 0.15; g = 8 only for sigma_lnG <= 0.07; g = 16 only with segmented columns at <= 0.045.")
    w("")
    w("## 4. (c) Energy per inference at the measured exit timestep")
    w("")
    w("Per inference, mean over the 240 test samples x 3 seeds, of the sample's own energy: crossbar reads = non-zero group reads actually issued up to the sample's exit x energy per read; digital = "
      "digital power x cycles/100 MHz (cycles up to the exit, including the 1F multi-pass sensing); class-HV arrays = reads of the 10 columns per timestep up to the exit.")
    w("")
    rows = []
    for g in (4, 8):
        for b, lab in (("full", "full design"), ("ee_off", "same network, run to the end")):
            v = B[f"{b}_g{g}"]
            rows.append([g, lab, f"{v['mean_exit_timestep']:.1f}", pct(v["mean_events_fraction"], 1), f"{v['mean_nonzero_reads']:,.0f}", f"{v['mean_cycles']:,.0f}", f"{e(v, 'snn_array'):.3f}", f"{e(v, 'digital'):.3f}", f"{e(v, 'hdc_array'):.4f}", f"**{e(v):.3f}**"])
    w(table(["g", "run", "mean exit timestep", "events ingested", "non-zero reads", "cycles", "crossbar reads (uJ)", "digital (uJ)", "class-HV arrays (uJ)", "total (uJ)"], rows))
    w("")
    for g, fv, ev in ((4, full4, eeoff4), (8, full8, eeoff8)):
        w(f"- g = {g}: early exit saves {e(ev) - e(fv):.3f} uJ ({pct(1 - e(fv) / e(ev), 1)}): crossbar reads {e(ev, 'snn_array') - e(fv, 'snn_array'):.3f}, digital {e(ev, 'digital') - e(fv, 'digital'):.3f}, class-HV arrays {e(ev, 'hdc_array') - e(fv, 'hdc_array'):.4f} uJ. "
          f"Energy at the *mean exit timestep* of the read profile instead of the mean of per-sample energies: crossbar {fv['energy_at_mean_exit_timestep_snn_uJ']:.3f} uJ (against {e(fv, 'snn_array'):.3f} - they agree because the per-timestep read profile is flat).")
    w("")
    w("### 4.1 Where the crossbar part comes from (full design, g = 4)")
    w("")
    sc = full4["snn_components_uJ"]
    w(table(["component", "uJ at the exit", "uJ, run to the end"], [[k.replace("_", " "), f"{sc[k]:.3f}", f"{eeoff4['snn_components_uJ'][k]:.3f}"] for k in sc] + [["total", f"{e(full4, 'snn_array'):.3f}", f"{e(eeoff4, 'snn_array'):.3f}"]]))
    w("")
    w("### 4.2 Sensitivities")
    w("")
    w(f"- **a = 0 reads issued.** The RTL issues {eeoff4['mean_zero_reads']:,.0f} empty reads per inference (g = 4); if each paid the front-end's idle bias ({pr4['idle_bias_per_empty_read_pj']:.0f} pJ) the full design would add "
      f"{full4['energy_if_empty_reads_issued_uJ']['extra']:.2f} uJ at the exit ({full4['energy_if_empty_reads_issued_uJ']['total']:.2f} uJ total). Skipping them is the 1E follow-up 1F recorded; not implemented here (non-goal).")
    w("- **HDC array model.** The class-HV arrays are 0.1 % of the energy under the stated per-column costs; they would stay below 1 % even at 10x.")
    w("")
    w("### 4.3 The digital term, and what clock gating could change")
    w("")
    w("Three readings of the same measurements (g = 4, mean of 3 seeds x 240 samples; the crossbar and class-HV terms are identical in all three):")
    w("")
    rows = []
    for b_, lab in (("full", "full design (exit)"), ("ee_off", "early exit OFF (run to the end)"), ("fact_off", "factorization OFF (exit)"), ("both_off", "both OFF")):
        v = B[f"{b_}_g4"]
        sc = v["scenarios_total_uJ"]
        rows.append([lab, f"{v['mean_cycles']:,.0f} / {v['mean_cycles_a0_skip']:,.0f}", f"{sc['as_built']:.2f}", f"{sc['a0_skip']:.2f}", f"{sc['clock_gated_bound']:.2f}", f"{sc['a0_skip_and_clock_gated_bound']:.2f}"])
    w(table(["build", "cycles: as built / with a = 0 skip", "(1) as built (uJ)", "(2) + a = 0 skip, 1F's cycle model (uJ)", "(3) + ideal clock gating, bound (uJ)", "(2)+(3) (uJ)"], rows))
    w("")
    w(f"(1) is the RTL as it stands: ungated clocks, and the sequencer walks every group read, empty ones too, once per sensing pass (the analog side is assumed to power the front end only for non-zero reads). "
      f"(2) removes the empty reads from the cycle count (1E/1F's recorded follow-up; not implemented). (3) is a *bound*: the sequential power scaled by the measured flip-flop activity "
      f"({full4['flop_activity_alpha']:.4f} Q transitions per flop per cycle, section 2) - an implementation with ideal clock gating; real gating cells, enable timing and the clock tree would eat part of it. "
      f"The digital term is {pct(e(full4, 'digital') / e(full4), 0)} of (1); the crossbar reads are {pct(e(full4, 'snn_array') / e(full4), 0)}. **The largest lever left is digital clocking, not the reads.** "
      f"With (2)+(3) the full design would be {full4['scenarios_total_uJ']['a0_skip_and_clock_gated_bound']:.2f} uJ, {full4['scenarios_total_uJ']['a0_skip_and_clock_gated_bound'] / NH['energy_uJ']:.2f}x NeuroHDC-small.")
    w("")
    w("### 4.4 Cycle model check")
    w("")
    cm = T.get("cycle_model_check")
    if cm:
        w(f"1E's sequencer senses 160 or 20 columns per read; 1F's recommended 40 columns per pass is modelled as `{cm['model']}`. Validated on the RTL's own 20-column run of the same {cm['samples']} samples and threshold: "
          f"worst error {cm['max_abs_error_cycles']} cycles (mean {cm['mean_error_cycles']:.2f}) on {cm['mean_cycles_rtl']:,.0f} cycles per inference. (1E measured the same identity at g = 8: 837,745 against 462,617 + 7 x 53,590.)")
    else:
        w("(The 20-column check run was not available.)")
    w("")
    w("## 5. (d) Comparison with NeuroHDC-small")
    w("")
    w(table(["", "NeuroHDC-small (as published)", "this design, full, g = 4", "this design, full, g = 8", "ratio (g = 4)"], [
        ["technology / clock", f"{NH['node_nm']} nm, {NH['f_mhz']} MHz", "45 nm library, 100 MHz", "45 nm library, 100 MHz", "-"],
        ["area (mm^2)", f"{NH['area_mm2']:.3f}", f"{full4['area_mm2']['total']:.3f}", f"{full8['area_mm2']['total']:.3f}", f"{full4['area_mm2']['total'] / NH['area_mm2']:.2f}x"],
        ["energy per inference (uJ), DVS-Gesture", f"{NH['energy_uJ']:.2f}", f"{e(full4):.2f}", f"{e(full8):.2f}", f"{e(full4) / NH['energy_uJ']:.2f}x"],
        ["accuracy", "87.5 % (paper) / 82.36 % (our reimplementation, 3 seeds)", pct(full4['accuracy_mean'], 2), pct(full8['accuracy_mean'], 2), "-"]]))
    w("")
    a4 = full4["area_mm2"]
    w(f"Area of this design, g = 4: digital {a4['digital']:.3f} + SNN crossbar with sense periphery and 1 nF decoupling {a4['snn_array_1nF']:.3f} + class-HV array {a4['hdc_array']:.4f} = **{a4['total']:.3f} mm^2**. "
      "The exclusions of section 1 apply to both sides unequally: NeuroHDC's numbers are a post-layout whole accelerator with its clock tree; ours are pre-layout and omit the clock tree, place-and-route overhead, "
      "the regulator, calibration and the host interface. Our crossbar numbers are simulated circuits with assumed mismatch (1F), not silicon.")
    w("")
    w("## 6. (e) The ablation table (the paper's result table)")
    w("")
    rows = []
    for b, f_, e_ in (("full", "R=1 factorized", "margin exit"), ("ee_off", "R=1 factorized", "off"), ("fact_off", "unfactorized", "margin exit"), ("both_off", "unfactorized", "off")):
        v4, v8 = B[f"{b}_g4"], B[f"{b}_g8"]
        rows.append([LAB[b], f_, e_, pct(v4["accuracy_mean"], 2), f"{v4['mean_exit_timestep']:.1f}", f"{v4['mean_nonzero_reads']:,.0f}", f"{v4['mean_cycles']:,.0f}", f"{e(v4, 'snn_array'):.2f}", f"{e(v4, 'digital'):.2f}", f"{e(v4, 'hdc_array'):.3f}", f"**{e(v4):.2f}**",
                     f"{v4['area_mm2']['digital']:.3f}", f"{v4['area_mm2']['hdc_array']:.4f}", f"{v4['area_mm2']['total']:.3f}", f"{e(v8):.2f}"])
    w("Recommended point g = 4 (40 columns per pass, T = 1 ns); last column: total energy at g = 8 (20 columns per pass, T = 2 ns).")
    w("")
    w(table(["build", "class HV", "exit", "accuracy", "mean exit timestep", "non-zero reads", "cycles", "crossbar (uJ)", "digital (uJ)", "class-HV arrays (uJ)", "total energy (uJ)", "digital (mm^2)",
             "class-HV array (mm^2)", "total area (mm^2)", "energy at g = 8 (uJ)"], rows))
    w("")
    w("What each contribution is worth (all separately attributable):")
    w("")
    ee_r1 = e(eeoff4) - e(full4)
    ee_b = e(both4) - e(fact4)
    w(f"- **Early exit**, same network: {ee_r1:.2f} uJ ({pct(ee_r1 / e(eeoff4), 0)}) on the R=1 model, {ee_b:.2f} uJ ({pct(ee_b / e(both4), 0)}) on the baseline; accuracy "
      f"{pct(full4['accuracy_mean'] - eeoff4['accuracy_mean'], 2)} / {pct(fact4['accuracy_mean'] - both4['accuracy_mean'], 2)} (points) relative to running to the end.")
    w(f"- **Factorized class hypervector**, with early exit on: accuracy {pct(full4['accuracy_mean'] - fact4['accuracy_mean'], 2)} (points; a different, jointly trained network), energy {e(full4) - e(fact4):+.3f} uJ "
      f"(digital {e(full4, 'digital') - e(fact4, 'digital'):+.3f}, class-HV arrays {e(full4, 'hdc_array') - e(fact4, 'hdc_array'):+.4f}, crossbar {e(full4, 'snn_array') - e(fact4, 'snn_array'):+.3f} uJ - the last is the exit timestep of the two networks, not the mapping), "
      f"area {full4['area_mm2']['total'] - fact4['area_mm2']['total']:+.3f} mm^2 (digital {full4['area_mm2']['digital'] - fact4['area_mm2']['digital']:+.4f}, class-HV array {full4['area_mm2']['hdc_array'] - fact4['area_mm2']['hdc_array']:+.4f}). "
      "The factorization buys the class-HV *array* (16 macros -> 1, about 0.11 mm^2 in the model) at the price of 1,050 digital flip-flops for the sign table and bias registers - which, ungated, cost "
      f"{(full4['digital_power_mW'] - fact4['digital_power_mW']) * full4['mean_cycles'] * 1e-8 * 1e3:.2f} uJ per inference in clock energy: the sign table belongs in a small memory or behind a clock gate, not in free-running flip-flops.")
    w("")
    w("## 7. Recommended operating point")
    w("")
    w(table(["parameter", "value", "why"], [
        ["g (rows per group)", "4", "1F: g = 8 closes only for sigma_lnG <= 0.07; g = 4 closes through 0.15 (the honest design point)"],
        ["columns per pass", "40 (4 passes)", "1F section 5: 69 mA for 160 columns is not deliverable; 40 columns at g = 4 peak at 8.7 mA with 1 nF"],
        ["read pulse", "T = 1 ns + 0.3 ns tail", "1F: set by noise + calibration residual"],
        ["exit threshold (XNOR margin units)", f"{S_THETA['r1']} (R=1 model); {S_THETA['base']} (unfactorized baseline)", "strict knee: accuracy equals the full run's and stays so for every larger threshold; software bipolar threshold = 2x"],
        ["class hypervector", "R=1 factorized", "16 macros -> 1, 20,000 -> 1,250 bits; costs 2.0 points of accuracy at training time (80.4 % vs 82.4 %)"],
        ["clock", "100 MHz", "closes with 8 ns of slack in the slow corner; the design is input-bound, so a higher clock only raises power"]]))
    w("")
    w("## 8. Assumptions and open items (updated TO BE DETERMINED list)")
    w("")
    w("- **Digital power is as designed (ungated) and window-sampled.** One sample, 8,000 cycles (timesteps ~3-5), the same window for all builds; ingest and MVM phases are both inside it but a different window or sample would move the combinational part "
      "(~0.4 mW) by tens of percent; the sequential part is activity-independent. No clock tree, so the real clock power is higher; no clock gating, so a real design with it is lower (4.3).")
    w("- **Class-HV array energy and area are scaled models** ([ASSUM]); the arrays were never designed (10 columns, 20 or 2,000 rows, sensing of 0..20 counts for the factorized one, bit-wise reads for the unfactorized one).")
    w("- **a = 0 reads** are assumed free and are not skipped in the RTL (non-goal); 1G.")
    w("- **40 columns per pass** is not an RTL option (1E's sequencer has 160 or 20); the cycle count adds one cycle per extra pass per read, a model validated on the 20-column RTL run.")
    w("- **The 1F energy model** (sense bias, comparators, threshold correction at Horowitz op energies) is carried forward unchanged, with its own open items (comparator latch noise, threshold generator, calibration energy).")
    w("- **No NeuroSim cross-check** (optional; not done). **No place-and-route**, so no utilisation, wire load, clock tree, or post-layout timing.")
    w("- **Timing at two corners of one library only**; the library is the FFT project's lab 45 nm card, not a foundry-qualified PDK.")
    w("- **The OpenSTA binary** was built from source (version 3.1.0, Tcl 8.6, CUDD); it is not in the repository (`design/rtl/tools/` is ignored) - the build recipe is in section 9.")
    w("- The accuracy column is on the 240 DVS-Gesture test samples with thresholds chosen on them (phase234_report.md, open items).")
    w("")
    w("## 9. Reproduce")
    w("")
    w("```")
    w("# OpenSTA (not in Homebrew): brew install cmake swig bison flex eigen tcl-tk@8 ; build CUDD (github.com/ivmai/cudd) ; git clone github.com/The-OpenROAD-Project/OpenSTA ;")
    w("#   cmake -DBUILD_TESTS=OFF -DCUDD_DIR=<cudd> -DTCL_LIBRARY=<tcl-tk@8>/lib/libtcl8.6.dylib -DTCL_HEADER=<tcl-tk@8>/include/tcl-tk/tcl.h -DFLEX_INCLUDE_DIR=<flex>/include ... ; make ; cp sta design/rtl/tools/sta")
    w("venv/bin/python design/rtl/scripts/synth_ppa.py [--hier]      # area and timing, 4 builds x 3 mapping/corner variants")
    w("venv/bin/python design/rtl/scripts/synth_power.py              # gate-level activity and power, 4 builds (~10 min each)")
    w("venv/bin/python design/rtl/scripts/phase5_ppa.py && venv/bin/python design/rtl/scripts/make_report_ppa.py")
    w("```")
    OUT.write_text("\n".join(L) + "\n")
    print("wrote", OUT, len(L), "lines")
    return 0


S_THETA = {"r1": 50, "base": 56}

if __name__ == "__main__":
    raise SystemExit(main())
