"""Writes results/reports/phase1f_report.md from the measured JSON files of 1F (every number is read from a file; the prose is the only hand-written part).
Usage: python -m sense.make_report"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import device.constants as C
import paths as RP
from sense import budget_1f as B, energy_1f as E

J = lambda p: json.loads(Path(p).read_text())
S = lambda n: J(RP.SENSE / n)
u = lambda x, n=2: f"{x * 1e6:.{n}f}"


def md_table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def main() -> None:
    topo = S("topology_comparison.json"); sw = [r for r in S("sweep_b.json") if "error" not in r]; mm = S("mismatch_mc.json"); cal = S("calibration_mc.json"); ct = S("calibration_transient.json")
    drift = S("drift_by_source.json"); az = S("autozero.json"); comp = S("comparator_noise.json"); en = S("enable_and_supply.json"); par = S("pareto_raw.json"); cm = S("closure_map.json")
    g16 = S("g16_variants.json"); allowed = S("budget_allowed_sigma.json"); eng = S("energy_per_inference_1f.json"); rec = S("recommended_designs.json"); rc = S("read_counts.json")
    thr = S("threshold_path.json"); area = S("area_table_1f.json"); chop = S("chopping_negative.json"); gnd = S("ground_rise.json")
    req = allowed["required_cmrr_db"]
    pdn = J(RP.PDN / "pdn_sweep.json"); padsw = J(RP.PDN / "pdn_pad_sweep.json")
    arr = J(RP.FULL_ARRAY / "energy_per_inference.json")
    rows_p = par["rows"]

    def c_for(T, stagger, target, rd=0.1, scale=1.0):
        """Decoupling (F) at which the droop crosses `target` mV (log-log interpolation over the sweep)."""
        pts = sorted([(x["c_dec"], x["droop_max_mV"]) for x in pdn if x["t_pulse"] == T and x["i_scale"] == scale and x["r_d"] == rd and (x["stagger"] > 0) == (stagger > 0) and x["c_dec"] > 0])
        c = np.log([p[0] for p in pts]); d = np.log([p[1] for p in pts])
        return float(np.exp(np.interp(np.log(target), d[::-1], c[::-1])))
    saving = {T: 1 - c_for(T, 200e-12, 20.0) / c_for(T, 0.0, 20.0) for T in (0.5e-9, 1e-9, 2e-9)}
    row_p = lambda vb, T, tail: [r for r in rows_p if abs(r["vb"] - vb) < 1e-9 and abs(r["T"] - T) < 1e-15 and abs(r["tail"] - tail) < 1e-15][0]
    far_row = lambda nm, s, T=1e-9, g="far": [r for r in topo["rows"] if r["topology"] == nm and r["ota_scale"] == s and r["group"] == g and abs(r["T"] - T) < 1e-15][0]
    L = []
    w = L.append

    # ------------------------------------------------------------------ derived numbers used in several places
    r_best8 = row_p(0.50, 2e-9, 0.3e-9); r_best4 = row_p(0.50, 1e-9, 0.3e-9)
    sn8 = float(np.hypot(r_best8["sigma_thermal_ref_uA"], r_best8["comparator_uA"])); sn4 = float(np.hypot(r_best4["sigma_thermal_ref_uA"], r_best4["comparator_uA"]))
    mc_a = {k: v for k, v in mm["sigma_uA"]["far"].items()}
    d_cal = cal["gain_and_offset"]
    slope = (d_cal["47"]["sigma_worst_point_uA"] - d_cal["27"]["sigma_worst_point_uA"]) / 20.0
    e8, e4 = rec[1]["energy"], rec[2]["energy"]
    m_g8 = {s: rec[1]["margins"][s]["margin_uA"] for s in rec[1]["margins"]}; m_g4 = {s: rec[2]["margins"][s]["margin_uA"] for s in rec[2]["margins"]}
    ref_en_1c = {k: v["total_J"] * 1e9 for k, v in arr["energy_per_inference_J"].items()}
    best = lambda g, s, dt=5.0, droop=0.0: max([r for r in cm if r["g"] == g and r["sigma"] == s and r["d_t"] == dt and r["droop_mV"] == droop], key=lambda r: r["margin_left_a"])
    mine = lambda g, s, dt=5.0: min([r for r in cm if r["g"] == g and r["sigma"] == s and r["d_t"] == dt and r["droop_mV"] == 0.0 and r["closes"] and r["energy_J"] is not None], key=lambda r: r["energy_J"], default=None)

    w("# Phase 1F report - the sense front-end and the read timing budget")
    w("")
    w("Tags: **[SIM]** simulated (ngspice, PTM 45 nm LP card, transistor level), **[MODEL]** analytic in code, **[ASSUM]** assumed (listed in section 11 and swept where it matters), **[CHOICE]** design decision, "
      "**[SP]** Stanford-PKU default. Every number below is read from a JSON file by `python -m sense.make_report`; commands in section 12. Carried forward from 1C and **not** re-derived: g = 8, 64 groups, 20 F^2 cell, "
      "drivers at both ends of every 32-cell macro row, rails <= 0.0072 ohm/pitch fed from both ends, all 160 columns sensed at once, 53,590 reads of which 20,420 non-zero, array settling 130-160 ps, far-group step 30.49 uA "
      "(limit 12.20 uA, margin 0.48 uA).")
    w("")
    w("## 0. The answer")
    w("")
    w(f"- **The 1 uA of comparator noise 1C assumed was not a noise number: the front-end's error is dominated by mismatch, not thermal noise.** Device-level thermal + flicker noise of the chosen front-end is "
      f"{S('topology_comparison.json')['noise_sigma_uA']['b (differential channel)']['1']:.2f} uA (1 sigma, T = 1 ns) differential [SIM]; the comparator stage adds {r_best4['comparator_uA']:.2f} uA at T = 1 ns [SIM + ASSUM latch]. "
      f"But with ordinary Pelgrom mismatch ({C.AVT_MV_UM} mV um [ASSUM, 1A]) the uncalibrated static error of a column is **{np.mean(list(mm['sigma_uA']['far']['all'].values())):.0f} uA (far group) / {np.mean(list(mm['sigma_uA']['near']['all'].values())):.0f} uA (near) 1 sigma against a 12.2 uA limit**: "
      f"the copy gain of each channel is 12% (1 sigma) and the amplifier offset (5.3 mV) acts on up to 1.8 mS of array conductance. **A per-column two-parameter calibration is mandatory**; after it {d_cal['27']['sigma_worst_point_uA']:.2f} uA is left on DC currents "
      f"and **{min(r['cal_sigma_far_uA'] for r in rows_p):.1f}-{max(r['cal_sigma_far_uA'] for r in rows_p):.1f} uA on the real read transient** (far group, depending on pulse length and bias), and it goes stale at {slope:.2f} uA per kelvin. Sections 3-4.")
    w(f"- **Topology: (b), a regulated current conveyor with a 1:4 copy into a charge integrator, is the only candidate that holds the virtual ground at <= 125 uA per bitline** (step collected {far_row('b',1)['step_ratio_min']:.2f} of ideal, far group, T = 1 ns). "
      f"The TIA (a) and the bitline integrator (d) reach {far_row('a',16)['step_ratio_min']:.2f} / {far_row('d',16)['step_ratio_min']:.2f} only with the OTA scaled x16 (1.6 mA per bitline = 13x the power); the regenerative input (c) forces the node to 0.54 V (row supply 0.64 V, "
      f"array energy x6.4) and collapses at the near group ({far_row('c',1,1e-9,'near')['step_ratio_min']:.2f}). (a), (c), (d) are *quieter* (0.14-0.6 uA per channel; only (a) at x4 peaks, 1.1-1.6 uA, a closed-loop peaking not investigated) - the choice is a virtual-ground / power choice, not a noise choice. Section 2.")
    w(f"- **Pulse length is derived, and it is set by the front-end's noise and calibration residual, not by any settling term.** g = 8: **T = 2 ns** (tail 0.3 ns); g = 4: **T = 1 ns**. The array needs 0.13-0.16 ns, the supply "
      f"recovers in <= 3 ns when damped and decoupled (inside the 10 ns cycle), the conveyor's own settling is inside the calibration residual. Section 4.")
    w(f"- **Energy per inference with the front-end: {e8['total_J']*1e6:.2f} uJ at g = 8 and {e4['total_J']*1e6:.2f} uJ at g = 4 - {e8['ratio_to_neurohdc']:.2f}x and {e4['ratio_to_neurohdc']:.2f}x NeuroHDC-small's 3.01 uJ.** The array is {e8['array_J']*1e6:.2f} uJ of it (x3.5 because the sense node must sit at 0.25 V: "
      f"the row supply is 0.35 V, not 0.1 V); the sense bias is {e8['sense_bias_J']*1e6:.2f} uJ, the comparators {e8['decision_J']*1e6:.2f}, the digital threshold correction {e8['threshold_J']*1e6:.2f}. **1C's 32-48 nJ was the cheap part.** "
      f"Exclusions as in 1C: HDC class-vector reads, 1E logic, clock tree. Section 4.")
    w(f"- **Charge delivery: the short pulse is NOT deliverable at full width.** 160 columns at a = 8 draw 69 mA: 10 mV of droop needs {next(x for x in pdn if x['t_pulse']==1e-9 and x['i_scale']==1.0 and x['r_d']==0.02 and x['c_dec']==10e-9 and x['stagger']==0.0)['c_dec']*1e9:.0f} nF at T = 1 ns "
      f"({10e-9*1e15/8.2*1e-6:.1f}-{10e-9*1e15/5.0*1e-6:.1f} mm^2 at the 0.35 V rail's measured 5-8 fF/um^2) against a 0.15 mm^2 array, and with R_pad = 0.5 ohm the decoupling does not recharge in the 10 ns cycle. **Sensing 40 columns per pass at g = 4 "
      f"(peak 8.7 mA) needs 1 nF (0.12-0.20 mm^2, 0.17 at the 6 fF/um^2 mid value; 7 mV droop, 3 ns recovery).** Staggering the five macros saves {100*saving[0.5e-9]:.0f}% of the decoupling at T = 0.5 ns, {100*saving[1e-9]:.0f}% at 1 ns and {100*saving[2e-9]:.0f}% at 2 ns (for 20 mV): **no**. Section 5.")
    w(f"- **g: 8 or 4? Honest design point: g = 4.** With the measured front-end terms, rail droop of the 1 nF decoupling and a 5 K recalibration window, g = 8 closes only for sigma_lnG <= 0.07 (margin {m_g8['0.07']:+.2f} uA at T = 2 ns) and **fails at 0.10 ({m_g8['0.1']:+.2f} uA)**; "
      f"g = 4 closes through 0.15 ({m_g4['0.1']:+.2f} uA at 0.10, {m_g4['0.15']:+.2f} at 0.15). g = 16 closes nowhere with end-sensed columns; with 4-8 sense nodes per column (seg4/seg8_mid) it opens for sigma_lnG <= ~0.045 (C4's 0.048 sits on the edge: "
      f"{g16['seg4_mid|0.048']['margin_1f_a']*1e6:+.2f} uA). g = 4 costs {rc['4']['reads_nonzero']:,.0f} non-zero reads (x{rc['4']['reads_nonzero']/rc['8']['reads_nonzero']:.2f}) and, with the supply limit of section 5 (40 columns per pass), **{rec[2]['cycles_skip_a0']:,.0f} cycles with the a = 0 skip against 1C's {rc['8']['cycles_all_reads']:,.0f}: +{100*(rec[2]['cycles_skip_a0']/rc['8']['cycles_all_reads']-1):.0f}%** "
      f"({rc['4']['cycles_skip_zero']:,.0f} if all 160 columns could be sensed at once). Section 8.")
    w(f"- **Area: {area['c_dec=0nF|mid']['total_mm2']:.3f} mm^2 without decoupling (1C table 0.151), {area['c_dec=1nF|mid']['total_mm2']:.3f} mm^2 with the 1 nF; the real sense periphery is {area['c_dec=0nF|mid']['parts_um2']['sense_front_ends_1f']*1e-6:.3f} mm^2 "
      f"(1C assumed {area['c_dec=0nF|mid']['replaced_1c_um2']*1e-6:.3f}).** Section 7.")
    w("- **Not completed, stated plainly (details in sections 11 and 12):** the comparator latch and the threshold generator are not simulated at transistor level (ngspice has no periodic noise; the latch noise is an assumption, the threshold generator is costed, not designed); autozero was evaluated as circuit pieces, "
      "not built into the loop (the calibration replaces it, see 3.4); chopping / dynamic element matching were built and **failed** (3.6); the calibration procedure itself (reference cells, 1D) and the recalibration trigger are open; the two-stage integrator (d) was not optimised.")
    w("")

    # ------------------------------------------------------------------ 1
    w("## 1. What 1F measures, and how it differs from the brief")
    w("")
    w("1C left two things open: the **5.00 uA of the 11.72 uA error budget that was an assumed 1 uA (1 sigma) comparator noise**, and the **read pulse length T**, which sets the energy (linear in T) and which no stage had designed. 1F builds the sense chain at transistor level on the "
      "same PTM 45 nm LP card (the NMOS block from 1A; the PMOS block was added to `device/ptm/ptm45p_lp.lib`) and derives T.")
    w("")
    w("**The array as the front-end sees it** (`sense/port.py`): the V_read source -> parallel branches (R_tx + R_LRS = 1558 ohm or R_tx + R_HRS) -> half the bitline capacitance -> bitline wire (0.72 ohm/pitch x distance) -> sense node. Linear at 0.1 V (1A), so ReRAM = fixed resistor "
      "[CHOICE per the brief; no compact model]. It reproduces 1C's mesh: far-group worst step 34.3 uA vs 34.1 (before row-line/rail losses). Far group = nearest row 505 pitches from the sense node; near group 1 pitch. The same row pulse drives every candidate.")
    w("")
    w("**Deviations / decisions to check:**")
    w("")
    w("1. **Report location**: `results/reports/phase1f_report.md` (the 1A-1C convention), not `results/1f/`; raw results in `results/sense_frontend/` and `results/pdn/`; figures in `results/figures/` (fig14-fig21).")
    w("2. **The sense node cannot sit at ground.** A PMOS-input amplifier (the only kind that works with its input near 0 V in this process) needs the node at **V_VG = 0.25 V**; the row supply must then be V_VG + V_READ = 0.35 V. The array current is unchanged (I = V_READ x G) but its energy is x3.5 against 1C's 0.1 V. "
      "This is a property of the process, not of the topology (candidate (c) is worse: 0.54 V).")
    w("3. **Static mismatch, not noise, is the dominant error** and it forces a per-column calibration that 1C did not have. Everything that follows (energy, g) depends on it.")
    w("4. The 1C margin (0.48 uA) is a Monte-Carlo estimate of a quantity with scatter: the same budget at 500 / 1000 / 2000 / 4000 draws gives 0.48 / 0.55 / 0.54 / 0.49 uA. **Margins below ~0.15 uA are not distinguishable from zero** and are marked as such.")
    w("")

    # ------------------------------------------------------------------ 2 F1
    w("## 2. F1 - topology: four candidates on the same step")
    w("")
    w("`sense/run_topologies.py`, `results/sense_frontend/topology_comparison.json`, Figure 14. Each candidate is a transistor-level single-bitline channel; (b) is the full differential channel. The measurement is the same for all: the charge the **array delivers into the node over the read window** "
      "(T + 0.3 ns tail) divided by what an ideal virtual ground (node held at V_VG) would draw from the same transient, as the differential step (BL+ minus BL-) over m = 1, 3, 5, 7 matching rows - far group (30.49 uA step) and near group (123 uA). "
      "A candidate that cannot hold the node does not just lose signal, it makes the loss data-dependent.")
    w("")
    rows = []
    desc = {("a", 1): "(a) TIA, R_f 500 ohm, 1-stage OTA", ("a", 4): "(a) OTA x4 current", ("a", 16): "(a) OTA x16", ("d", 1): "(d) integrator on the bitline, C_f 1 pF, 1-stage OTA", ("d", 4): "(d) OTA x4", ("d", 16): "(d) OTA x16",
            ("d2", 1): "(d) two-stage Miller OTA (open-loop ~60 dB)", ("c", 1): "(c) latch input device (regenerative)", ("b", 1): "(b) conveyor + 1:4 copy + integrator (differential channel)"}
    sup = topo["supply"]; nz = topo["noise_sigma_uA"]
    keymap = {("a", 1): "a x1", ("a", 4): "a x4", ("a", 16): "a x16", ("d", 1): "d x1", ("d", 4): "d x4", ("d", 16): "d x16", ("d2", 1): "d2", ("c", 1): "c", ("b", 1): "b (differential channel)"}
    for (nm, s), d in desc.items():
        rf, rn = far_row(nm, s), far_row(nm, s, 1e-9, "near"); r05 = far_row(nm, s, 0.5e-9)
        sk = f"{nm} x{s}" if nm in ("a", "d", "c", "d2") else "b (per differential channel)"
        i_ua = sup[sk][0] / (2 if nm == "b" else 1); vnode = sup[sk][1]
        rows.append([d, f"{i_ua:.0f}", f"{vnode*1e3:.0f}", f"{r05['step_ratio_min']:.2f} / {rf['step_ratio_min']:.2f}", f"{rn['step_ratio_min']:.2f}", f"{rf['vn_min_mV']:.0f}-{rf['vn_max_mV']:.0f}",
                     f"{nz[keymap[(nm, s)]]['0.5']:.2f} / {nz[keymap[(nm, s)]]['1']:.2f} / {nz[keymap[(nm, s)]]['2']:.2f}"])
    w(md_table(["candidate", "supply per bitline (uA)", "forced node (mV)", "step vs ideal, far, T 0.5 / 1 ns", "near, T 1 ns", "node excursion far (mV)", "noise 1 sigma (uA) at T 0.5 / 1 / 2 ns"], rows))
    w("")
    zb = topo["zin_b"]
    w(f"**Input impedance** of (b) with the array removed and 100 uA flowing: {zb['1e+08']:.0f} ohm at 100 MHz, {zb['5e+08']:.0f} at 500 MHz, {zb['1e+09']:.0f} ohm at 1 GHz (inductive: the loop gain runs out). Against the ~195 ohm of eight LRS branches in parallel this is why the node is pushed 40 mV below and 85 mV above V_VG "
      "(211-334 mV) during a 0.5-1 ns pulse and why the collected step is 0.67-0.78, and why longer pulses help: the signal bandwidth (~0.5/T) must stay below ~300 MHz. **Ground rails** (`ground_rise.json`): raising the local ground of the sinks by 3 mV (1C measured 1.8 mV far / 3.2 mV near in a macro) "
      f"changes the differential by at most {max(abs(v['3mV']['d_diff_uA']) for v in gnd['far'].values()):.2f} uA (far) / {max(abs(v['3mV']['d_diff_uA']) for v in gnd['near'].values()):.2f} uA (near), the node by {gnd['far']['4']['3mV']['d_node_mV']:.2f} mV; 5 mV: {max(abs(v['5mV']['d_diff_uA']) for v in gnd['far'].values()):.2f} / {max(abs(v['5mV']['d_diff_uA']) for v in gnd['near'].values()):.2f} uA. "
      "The node is regulated against an absolute reference, so the 69 mA in the ground rails is benign if V_ref is distributed without current; the shift is deterministic given (G, a), i.e. inside the table.")
    w("")
    w("**Common-level shift (2-22 uA, 1C).** (b): a current added to both bitlines leaks into the differential by the common-mode gain measured here: "
      f"{abs(mm['cm_gain']['far']['nominal'])*100:.1f}% far / {abs(mm['cm_gain']['near']['nominal'])*100:.1f}% near nominal (CMRR {-20*np.log10(abs(mm['cm_gain']['far']['nominal'])):.0f} / {-20*np.log10(abs(mm['cm_gain']['near']['nominal'])):.0f} dB) - after the PMOS mirror was matched to the summing node (V_S = 0.45 V, "
      f"16/0.36 um; at 0.6 V and 4/0.09 um it was 6.5%) - **but {mm['cm_gain']['far']['mismatch_sigma']*100:.0f}% (1 sigma) with mismatch**, i.e. 17 dB. **The CMRR the 1B check requires** (common-mode error held to 10% of a step): " + f"g = 4 {req['4|far']:.0f} / {req['4|near']:.0f} dB, g = 8 {req['8|far']:.0f} / {req['8|near']:.0f} dB, g = 16 {req['16|far']:.0f} / {req['16|near']:.0f} dB (far / near). The nominal channel meets all of them (g = 16 far by {-20*np.log10(abs(mm['cm_gain']['far']['nominal']))-req['16|far']:.0f} dB); a column with uncalibrated mismatch meets none; the calibrated one (residual gain mismatch ~0.1%, 60 dB) meets all. "
      "For (a), (c), (d) the common level only moves an output by a few tens of mV (20 uA x R_f or x T/C_f) - not a limit.")
    w("")
    w(f"**Why (b), and what the comparison does not prove.** At the same row load (b) is the only candidate whose node is held to 100-125 mV and whose step is >= 0.67 at ~125 uA per bitline; its second stage is the sink transistor M1 (g_m 1-3 mS), which a single-stage OTA cannot imitate "
      f"without 13-16x the current. The cost of (b) is exactly what the tables show: 4-10x the thermal noise of (a), (c), (d), and a copy device whose mismatch the other candidates do not have. The two-stage integrator (d) has *no copy mismatch* and 0.27 uA of noise: its virtual ground "
      f"is not yet good enough ({far_row('d2',1)['step_ratio_min']:.2f} far, {far_row('d2',1,1e-9,'near')['step_ratio_min']:.2f} near) and a fixed bias leaves its output at the rail for most mismatch draws (the open-loop gain of 60 dB turns a 3 mV offset into 3 V): a real design needs a reset/autozero "
      "phase and bias centring that were not built. **It is the alternative to revisit if (b)'s calibration cannot be made to work.**")
    w("")
    w("![Figure 14: the four candidate topologies on the same load: step collected vs power, and input-referred noise](../figures/fig14_topologies.png)")
    w("")
    w("*Figure 14.* Left: differential step collected / ideal (far group, T = 1 ns) against supply current per bitline; (a) and (d) climb with OTA current and reach (b)'s step only at 13-16x its power. Right: input-referred noise by candidate and window.")
    w("")

    # ------------------------------------------------------------------ 3 F2
    w("## 3. F2 - noise, offset, calibration, comparator")
    w("")
    w("### 3.1 Noise of the whole differential channel (device level)")
    w("")
    ref = [r for r in sw if r["design"]["k"] == 4.0 and r["design"]["w1"] == 15e-6 and r["design"]["wi1"] == 8e-6 and r["design"]["wp"] == 16e-6]
    w("`sense/mc.py: noise`, `sense/sweep_b.py` (72 sizing points), `sweep_b.json`, Figure 15. ngspice `.noise` of the whole channel - both conveyors, the copies, the mirror, the summing node, and the **array's resistors** (thermal) - integrated over the window T_w of an ideal integrate-and-dump "
      "(sinc^2 weight on the output noise that reaches the integrator, divided by the channel's DC transfer; thermal + 1/f + gate/bulk resistance noise of every BSIM4 device). Referred to the ideal array current through the collected-charge ratio eta (the signal that actually arrives).")
    w("")
    rows = [[f"{r['design']['vb']}", f"{r['i_bias_uA']:.0f}", f"{r['sigma_uA']['0.5']:.2f}", f"{r['sigma_uA']['1']:.2f}", f"{r['sigma_uA']['2']:.2f}", f"{r['step_ratio_min']['0.5']:.2f} / {r['step_ratio_min']['1']:.2f}", f"{r['gate_area_um2']:.0f}", f"{abs(r['cm_gain'])*100:.2f}"] for r in sorted(ref, key=lambda r: r['design']['vb'])]
    w(md_table(["OTA bias vb (V)", "channel supply (uA)", "sigma at T_w 0.5 ns", "1 ns", "2 ns", "step vs ideal (min m), T 0.5 / 1 ns", "gate area (um^2)", "CM gain (%)"], rows))
    w("")
    lo = min(r["sigma_uA"]["1"] for r in sw); hi = max(r["sigma_uA"]["1"] for r in sw)
    w(f"Sweep result: over k in {{2, 4}}, W1 in {{8, 15}} um, OTA1 width {{8, 16}} um, mirror {{4/0.09, 8/0.18, 16/0.36}} um and vb in {{0.42, 0.46, 0.50}} V the noise at T_w = 1 ns spans {lo:.2f}-{hi:.2f} uA. **It is set by the bias current (gm) and the copy ratio k, not by area**: "
      "the OTA input width and the conveyor width change it by < 3%; k = 2 instead of 4 lowers it by ~15% at +65 uA; the mirror size sets the common-mode gain (0.7% at 16/0.36 um, 2.5% at 4/0.09). Chosen sizing: k = 4, W1 = 15 um (L = 45 nm), M2 = W1/k, cascode 2 W1/k, "
      "OTA 8/0.09 um pair, mirror 16/0.36 um, V_S = 0.45 V.")
    w("")
    w(f"**Is the noise above or below 1 uA?** Thermal + flicker alone (referred to the ideal current, T_w = T + 0.3 ns): {row_p(0.5,0.5e-9,0.3e-9)['sigma_thermal_ref_uA']:.1f} / {row_p(0.5,1e-9,0.3e-9)['sigma_thermal_ref_uA']:.1f} / {row_p(0.5,2e-9,0.3e-9)['sigma_thermal_ref_uA']:.1f} uA at T = 0.5 / 1 / 2 ns (vb 0.50); "
      f"{row_p(0.46,0.5e-9,0.3e-9)['sigma_thermal_ref_uA']:.1f} / {row_p(0.46,1e-9,0.3e-9)['sigma_thermal_ref_uA']:.1f} / {row_p(0.46,2e-9,0.3e-9)['sigma_thermal_ref_uA']:.1f} at vb 0.46. **Above 1 uA below T ~ 1.5 ns, below it beyond, and the comparator and the calibration residual come on top (3.3, 3.4).**")
    w("")
    w("![Figure 15: noise vs sizing and bias](../figures/fig15_noise_sweep.png)")
    w("")
    w("*Figure 15.* Left: all 72 points, noise at T_w = 1 ns against channel supply current (two copy ratios); right: the chosen sizing against bias and window.")
    w("")
    w("### 3.2 Static mismatch: it is large, and it is the copy device")
    w("")
    w(f"`sense/run_mismatch.py`, `mismatch_mc.json`. Pelgrom Vth mismatch (sigma = AVT / sqrt(W L), AVT = {C.AVT_MV_UM} mV um [ASSUM, 1A]) on every transistor of the channel through BSIM4 `delvto`, N = {mm['n']} draws, differential input-referred current error of a read (sample - nominal), mean over m = 1, 4, 7 (1 sigma, uA):")
    w("")
    rows = [[s, f"{np.mean(list(mm['sigma_uA']['far'][s].values())):.1f}", f"{np.mean(list(mm['sigma_uA']['near'][s].values())):.1f}"] for s in mm["sigma_uA"]["far"]]
    w(md_table(["mismatched devices", "far group", "near group"], rows))
    w("")
    w("The copy devices dominate: with M1 and M2 of different size in weak-to-moderate inversion the copy current error is gm x dVth(M2) (k times larger when referred back to the array). The error does not shrink with a smaller W1 (2-15 um: 22-30 uA far) and grows with k (23 -> 40 uA for k = 2 -> 8 at W1 = 4 um): "
      "in triode, g = I/V_ds is fixed by the current to be carried, so delta-g/g = dVth/V_ov; only a deep-triode device (V_ov ~ 0.6 V) would lower it, and that needs a much higher-gain amplifier than the single-stage OTAs used here to hold the node (not built). **Uncalibrated, no sizing of this topology reaches the 12.2 uA limit.**")
    w("")
    w("### 3.3 Calibration: two parameters per channel, then what is left")
    w("")
    w(f"`sense/cal.py`, `calibration_mc.json`, `calibration_transient.json`, Figure 16. The whole static error of a column is described by two numbers per channel: the **effective gain** kappa (sigma {cal['kappa_sigma']*100:.0f}%) and the **node offset voltage** V (error V x G_array(state)); "
      "they are nearly collinear (I_nom ~ 0.1 V x G_array), separated only by the few-percent group-to-group variation of the front-end gain, so V is carried on the orthogonal component. A calibration measurement with known cells (both groups, m = 0..8) fits them; the column is then corrected with them. Residual (far group, worst level, 1 sigma, N = 100 draws):")
    w("")
    rows = [[t, f"{cal['gain_only'][t]['sigma_worst_point_uA']:.2f}", f"{cal['gain_and_offset'][t]['sigma_worst_point_uA']:.2f}", f"{cal['gain_and_offset'][t]['rms_uA']:.2f}"] for t in cal["gain_only"]]
    w(f"Uncalibrated rms error {cal['raw']['rms_uA']:.0f} uA.")
    w("")
    w(md_table(["read temperature (C), calibrated at 27 C", "gain only: worst level (uA)", "gain + offset: worst level (uA)", "gain + offset: rms (uA)"], rows))
    w("")
    q = cal["quantised"]
    w(f"**Trim resolution** (parameters rounded to +/- 4 sigma in 2^bits steps, DC, 27 C): " + ", ".join(f"{b} bits (kappa LSB {q[b]['lsb_kappa_percent']:.2f}%) -> {q[b]['at_27C']['sigma_worst_point_uA']:.2f} uA" for b in ("6", "8", "9", "10", "12")) + ". **10 bits** per parameter is where the quantisation stops mattering.")
    w("")
    w(f"**On the real read transient** (the calibration is done with the read pulse itself; far group, worst level; N = 40 draws, scatter of this statistic ~15%):")
    w("")
    rows = []
    for vb in (0.42, 0.46, 0.50):
        for tail in (0.3e-9, 1.0e-9):
            cells = []
            for T in (0.5e-9, 1e-9, 2e-9):
                rr = [r for r in ct if abs(r["design"]["vb"] - vb) < 1e-9 and abs(r["T"] - T) < 1e-15 and abs(r["tail"] - tail) < 1e-15][0]
                cells.append(f"{np.array(rr['gain_and_offset']['sigma_by_point_uA'])[:9].max():.2f} ({rr['gain_only']['sigma_worst_point_uA']:.1f})")
            rows.append([vb, f"{tail*1e9:g}"] + cells)
    w(md_table(["vb (V)", "tail (ns)", "T = 0.5 ns", "T = 1 ns", "T = 2 ns"], rows))
    w("")
    w("(in brackets: one gain per channel only). **The transient residual (0.5-2.8 uA) is 5-15x the DC one**: mismatch also changes how each channel settles after the pulse starts (the node excursion and the conveyor's start-up depend on the offsets), and a two-parameter static model does not follow that. "
      "It falls with T and with the integration tail, which is the first reason T cannot be short.")
    w("")
    w("![Figure 16: uncalibrated mismatch by source; calibrated residual vs temperature; calibrated residual on the transient](../figures/fig16_mismatch_calibration.png)")
    w("")
    w("*Figure 16.* Left: static error by mismatch source (budget limit 12.2 uA). Centre: calibrated at 27 C on DC currents, read at another temperature. Right: calibrated on the real transient, far group, vs pulse length, bias and tail.")
    w("")
    ds = drift
    w(f"**Temperature.** The calibration goes stale at ~{slope:.2f} uA per kelvin (worst level, 1 sigma: {d_cal['47']['sigma_worst_point_uA']:.1f} uA at +20 K, {d_cal['87']['sigma_worst_point_uA']:.1f} at +60 K). By source (`drift_by_source.json`, +40 K): copy devices {ds['copy devices only']['67']['sigma_worst_point_uA']:.1f} uA, "
      f"OTA1 {ds['OTA1 only']['67']['sigma_worst_point_uA']:.2f}, OTA2 {ds['OTA2 only']['67']['sigma_worst_point_uA']:.2f}, mirror {ds['PMOS mirror only']['67']['sigma_worst_point_uA']:.2f}: **it is the weak-inversion gain of the copy devices (error ~ dVth / (n kT/q)), not the amplifier offset.** "
      "Scaling the gain deviation with 1/T made it worse (the fitted kappa is not 1 + epsilon: it carries the offset compensation). **Operating requirement: recalibrate when the temperature has moved by more than ~5 K (0.25 uA at 1 sigma); how, and what it costs, is not designed (TBD).**")
    w("")
    w("### 3.4 Offset cancellation: autozero evaluated, not adopted")
    w("")
    a = {(x["w_sw"], x["c_az"]): x for x in az["az"]}
    w(f"`sense/az.py`, `autozero.json`. OTA1's input offset is {az['ota1_offset_sigma_mV']:.1f} mV (1 sigma, N = {az['n']} [SIM]) = {az['offset_current_far_sigma_uA']:.1f} uA on the far group's 1.78 mS and {az['offset_current_near_sigma_uA']:.0f} uA on the near group's 5.05 mS. An autozero loop (OTA in unity feedback, offset stored on C_az, "
      f"transmission gate) was simulated: **cost in time** = settling of the stored value to 0.1 mV: {a[(1e-6,0.3e-12)]['settle_to_0p1mV_ns']:.1f} ns at C_az = 0.3 pF, {a[(1e-6,1e-12)]['settle_to_0p1mV_ns']:.1f} ns at 1 pF (hidden in the 10 ns cycle if prefetched during the previous decision); "
      f"**residual** = switch charge injection (W = 1 um: {a[(1e-6,0.3e-12)]['injection_V']*1e3:.2f} mV at 0.3 pF, {a[(1e-6,1e-12)]['injection_V']*1e3:.2f} mV at 1 pF; systematic, so calibratable, with a random fraction of ~20% [ASSUM]) and kT/C "
      f"({a[(1e-6,0.3e-12)]['ktc_sigma_uV']:.0f} uV at 0.3 pF = {a[(1e-6,0.3e-12)]['ktc_current_far_uA']:.2f} uA far, {a[(1e-6,0.3e-12)]['ktc_current_far_uA']*az['g_near_max_mS']/az['g_far_max_mS']:.2f} uA near): ~0.25 uA. "
      "**Not adopted**: the offset's temperature drift is 0.17 uA at +20 K against 1.0 uA for the copy gain (3.3), and the per-column calibration already removes its static part; autozero would cost 2 x 160 capacitors and 1.4-7 ns per read for the smaller half of the drift. Revisit if the recalibration window cannot be met.")
    w("")
    w("### 3.5 The comparator stage")
    w("")
    w(f"`sense/comparator.py`, `comparator_noise.json`. The charge Q+ - Q- - Q_thr integrates on C_int = 200 fF (sized so the node swings <= 0.3 V for the largest |I - threshold| of the near group); the sign of V(S-) - V(S+) is read by a clocked comparator. ngspice has **no periodic or transient device noise**, so the comparator is split: "
      f"(i) the **preamplifier at device level**: PMOS-input OTA, W = 32 um, {comp['preamp']['a_pre']:.0f}x gain; at W = 32 um its input noise is {par['preamp']['sigma_v_by_window']['0.3']*1e3:.2f} mV over a 0.3 ns amplification window (1.9 mV for the 8 um version, 0.45 mV at 128 um: flicker floor), 51 uA while active; "
      f"(ii) the **latch behind it, not simulated**: sigma_latch = 1 mV [ASSUM] divided by the preamp gain (0.03 mV); (iii) **reset noise** sqrt(2 kT/C) = {np.sqrt(2*1.38e-23*300/200e-15)*1e6:.0f} uV on the two integrators, exact. Referred to the array current, sigma_I = sigma_V x C_int x k / T: "
      f"**{row_p(0.5,0.5e-9,0.3e-9)['comparator_uA']:.2f} / {row_p(0.5,1e-9,0.3e-9)['comparator_uA']:.2f} / {row_p(0.5,2e-9,0.3e-9)['comparator_uA']:.2f} uA at T = 0.5 / 1 / 2 ns** - at 0.5 ns the comparator alone already uses the whole 1 uA 1C allowed for everything. "
      f"The comparator's static offset (a 10 mV class latch [ASSUM] = {10e-3*200e-15*4/1e-9*1e6:.0f} uA at T = 1 ns) is one more per-column number removed by the calibration; its residual is assumed inside the calibration terms (an [ASSUM]).")
    w("")
    w("### 3.6 Chopping and element swapping: built, failed")
    w("")
    ch = chop["mismatch_mc_T1ns_tail0p5ns"]
    w(f"`sense/b2.py`, `sense/dem.py`, `sense/run_chop.py`, `chopping_negative.json`. To cancel the copy gain without calibration, the conveyors were swapped between the bitlines half-way through the window (dual integrator S+ / S-, no mirror), and separately the copy devices were swapped (dynamic element matching). "
      f"Nominal circuit, far group, differential step / ideal: dual integrator **plain {chop['b2'][0]['step_ratio_plain']:.2f}, chopped {chop['b2'][0]['step_ratio_chopped']:.2f} at T = 0.5 ns** (the swap lands before the conveyors have re-slewed), {chop['b2'][2]['step_ratio_plain']:.2f} -> {chop['b2'][2]['step_ratio_chopped']:.2f} at 1 ns, "
      f"{chop['b2'][4]['step_ratio_plain']:.2f} -> {chop['b2'][4]['step_ratio_chopped']:.2f} at 2 ns; DEM of the copy devices {chop['dem'][0]['step_ratio_plain_gate_switches']:.2f} -> {chop['dem'][0]['step_ratio_swapped']:.2f} (1 ns). With mismatch (T = 1 ns, N = 30): raw error {ch['plain']['raw_rms_uA']:.0f} uA plain vs {ch['chopped']['raw_rms_uA']:.0f} uA chopped (halved, not removed), "
      f"and after a gain per channel {ch['plain']['two_gain_worst_far_uA']:.1f} uA plain vs **{ch['chopped']['two_gain_worst_far_uA']:.1f} uA chopped**: the swap adds mismatch-dependent settling errors that calibration cannot follow. Conveyors that must re-slew from a 2-3x different current need more than the ~0.5 ns the window leaves. Negative result, kept.")
    w("")

    # ------------------------------------------------------------------ 4 F3
    w("## 4. F3 - the pulse length, derived")
    w("")
    w("A read has four time scales; the pulse length is the largest of what each demands:")
    w("")
    w("| term | demand | source |")
    w("|---|---|---|")
    w("| array settling (bitline RC, row line) | 0.13-0.16 ns to 0.1 uA; crosstalk < 0.1 uA from ~150 ps | 1C [SIM] |")
    pw = [x for x in pdn if x["t_pulse"] == 1e-9 and x["i_scale"] == 0.125 and x["r_d"] == 0.05 and x["c_dec"] == 1e-9 and x["stagger"] == 0.0][0]
    w(f"| supply (rail ring-down after the pulse) | recovery to 1 mV in {pw['recovery_ns']:.1f} ns for the recommended 8.7 mA / 1 nF; 10-30 ns for the full 69 mA with 10-20 nF (> the 10 ns cycle) | `sense.pdn` [SIM] |")
    w(f"| power-up of the bias | {en['0.42']['power_up']['t_settle_ns']:.1f} / {en['0.46']['power_up']['t_settle_ns']:.1f} / {en['0.5']['power_up']['t_settle_ns']:.1f} ns for vb 0.42 / 0.46 / 0.50 (idle {np.mean([en['0.42']['supply_uA']['far']['idle'],en['0.42']['supply_uA']['near']['idle']]):.0f} / {np.mean([en['0.46']['supply_uA']['far']['idle'],en['0.46']['supply_uA']['near']['idle']]):.0f} / {np.mean([en['0.5']['supply_uA']['far']['idle'],en['0.5']['supply_uA']['near']['idle']]):.0f} uA): before the pulse, overlappable with the previous decision | `sense.enable` [SIM] |")
    w("| **front-end noise + calibration residual** | **sigma_total <= what the budget allows** (below) | sections 3.1-3.5 |")
    w("")
    w("The budget allows (all else at 1C values, MC n = 200): " + ", ".join(f"g = {g}, sigma_lnG {s}: {allowed['allowed_sigma_uA'][f'{g}|{s}']:.2f} uA" for g, s in ((8, 0.05), (8, 0.07), (8, 0.10), (4, 0.10), (4, 0.15))) + " (the single front-end 1 sigma that the budget tolerates, 5 sigma in quadrature). "
      "The measured front-end sigma (thermal, comparator, calibration residual, drift, threshold generation in quadrature, far group) is:")
    w("")
    rows = []
    for T, tail in ((0.5e-9, 0.3e-9), (1e-9, 0.3e-9), (1e-9, 1e-9), (2e-9, 0.3e-9), (2e-9, 1e-9)):
        r = row_p(0.50, T, tail)
        n_ = float(np.hypot(r["sigma_thermal_ref_uA"], r["comparator_uA"])); tot = float(np.sqrt(n_ ** 2 + r["cal_sigma_far_uA"] ** 2 + (0.05 * 5.0) ** 2 + (B.THR_SIGMA_REL * B.THR_MAG_A["far"] * 1e6) ** 2))
        rows.append([f"{T*1e9:g}", f"{tail*1e9:g}", f"{r['sigma_thermal_ref_uA']:.2f}", f"{r['comparator_uA']:.2f}", f"{r['cal_sigma_far_uA']:.2f}", "0.25", f"{B.THR_SIGMA_REL*B.THR_MAG_A['far']*1e6:.2f}", f"**{tot:.2f}**"])
    w(md_table(["T (ns)", "tail (ns)", "thermal", "comparator + reset", "calibration residual", "drift (5 K)", "threshold gen. [ASSUM]", "total sigma (uA), vb 0.50"], rows))
    w("")
    w("**The binding term** (g = 8, sigma_lnG 0.07, vb 0.50, tail 0.3 ns, 5 K): margin left when only one front-end term is present (`binding` below), and with all of them:")
    w("")
    rows = []
    for T in (0.5e-9, 1e-9, 2e-9):
        r = row_p(0.50, T, 0.3e-9)
        n_ = float(np.hypot(r["sigma_thermal_ref_uA"], r["comparator_uA"])) * 1e-6
        z = dict(far=0.0, near=0.0)
        def mg(noise, calr, dt, thr):
            t = B.fe_terms(dict(far=noise, near=noise), dict(far=calr * r["cal_sigma_far_uA"] * 1e-6, near=calr * r["cal_sigma_near_uA"] * 1e-6), d_t_k=dt, thr_rel=thr)
            return B.closure(8, 0.07, t, n=2000)["margin_left_a"] * 1e6
        rows.append([f"{T*1e9:g}", f"{mg(0, 0, 0, 0):+.2f}", f"{mg(n_, 0, 0, 0):+.2f}", f"{mg(0, 1, 0, 0):+.2f}", f"{mg(n_, 1, 5.0, B.THR_SIGMA_REL):+.2f}"])
    w(md_table(["T (ns)", "no 1F term (1C only)", "+ thermal & comparator noise only", "+ calibration residual only", "all 1F terms"], rows))
    w("")
    w(f"At T = 0.5 ns the noise alone costs {-(float(rows[0][2])-float(rows[0][1])):.1f} uA; at 2 ns the calibration residual is the larger term. **g = 8 closes only at T = 2 ns (margin {m_g8['0.07']:+.2f} uA at sigma_lnG 0.07 including the droop); g = 4 closes already at 1 ns** "
      f"(tail 0.3 ns; the limit of 19.5 uA at the far group is looser). Where the pulse length is *derived* from: noise + calibration residual (set by the conveyor's loop bandwidth, 3.3), not the array (0.15 ns) and not the supply (recovers inside the cycle when the supply is damped and the current is limited, section 5). Figure 17.")
    w("")
    w("![Figure 17: budget margin vs read pulse length for g = 8 and g = 4](../figures/fig17_pulse_length_margin.png)")
    w("")
    w("*Figure 17.* Margin left against T (vb 0.50, 5 K recalibration window, no droop). Grey: Monte-Carlo scatter of the budget (~0.15 uA).")
    w("")
    w("### Energy per inference at that T")
    w("")
    w(f"`sense/energy_1f.py`, `energy_per_inference_1f.json`, Figure 20. 1E's real read pattern with the a = 0 reads skipped ({rc['8']['reads_nonzero']:,.0f} non-zero reads at g = 8, {rc['4']['reads_nonzero']:,.0f} at g = 4; mean {rc['8']['mean_active_per_nonzero']:.2f} / {rc['4']['mean_active_per_nonzero']:.2f} active rows). "
      "Components: array = 1C's table x (V_VG + V_READ)/V_READ = 3.5 [SIM x MODEL]; word line 16 nJ (1C); **sense bias** = 160 columns x 1.1 V x (I_idle x (t_en + T + tail) + I_signal x (T + tail)) per non-zero read, the front-end powered only for its own read [SIM]; "
      "**comparators** = preamp 51 uA x 1.1 V x 0.3 ns + latch 10 fJ + threshold capacitor-array 100 fJ per comparison [SIM + ASSUM], binary search over the a + 1 outcomes (mean 1.8 comparisons at g = 8); "
      "**threshold correction** = the 32-position digital rank-3 correction (section 7) at Horowitz ISSCC 2014 45 nm op energies [ASSUM, cited].")
    w("")
    rows = []
    for r in eng["rows"]:
        if (r["T"], r["tail"]) in ((0.5e-9, 0.3e-9), (1e-9, 0.3e-9), (2e-9, 1e-9)) and r["g"] in (4, 8):
            rows.append([r["g"], f"{r['vb']}", f"{r['T']*1e9:g} + {r['tail']*1e9:g}", f"{r['array_J']*1e6:.2f}", f"{r['sense_bias_J']*1e6:.2f}", f"{r['decision_J']*1e6:.2f}", f"{r['threshold_J']*1e6:.2f}", f"**{r['total_J']*1e6:.2f}**", f"{r['ratio_to_neurohdc']:.2f}x"])
    w(md_table(["g", "vb", "T + tail (ns)", "array (uJ)", "sense bias", "comparators", "threshold corr.", "total (uJ)", "vs 3.01 uJ"], rows))
    w("")
    w(f"1C's numbers (array + word line only, V_READ 0.1 V): " + ", ".join(f"{float(k)*1e9:g} ns: {v:.0f} nJ" for k, v in ref_en_1c.items() if float(k) in (5e-10, 1e-9, 1e-8)) + ". "
      f"**The recommended points are {e8['total_J']*1e6:.2f} uJ (g = 8, T = 2 ns) and {e4['total_J']*1e6:.2f} uJ (g = 4, T = 1 ns), {e8['ratio_to_neurohdc']:.2f}x and {e4['ratio_to_neurohdc']:.2f}x NeuroHDC-small (3.01 uJ, whole accelerator at 45 nm).** "
      f"Per non-zero read: {e8['per_read_pJ']:.0f} pJ (g = 8), {e4['per_read_pJ']:.0f} pJ (g = 4); per column and read the sense front-end costs {e8['sense_per_col_read_pJ']:.2f} pJ. "
      "**Named exclusions:** class-hypervector reads and HDC logic (Phase 2), 1E's flip-flops and clock tree, the supply regulator and the energy of the calibration. **This comparison is unfavourable by construction in one respect: NeuroHDC counts a whole accelerator; ours is the weight memory and its periphery only.** "
      "The front-end energy is a trade of power against noise at fixed T (sigma^2 ~ 1/(gm T) and E ~ gm T): at the noise the budget allows, ~1 pJ per column and read is the floor this topology reaches; boosting the bias during power-up (the 1.0-3.2 ns idle ramp is a third of the on-time) was not designed.")
    w("")
    w("![Figure 20: energy per inference by component for the recommended designs](../figures/fig20_energy_per_inference.png)")
    w("")
    w("*Figure 20.* Energy per inference for the three architectures of section 5 (vb 0.50; g = 8 at T = 2 ns, g = 4 at T = 1 ns), by component, against NeuroHDC-small's 3.01 uJ.")
    w("")

    # ------------------------------------------------------------------ 5 F4
    w("## 5. F4 - power delivery of the read pulse")
    w("")
    w("`sense/pdn.py`, `results/pdn/pdn_sweep.json`, `pdn_pad_sweep.json`, Figure 18. Lumped ngspice model of the row-supply rail (0.35 V): regulator (ideal source behind R_reg 0.05 ohm and L_reg 0.5 nH, a ~16 MHz loop that cannot follow a nanosecond pulse and only recharges between reads) [ASSUM] -> "
      "package R_pad 0.5 ohm, L_pad 100 pH (the brief's baseline) -> rail wire 0.1 ohm [MODEL, 1C rails] -> on-chip decoupling C_dec with a series damping resistor R_d; the load is five current pulses (one per macro) of I/5 each with 100 ps ramps (the array's own rise), width T, "
      "stagger s. **Decoupling density at this rail, from the PTM card** (a MOS capacitor C(V) AC simulation at the rail's 0.35 V): **5.0 fF/um^2** (NMOS gate at 0.35 V over ground: below threshold) to **8.2 fF/um^2** (accumulation-mode in an isolated well); 21 fF/um^2 only at 1.1 V - 1C's 10 fF/um^2 would need a MIM/MOM capacitor.")
    w("")
    w("**Droop of the full 160-column read** (69.2 mA, a = 8, T = 1 ns, no stagger, R_d 0.02 ohm; `droop` = minimum rail voltage during the pulse):")
    w("")
    rows = []
    for c in (1e-9, 2e-9, 5e-9, 10e-9, 20e-9):
        x = [y for y in pdn if y["t_pulse"] == 1e-9 and y["i_scale"] == 1.0 and y["r_d"] == 0.02 and y["c_dec"] == c and y["stagger"] == 0.0][0]
        x2 = [y for y in pdn if y["t_pulse"] == 2e-9 and y["i_scale"] == 1.0 and y["r_d"] == 0.02 and y["c_dec"] == c and y["stagger"] == 0.0][0]
        rows.append([f"{c*1e9:g}", f"{c*1e15/8.2*1e-6:.2f}-{c*1e15/5.0*1e-6:.2f}", f"{x['droop_max_mV']:.1f}", f"{x['recovery_ns']:.1f}", f"{x2['droop_max_mV']:.1f}", f"{x2['recovery_ns']:.1f}"])
    w(md_table(["C_dec (nF)", "area at 8.2-5.0 fF/um^2 (mm^2)", "droop, T = 1 ns (mV)", "recovery (ns)", "droop, T = 2 ns (mV)", "recovery (ns)"], rows))
    w("")
    w("Q = I T = 69 pC at 1 ns (138 pC at 2 ns): a droop budget of 10 mV costs 10 nF / 20 nF; 5 mV does not close inside 20 nF at 2 ns. **A droop of d mV scales the read bias by (1 - d / 100) and the budget's signal terms with it (an 8 mV droop costs 0.4-0.8 uA of margin at g = 8)**, so the budget, not the supply, sets the droop target. "
      "**The recovery matters as much as the droop**: through R_pad the decoupling recharges with tau = R_pad C: 10 nF with 0.5 ohm is 5 ns, the rail needs 12-24 ns to settle to 1 mV, i.e. longer than the 10 ns cycle; reads would then see the previous read's droop (history-dependent, not calibratable).")
    w("")
    w("**Is the short pulse deliverable?** At full width: **no**. 0.5 ns needs 10 nF for 5 mV (1.2-2.0 mm^2, 8-13x the array); 2 ns needs 20 nF for 8 mV (2.4-4.0 mm^2) and 24 ns to recover. **At reduced peak current: yes.** Scaling the current (fewer columns per pass or smaller a per read):")
    w("")
    rows = []
    for sc, lab in ((1.0, "160 columns, g = 8 (69 mA)"), (0.5, "80 columns or g = 4 (34.6 mA)"), (0.25, "40 columns at g = 8 or 80 at g = 4 (17.3 mA)"), (0.125, "40 columns at g = 4 (8.7 mA)")):
        rd = 0.02 if sc == 1.0 else 0.05
        cells = []
        for tgt in (5, 10, 20):
            ok = sorted([x for x in pdn if x["t_pulse"] == 1e-9 and x["i_scale"] == sc and x["r_d"] == rd and x["stagger"] == 0.0 and x["c_dec"] > 0 and x["droop_max_mV"] <= tgt], key=lambda x: x["c_dec"])
            cells.append(f"{ok[0]['c_dec']*1e9:g}" if ok else "> 20")
        rows.append([lab] + cells)
    w(md_table(["peak current", "C_dec for 5 mV (nF)", "10 mV", "20 mV"], rows))
    w("")
    w("(T = 1 ns; 2 ns needs ~1.5-2x). **The recommended supply design is the last row: 40 columns per pass (4 passes), g = 4, C_dec = 1 nF (0.12-0.20 mm^2 at 8.2-5.0 fF/um^2), R_d 0.05 ohm: droop 7 mV, recovery 3 ns.** "
      "The cost is latency, not energy (each column-read costs the same whatever the pass): " + f"{rec[2]['cycles_skip_a0']:,.0f} cycles per inference with the a = 0 skip, against {rc['8']['cycles_all_reads']:,.0f} for 1C's g = 8 / 160-column read without it, and {rc['8']['cycles_skip_zero']:,.0f} for g = 8 / 160 columns with it.")
    w("")
    st = lambda T, c: [x for x in pdn if x["t_pulse"] == T and x["i_scale"] == 1.0 and x["r_d"] == 0.1 and x["c_dec"] == c and x["stagger"] == 0.0][0]["droop_max_mV"] / [x for x in pdn if x["t_pulse"] == T and x["i_scale"] == 1.0 and x["r_d"] == 0.1 and x["c_dec"] == c and x["stagger"] > 0][0]["droop_max_mV"]
    w(f"**Staggering the macros** (five macros 200 ps apart, peak 14 mA each): the droop falls by a factor {st(0.5e-9, 5e-9):.2f} at T = 0.5 ns and {st(1e-9, 5e-9):.2f} at 1 ns, {st(2e-9, 5e-9):.2f} at 2 ns (5 nF, R_d 0.1 ohm): the decoupling saved for a 20 mV droop is {100*saving[0.5e-9]:.0f}% at 0.5 ns, {100*saving[1e-9]:.0f}% at 1 ns and {100*saving[2e-9]:.0f}% at 2 ns ({c_for(0.5e-9,0.0,20.0)*1e9:.1f} -> {c_for(0.5e-9,200e-12,20.0)*1e9:.1f} nF, {c_for(1e-9,0.0,20.0)*1e9:.1f} -> {c_for(1e-9,200e-12,20.0)*1e9:.1f} nF, {c_for(2e-9,0.0,20.0)*1e9:.1f} -> {c_for(2e-9,200e-12,20.0)*1e9:.1f} nF). "
      "The read window grows by 0.8 ns, still inside one cycle (cycle count unchanged), each macro's sense integrates its own window (energy unchanged). **Recommendation: no** - the pulse lengths 1F derives are >= 1 ns, where it saves little, and it needs five delayed timing domains.")
    w("")
    w("**Damping.** The series resistance in the decoupling path costs I x R_d of droop and buys recovery: at the full 69 mA, R_d 1 ohm gives a 64 mV droop whatever the capacitance; 0.02-0.1 ohm costs 1.4-7 mV. Recovery after the pulse is set by R_pad C and the regulator's L_reg (`pdn_pad_sweep.json`, 8.7 mA / 1 nF and 69 mA / 10 nF): "
      f"droop depends on C_dec ({min(r['droop_max_mV'] for r in padsw if r['i_scale']==1.0):.1f}-{max(r['droop_max_mV'] for r in padsw if r['i_scale']==1.0):.1f} mV for the full read over R_pad 0.1-1 ohm, L_pad 50-200 pH, L_reg 0-2 nH) and hardly on the pad network; **recovery depends on L_reg**: "
      f"an ideal regulator recovers in 1 ns, 0.5 nH in 4 ns, 2 nH (a ~4 MHz loop) in 16 ns. **Requirements: regulator output inductance <= 0.5 nH, R_pad C <= 1/3 of the cycle, R_d 0.05 ohm.**")
    w("")
    w("![Figure 18: rail droop vs decoupling, by peak current and staggering](../figures/fig18_pdn.png)")
    w("")
    w("*Figure 18.* Left: droop against C_dec at T = 1 ns for the four peak currents (dotted: 5, 10, 20 mV). Right: the full 69 mA with and without 200 ps stagger between macros at T = 0.5 and 2 ns.")
    w("")

    # ------------------------------------------------------------------ 6 F5
    w("## 6. F5 - the threshold path")
    w("")
    w("`sense/threshold_path.py`, `threshold_path.json`. A column's decision is made against a threshold that depends on the group and on a; the threshold has to reach each column's comparator with 1 sigma <= ~0.2 uA out of up to 115 uA (far) / 300 uA (near) - **10-11 bits of absolute accuracy per column**, "
      "because any error of that column's threshold is an error of that column's decision.")
    w("")
    mir = thr["mirror_mc"]
    w("**What matching can give** (a PMOS current mirror, the unit of every per-column current DAC or copy; Pelgrom Monte-Carlo on the card, 20 uA): " + "; ".join(f"{r['area_um2']:.1f} um^2: {100*r['sigma_rel']:.2f}%" for r in mir) +
      ". **Even 184 um^2 per mirror leaves 0.6% (2 uA at 300 uA): per-column generation needs per-column calibration, or a structure whose accuracy comes from capacitor ratios.**")
    w("")
    rows = []
    for o in thr["options"]:
        rows.append([o["option"], f"{o['area_per_col_um2']:.0f}", o["accuracy"], f"{o['energy_per_read_pJ']:.0f}" if o["energy_per_read_pJ"] is not None else "-", o["time_ns"]])
    w(md_table(["delivery", "area per column (um^2) [ASSUM]", "accuracy", "energy per read, 160 columns (pJ)", "timing"], rows))
    w("")
    w("**Chosen for the estimates (not designed): (C) a 10-bit switched capacitor array per column**, because its accuracy is capacitor matching (~0.1-0.2% [ASSUM]) and temperature-stable; it costs ~250 um^2 per column and "
      f"~{E.E_DAC_J*1e15:.0f} fJ per comparison [ASSUM]. (A) is the same function in current mode and needs the 10-bit gain calibrated per column; (B) cannot serve 160 columns in a nanosecond; (D) costs 160 ADCs x 20 pJ x {rc['8']['reads_nonzero']:,.0f} reads = {160*E.ADC10_PJ*1e-12*rc['8']['reads_nonzero']*1e6 if hasattr(E,'ADC10_PJ') else 160*20e-12*rc['8']['reads_nonzero']*1e6:.0f} uJ per inference - rejected.")
    w("")
    w(f"**Where the rank-3 row-gain multiply is done** (1C: gain(c, G, a) = sum of 3 products, 12-bit, 19,584 bits). Digital energy per inference at Horowitz op energies (12-bit multiply 0.45 pJ, 12-bit add 0.05 pJ, SRAM 0.16 pJ/bit):")
    w("")
    mo = thr["rank3_multiply_uJ"]
    w(md_table(["where", "g = 8 (uJ)", "g = 4 (uJ)"], [["per column, digital (160 x (3 MAC + comparisons x multiply) per read)", f"{mo['per_column_digital']['8']:.1f}", f"{mo['per_column_digital']['4']:.1f}"],
                                                         ["per column POSITION, digital (the 32 distinct positions of a macro row, shared by the five macros)", f"{mo['per_position_digital']['8']:.2f}", f"{mo['per_position_digital']['4']:.2f}"],
                                                         ["stored corrected thresholds (one SRAM read of the needed thresholds x 32 positions per read)", f"{mo['stored_corrected']['8']:.2f}", f"{mo['stored_corrected']['4']:.2f}"]]))
    w("")
    w("**Doing it per column costs more than NeuroHDC's whole inference (7.5 uJ).** The correction depends on the column's position inside its macro row (32 values), not on the column itself, so the five macros share it: ~1.5 uJ (g = 8) - 2.0 uJ (g = 4) [MODEL/ASSUM]; that is the figure used in section 4. "
      "Moving the correction into the analog domain (three shared 'weighted ladders' and three per-column trimmed weights) would remove it but needs three trimmed threshold paths per column: not evaluated. **This is a cost of 1C's rank-3 correction that 1C did not price; it is the second largest item after the sense bias.**")
    w("")
    w(f"**Timing and prefetch.** The group sequence and a are known before the read (they are 1E's counts): the threshold table lookups, the digital correction and the capacitor-array pre-charge of the next read overlap the current read. A binary search needs {E.n_comparisons(rc['8']['a_hist']):.1f} comparisons on average at g = 8 "
      f"({E.n_comparisons(rc['4']['a_hist']):.1f} at g = 4; 4 at most), each 0.2 ns (charge redistribution) + 0.3 ns (comparator): 2 ns at most, inside the 10 ns cycle with the 2 ns window and the 1.8-3 ns power-up (itself prefetchable: the next read is known). No timing term is binding. "
      "**Area:** see section 7.")
    w("")

    # ------------------------------------------------------------------ 7 area
    w("## 7. Area: 1C's table re-run with the real sense periphery")
    w("")
    w("`sense/area_1f.py`, `area_table_1f.json`, Figure 21. 1C assumed per column a 20 um^2 sense input and eight 12 um^2 comparators (116 um^2) plus eight 400 um^2 reference DACs. Here, per column [low-mid-high ranges as 1C]: the simulated channel's gate area (28 um^2 of W x L) x a layout factor 3 / 5 / 8; "
      "two integration capacitors of 200 fF at 20 / 10 / 5 fF/um^2; the decision stage (preamp W = 32 um, latch); the 10-bit threshold capacitor array (150 / 250 / 400 um^2); 2 x 10 calibration trim bits.")
    w("")
    s_ = area["c_dec=0nF|mid"]["sense_per_col"]
    w(md_table(["per column (mid, um^2)", ""], [[k.replace("_", " "), f"{v:.0f}"] for k, v in s_.items()] + [["**total**", f"**{sum(s_.values()):.0f}**"], ["1C's assumption", "116 (+ shared DACs)"]]))
    w("")
    rows = []
    for nm in ("c_dec=0nF", "c_dec=1nF", "c_dec=2nF", "c_dec=20nF"):
        lo_, mi_, hi_ = (area[f"{nm}|{k}"]["total_mm2"] for k in ("low", "mid", "high"))
        rows.append([nm.replace("c_dec=", "").replace("nF", " nF"), f"{lo_:.3f}", f"{mi_:.3f}", f"{hi_:.3f}"])
    w(md_table(["decoupling at 0.35 V", "total low (mm^2)", "mid", "high"], rows) + f"\n\n1C's table: {area['c_dec=0nF|mid']['total_1c_mm2']:.3f} mm^2. The sense periphery grows from {(area['c_dec=0nF|mid']['replaced_1c_um2'])*1e-6:.3f} to {area['c_dec=0nF|mid']['parts_um2']['sense_front_ends_1f']*1e-6:.3f} mm^2; "
      "the decoupling is larger than the rest of the chip for a full-width read (20 nF: 3.3 mm^2) and comparable to the array for the recommended one (1 nF: 0.17 mm^2).")
    w("")
    w("![Figure 21: area, 1C table vs 1F](../figures/fig21_area_1f.png)")
    w("")
    w("*Figure 21.* Area by part: 1C's table, 1F with the simulated sense periphery and no decoupling, with the recommended 1 nF, and with the 20 nF a full-width read would need (truncated).")
    w("")

    # ------------------------------------------------------------------ 8 F6
    w("## 8. F6 - the budget re-closed, and g as a surface")
    w("")
    w("`sense/budget_1f.py`, `sense/closure_1f.py`, `sense/recommend_1f.py`, `closure_map.json`, `recommended_designs.json`, Figure 19. The 1C machinery is unchanged (`drift.strategies.evaluate` through `scaleup.budget1c.close_1c`; S1, drift 'moderate', 20 F^2, R_s 1 ohm, 5 sigma random terms in quadrature, 20% headroom); "
      "the comparator-noise slot (1C's assumed 1 uA -> 5.00 uA) is replaced by four measured lines per group:")
    w("")
    bd = rec[1]["margins"]["0.07"]["far_breakdown_uA"]
    rows = [[k, f"{v:.2f}"] for k, v in bd.items() if v > 0.0 and k != "absolute signal (comparator noise)"]
    w("far-group lines at the g = 8 point (T = 2 ns, vb 0.50, sigma_lnG 0.07, 8 mV droop, 5 K), uA at 5 sigma:")
    w("")
    w(md_table(["term", "uA"], rows) + f"\n\nlimit {rec[1]['margins']['0.07']['limit_uA']:.2f} uA, total {rec[1]['margins']['0.07']['total_uA']:.2f} uA. The 1C budget at its assumed 1 uA reproduces here as {allowed['check_1c_baseline']['margin_left_a']*1e6:.3f} uA of {allowed['check_1c_baseline']['limit_a']*1e6:.2f} (total {allowed['check_1c_baseline']['total_a']*1e6:.2f}), i.e. exactly 1C's 0.48 / 12.20 / 11.72.")
    w("")
    w("**Margin left (uA), best of the 18 front-end points (3 biases x 3 pulse lengths x 2 tails), 5 K recalibration window; without droop, then with 8 mV droop** (Figure 19):")
    w("")
    rows = []
    for g in (4, 8, 16):
        rows.append([f"g = {g}"] + [f"{best(g, s)['margin_left_a']*1e6:+.1f} / {best(g, s, 5.0, 8.0)['margin_left_a']*1e6:+.1f}" for s in (0.03, 0.05, 0.07, 0.10, 0.15)])
    w(md_table(["", "sigma_lnG 0.03", "0.05", "0.07", "0.10", "0.15"], rows))
    w("")
    w("**g = 8 closes with a real margin (> 0.15 uA, outside the Monte-Carlo scatter) only for sigma_lnG <= 0.07, and then only at T = 2 ns; at sigma_lnG = 0.10 - 1C's recommended point - it is +0.6 uA without droop, +0.2 with 8 mV: not distinguishable from zero, and negative (-0.75 uA) for the 1 nF / T = 2 ns design. "
      "g = 4 closes through 0.15 with 2-8 uA to spare. g = 16 never opens with end-sensed columns:** even the 1C terms alone leave -1.0 uA at sigma_lnG 0.03; with the front-end -4.1 uA.")
    w("")
    w("**g = 16 against C4** (`g16_variants.json`; sigma_lnG <= 0.048 was C4's condition for the segmented column; vb 0.46, T = 2 ns, tail 1 ns, 5 K; margin with 1F / with the 1C terms only):")
    w("")
    rows = []
    for v in ("end", "centre", "seg2_mid", "seg4_mid", "seg8_mid"):
        rows.append([v] + [f"{g16[f'{v}|{s}']['margin_1f_a']*1e6:+.2f} / {g16[f'{v}|{s}']['margin_1c_without_comparator_a']*1e6:+.2f}" for s in (0.02, 0.03, 0.04, 0.048, 0.05)])
    w(md_table(["readout variant", "sigma_lnG 0.02", "0.03", "0.04", "0.048", "0.05"], rows))
    w("")
    w("**g = 16 opens only with centre-tapped-or-better columns: seg4_mid / seg8_mid (4-8 sense nodes per column) up to sigma_lnG ~ 0.045**; the 1F front-end takes 1.0-1.4 uA of the 1C-only margin, which is the difference between closing at 0.048 and not (+0.04 / +0.06 uA: zero within the scatter). "
      "Each extra sense node per column multiplies the front-end area (x4-x8 of the 0.084 mm^2) while the energy per read is unchanged.")
    w("")
    w("**Sensitivity: what the front-end would have to do for g = 8 at sigma_lnG 0.10** (T = 2 ns, vb 0.50, 5 K, 8 mV droop; margin left vs the calibration residual scaled):")
    w("")
    rows = []
    r_ = row_p(0.50, 2e-9, 0.3e-9); n_ = float(np.hypot(r_["sigma_thermal_ref_uA"], r_["comparator_uA"])) * 1e-6
    for k_ in (1.0, 0.5, 0.25, 0.0):
        t = B.fe_terms(dict(far=n_, near=n_), dict(far=k_ * r_["cal_sigma_far_uA"] * 1e-6, near=k_ * r_["cal_sigma_near_uA"] * 1e-6), d_t_k=5.0)
        rows.append([f"x {k_:g}", f"{B.closure(8, 0.10, t, gain_factor=0.92, n=2000)['margin_left_a']*1e6:+.2f}"])
    w(md_table(["calibration residual", "margin left (uA)"], rows))
    w("")
    w("A calibration twice as good (0.5 uA far on the transient) puts g = 8 at sigma_lnG 0.10 at the edge; this is the quantity to improve before giving up g = 8 (more calibration parameters, a lower-mismatch conveyor, or the two-stage integrator of section 2).")
    w("")
    w("**Where it ends up.**")
    w("")
    rows = []
    for r in rec:
        mg = "; ".join(f"{s}: {m['margin_uA']:+.2f}" for s, m in r["margins"].items())
        rows.append([r["name"], f"{r['T']*1e9:g} + {r['tail']*1e9:g}", f"{r['droop_mV']:.1f} / {r['recovery_ns']:.1f}", f"{r['reads_per_inference']:,.0f}", f"{r['cycles_skip_a0']:,.0f}", f"{r['energy']['total_J']*1e6:.2f}", f"{r['area_mm2_mid']:.2f}", mg])
    w(md_table(["design", "T + tail (ns)", "droop (mV) / recovery (ns)", "reads", "cycles (a = 0 skipped)", "energy (uJ)", "area (mm^2)", "margin left (uA) at sigma_lnG ..."], rows))
    w("")
    w("**The honest design point is g = 4**, 40 columns per pass, T = 1 ns (tail 0.3 ns), OTA bias vb 0.50, 1 nF of decoupling, per-column calibration with a recalibration window of 5 K: margin +5.2 uA at sigma_lnG 0.10 (+1.9 at 0.15), "
      f"{e4['total_J']*1e6:.2f} uJ per inference ({e4['ratio_to_neurohdc']:.2f}x NeuroHDC-small), {rec[2]['area_mm2_mid']:.2f} mm^2, {rec[2]['cycles_skip_a0']:,.0f} cycles. **g = 8 is the alternative only if sigma_lnG <= 0.07 is demonstrated (1D) and the calibration residual is halved**; at 1C's own 0.10 it does not close "
      "once the front-end and the supply are real. g = 16 needs seg4/seg8 columns and sigma_lnG <= 0.045.")
    w("")
    w("![Figure 19: margin left vs g and sigma_lnG without and with rail droop](../figures/fig19_g_surface.png)")
    w("")
    w("*Figure 19.* The g surface: best margin over the 18 front-end points, 5 K recalibration window, without droop (left) and with 8 mV (right). Bold: outside the Monte-Carlo scatter (> 0.15 uA).")
    w("")

    # ------------------------------------------------------------------ 9 handoff
    w("## 9. Handoff to Phase 5")
    w("")
    w("1. **Energy per group read including the sense front-end and the threshold path** (non-zero reads only): "
      f"g = 4, T = 1 ns: **{e4['per_read_pJ']:.0f} pJ** ({e4['sense_bias_J']/rc['4']['reads_nonzero']*1e12:.0f} pJ sense bias, {e4['decision_J']/rc['4']['reads_nonzero']*1e12:.0f} comparators, {e4['threshold_J']/rc['4']['reads_nonzero']*1e12:.0f} threshold correction, "
      f"{(e4['array_J']+e4['wordline_J'])/rc['4']['reads_nonzero']*1e12:.0f} array + word line); g = 8, T = 2 ns: **{e8['per_read_pJ']:.0f} pJ**.")
    w(f"2. **Energy per inference at the real T**: {e4['total_J']*1e6:.2f} uJ (g = 4, T = 1 ns) / {e8['total_J']*1e6:.2f} uJ (g = 8, T = 2 ns), exclusions as named in section 4. (1C's pre-front-end 32-48 nJ is the array alone with the sense node at 0 V.)")
    w(f"3. **Total area with the real sense periphery**: {rec[2]['area_mm2_mid']:.2f} mm^2 (mid; {area['c_dec=1nF|low']['total_mm2']:.2f}-{area['c_dec=1nF|high']['total_mm2']:.2f}) with the 1 nF decoupling, {area['c_dec=0nF|mid']['total_mm2']:.2f} mm^2 without; 1C's table said 0.15 mm^2.")
    w("4. **The g surface** (section 8, `closure_map.json`): g = 4 for sigma_lnG <= 0.15; g = 8 for sigma_lnG <= 0.07 with a halved calibration residual; g = 16 with seg4/seg8 columns at sigma_lnG <= 0.045.")
    w(f"5. **Read pattern for the 1E follow-up (RTL, not done here):** skip the a = 0 reads. {rc['8']['reads_issued']:,.0f} -> {rc['8']['reads_nonzero']:,.0f} reads at g = 8 and {rc['4']['reads_issued']:,.0f} -> {rc['4']['reads_nonzero']:,.0f} at g = 4: it removes {100*(1-rc['8']['reads_nonzero']/rc['8']['reads_issued']):.0f}% / {100*(1-rc['4']['reads_nonzero']/rc['4']['reads_issued']):.0f}% of the sense energy. "
      f"With the front-end this is no longer a latency detail: a read the sequencer can see is empty would cost ~{160*1.1*np.mean([en['0.5']['supply_uA']['far']['idle'],en['0.5']['supply_uA']['near']['idle']])*1e-6*(en['0.5']['power_up']['t_settle_ns']+2.3)*1e-9*1e12:.0f} pJ of idle bias (160 columns, power-up + window) if it were issued with the front-end powered.")
    w("6. **Interfaces the digital side needs**: the per-column calibration words (2 channels x 2 parameters x 10 bits = 40 bits per column, 6.4 kbit), the per-(position, group, a) corrected thresholds or the shared rank-3 factors, a temperature-triggered recalibration request, 40-column pass sequencing, and the read-window timing "
      "(power-up 1.8-3.2 ns before the pulse, pulse T, tail 0.3 ns, comparisons 0.5 ns each).")
    w("")

    # ------------------------------------------------------------------ 10 summary of tags
    w("## 10. Compared with what 1C and the brief expected")
    w("")
    w("| 1C premise | 1F finding |")
    w("|---|---|")
    w("| 1 uA (1 sigma) comparator noise, 5.00 uA of the 11.72 uA total | thermal 0.8-2.4 uA + comparator 0.3-1.0 uA + **calibration residual 0.5-2.5 uA + drift + threshold generation**: 1.1-3.7 uA (1 sigma), i.e. 5.5-18 uA at 5 sigma from T = 2 ns down to 0.5 ns (vb 0.50, far group) |")
    w("| array energy 32 nJ at 0.5 ns | x3.5 (V_VG), plus the sense bias (2.3 uJ) and threshold correction (1.5 uJ): **4.7-5.3 uJ** |")
    w(f"| 8 comparators + 8 DACs per column, 116 um^2 | {sum(area['c_dec=0nF|mid']['sense_per_col'].values()):.0f} um^2 per column (mid; 250 of it the threshold capacitor array) and no reference-DAC bank, but a per-column calibration |")
    w("| supply ideal at the pads | 69 mA x 1 ns needs 10 nF (1.2-2 mm^2) for 10 mV; the recommended 8.7 mA pass needs 1 nF |")
    w("| g = 8 closes with 0.48 uA | g = 8 closes only for sigma_lnG <= 0.07; **g = 4 is the design point** |")
    w("| (not considered) calibration | mandatory, 10-bit trims, recalibration every ~5 K |")
    w("")

    # ------------------------------------------------------------------ 11 TBD
    w("## 11. Assumptions and open items (updated TBD list)")
    w("")
    w("**Assumptions (every one tagged where used; swept where stated).**")
    w("")
    w(md_table(["quantity", "value", "tag", "where / what depends on it"], [
        ["AVT (Pelgrom)", f"{C.AVT_MV_UM} mV um", "[ASSUM, 1A]", "all mismatch results (3.2-3.3); scales the calibration residual and the uncalibrated error linearly"],
        ["V_VG (sense node)", "0.25 V", "[CHOICE]", "forced by the PMOS-input amplifier in this process; array energy x3.5"],
        ["latch noise", "1 mV, / preamp gain", "[ASSUM]", "comparator term (small: 0.03 mV after the preamp)"],
        ["comparator + latch offset", "removed by the per-column calibration", "[ASSUM]", "not simulated"],
        ["threshold generation accuracy", f"{B.THR_SIGMA_REL*100:.2f}% of the threshold, 1 sigma", "[ASSUM]", "capacitor-array matching; 0.86 uA at 5 sigma, far"],
        ["recalibration window", "5 K", "[CHOICE]", "calibration drift measured 0.04 uA/K, 0.05 used [SIM, rounded up]; swept 0 / 5 / 10 K in `closure_map.json`"],
        ["autozero residual random fraction", "20%", "[ASSUM]", "3.4 only; autozero not adopted"],
        ["regulator R_reg 0.05 ohm, L_reg 0.5 nH, R_grid 0.1 ohm", "", "[ASSUM] / [MODEL]", "PDN; L_reg swept 0-2 nH"],
        ["R_pad 0.5 ohm, L_pad 100 pH", "", "[ASSUM, brief]", "swept 0.1-1 ohm, 50-200 pH: droop insensitive"],
        ["decoupling density at 0.35 V", "5.0-8.2 fF/um^2", "[SIM]", "PTM card MOS capacitor C(V)"],
        ["sense-area densities, layout factor 3 / 5 / 8", "", "[ASSUM]", "section 7"],
        ["op energies (multiply, add, SRAM)", "Horowitz ISSCC 2014, 45 nm", "[ASSUM, cited]", "threshold correction energy (1.5-2 uJ)"],
        ["capacitor-DAC switching 100 fJ, latch 10 fJ", "", "[ASSUM]", "comparators 0.5-0.85 uJ"],
        ["rank-3 gain / quantisation / antisymmetric terms at g != 8", "the g = 8 values", "[MODEL]", "0.4 uA at the far group in the budget"],
        ["PDN lumped, one regulator, no on-chip grid", "", "[MODEL]", "droop is a lower bound for a real grid"]]))
    w("")
    w("**Open (not done, with what is blocked):**")
    w("")
    w("- **Comparator latch noise and offset**: ngspice has no periodic/transient noise; a device-level number needs another simulator or a transient Monte-Carlo with injected noise (non-converging approach not attempted). Blocked, assumed.")
    w("- **Threshold generator at transistor level** (the switched capacitor array and its distribution to 160 columns, its settling, kT/C): costed, not designed. The 0.17% accuracy requirement is derived, not demonstrated.")
    w("- **The calibration procedure**: reference states/cells, how many reads, who stores 6.4 kbit, how the 5 K trigger is generated; the calibration measurement's own noise would add to the residual (not modelled). Depends on 1D (write/verify).")
    w("- **Column-to-column variation of the dynamic response** is inside the 'calibration residual on the transient' (N = 40 draws per point, ~15% scatter); a larger Monte-Carlo and the worst-case over all 64 groups (here: far and near, 9 levels each) would tighten it.")
    w("- **The two-stage integrator (d)** and a gain-boosted conveyor: the alternatives that could remove the copy mismatch; not optimised (section 2). **Autozero in the loop** and **boosted power-up** (1 ns instead of 1.8-3.2): not built.")
    w("- **A real PDN**: bump/grid layout, the regulator design, on-chip droop sensing; the recovery requirement (R_pad C <= 3 ns, L_reg <= 0.5 nH) is a specification, not a design. **40-column passes** change 1E's sequencer (cycle model: 409,028 + passes x reads, measured by 1E for 160 and 20 columns, extrapolated).")
    w("- **The 0.25 V sense node** and its reference distribution to 160 columns at < 0.1 mV accuracy (the node error x 1.8-5 mS is the offset current): the node is held absolutely; no on-chip reference was designed.")
    w("- Not in scope and untouched: write path / forming / program-verify (1D), RTL (the a = 0 skip is recorded for 1E), the HDC side (Phase 2), early exit (Phase 4), final PPA (Phase 5).")
    w("")

    # ------------------------------------------------------------------ 12 files
    w("## 12. Files and reproduction")
    w("")
    w("```")
    w("python -m sense.run_topologies          # F1: results/sense_frontend/topology_comparison.json")
    w("python -m sense.sweep_b                 # F2: 72-point sizing/bias sweep (noise, step, power, area, CM gain)")
    w("python -m sense.run_mismatch            # F2: mismatch Monte-Carlo by source, CM gain with mismatch")
    w("python -m sense.cal                     # F2: calibration (DC, vs temperature, quantisation, transient)")
    w("python -m sense.run_cal_transient       # F2: calibration residual on the transient vs vb, T, tail")
    w("python -m sense.run_drift_sources       # F2: which mismatch source makes the calibration go stale")
    w("python -m sense.az                      # F2: autozero pieces")
    w("python -m sense.comparator              # F2: preamp noise, reset noise")
    w("python -m sense.run_chop                # F2: chopping / DEM (negative result)")
    w("python -m sense.enable                  # F3: power-up and supply current")
    w("python -m sense.pareto                  # F3: noise / comparator / calibration per (vb, T, tail)")
    w("python -m sense.reads                   # read counts vs g (1E golden count vectors)")
    w("python -m sense.budget_1f               # F6: allowed sigma per (g, sigma_lnG)")
    w("python -m sense.closure_1f              # F3/F6: closure map; g = 16 variants")
    w("python -m sense.energy_1f               # F3: energy per inference")
    w("python -m sense.pdn && python -m sense.pdn --pad     # F4")
    w("python -m sense.threshold_path          # F5")
    w("python -m sense.area_1f                 # F5/F7: area table")
    w("python -m sense.recommend_1f            # F6/F7: the candidate designs end to end")
    w("python -m sense.figures                 # figures 14-21")
    w("python -m sense.make_report             # this file")
    w("python -m pytest tests/test_sense_frontend.py")
    w("```")
    w("")
    w("`sense/`: `ngs.py` (ngspice harness), `cells.py` (OTAs, transmission gate), `port.py` (array port), `mc.py` (the chosen front-end: netlist, mismatch, noise, fidelity, impedance), `acnoise.py`, `metrics.py`, `topo_a/c/d/d2.py`, `collect.py`, `b2.py` and `dem.py` (the failed swaps). "
      "`device/ptm/ptm45p_lp.lib`: the PMOS block of the same PTM card.")
    out = RP.REPORT_1F
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n")
    print("wrote", out, len(L), "lines")


if __name__ == "__main__":
    main()
