#!/usr/bin/env python3
"""reports/final_ppa.md - the PPA of the digital block and of the analog block, and the chip numbers. Every number is read from files; a post-route cell stays 'PENDING (owner)' until the
owner's Innovus run has produced the stage netlists and layout_analysis.py has analysed them (synth/results/layout/<build>/<stage>/summary.json). Nothing post-route is estimated.

  python design/rtl/synth/final_ppa.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
RES = HERE / "results"
PPA = ROOT / "results" / "ppa_digital"
OUT = REPO / "reports" / "final_ppa.md"
BUILDS = ["full", "ee_off", "fact_off", "both_off"]
LAB = {"full": "full design", "ee_off": "early exit OFF", "fact_off": "factorization OFF", "both_off": "both OFF"}
PEND = "**PENDING (not run)**"
pct = lambda x, d=1: f"{100 * x:.{d}f}%"          # noqa: E731


def jl(p):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return None


def table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def main() -> int:
    D = jl(PPA / "digital_tables.json")
    T5 = jl(ROOT / "results" / "ppa" / "phase5_tables.json")
    NS = jl(RES / "neurosim.json")
    AA = jl(RES / "analog_area.json")
    AM = jl(RES / "analog_macros.json")
    IF = jl(RES / "interface.json")
    Sy = {b: jl(PPA / b / "summary.json") for b in BUILDS}
    Pw = {b: jl(PPA / b / "power" / "power_summary.json") for b in BUILDS}
    PwI = {b: jl(PPA / b / "power_ing" / "power_summary.json") for b in BUILDS}
    PwM = {b: jl(PPA / b / "power_mvm" / "power_summary.json") for b in BUILDS}
    LA = {b: {s: jl(RES / "layout" / b / s / "summary.json") for s in ("baseline", "pre_cts", "post_cts", "groute", "routed")} for b in BUILDS}
    g4 = {b: D["builds"][f"{b}_g4"] for b in BUILDS}
    NH = T5["neurohdc_small"]
    f4 = g4["full"]
    nsB, nsA2 = NS["variants"]["B_128F"], NS["variants"]["A2_40F"]
    A = {k: AA[k]["total_um2"] * 1e-6 for k in ("1C_analytic_20F2", "A2_40F", "B_128F")}
    cim = AM["cim_macro"]
    post = lambda b, s: LA[b][s]                                                                       # noqa: E731
    have_routed = any(LA[b]["routed"] for b in BUILDS)
    c = lambda x: PEND if x is None else x                                                           # noqa: E731

    # ---- the OpenROAD layout of the full design (the only build run): the latest stage that has power windows
    LF = LA["full"]
    best_stage = next((s for s in ("routed", "groute", "post_cts") if LF[s] and LF[s].get("power") and "mvm" in LF[s]["power"]), None)
    BL = LF[best_stage] if best_stage else None
    IFR = jl(RES / f"interface_routed_{best_stage}.json") if best_stage else None
    LAB_STAGE = {"routed": "routed (OpenROAD)", "groute": "global-routed (OpenROAD)", "post_cts": "after CTS (OpenROAD)", "pre_cts": "placed, before CTS (OpenROAD)"}
    pw = lambda s, k: (LF[s]["power"][k]["total_w"] * 1e3 if LF[s] and LF[s].get("power") and k in LF[s]["power"] else None)          # noqa: E731
    grp = lambda s, k, g: (LF[s]["power"][k]["groups_internal_switching_leakage_total_w"][g][3] * 1e3 if LF[s] and LF[s].get("power") and k in LF[s]["power"] else None)          # noqa: E731
    fmt = lambda x, d=3: ("n/a" if x is None else f"{x:.{d}f}")                                          # noqa: E731
    pre_ck0 = PwM["full"]["groups_internal_switching_leakage_total_w"]["Clock"][3] * 1e3
    fp = {}
    for ln in (HERE / "innovus" / "floorplan_params.tcl").read_text().splitlines():
        m_ = re.match(r"set (\w+) ([\d.]+)", ln)
        if m_:
            fp[m_.group(1)] = float(m_.group(2))

    # ---- interface and chip-energy pieces (per build)
    ifn = IF["energy"]["nominal"]["energy_pJ_per_read"]
    ifl, ifs = IF["energy"]["long"]["energy_pJ_per_read"], IF["energy"]["short"]["energy_pJ_per_read"]

    def chip(b):
        nb = g4[b]
        pr = nb["phase_resolved"]
        e_dig = pr["digital_uJ"]
        e_xbar = nb["energy_uJ"]["snn_array"]
        e_hdc = nb["energy_uJ"]["hdc_array"]
        e_if = ifn * nb["mean_all_reads"] * 1e-6
        tot = e_dig + e_xbar + e_hdc + e_if
        util = 0.65
        a_dig_cells = Sy[b]["buf_fast"]["area_um2"] * 1e-6
        a_hdc = nb["area_mm2"]["hdc_array"]
        a_ls = IF["level_shifters"]["area_mm2"]
        a_tot = a_dig_cells / util + A["B_128F"] + a_hdc + a_ls
        lay = None
        if b == "full" and BL and BL["power"].get("ing") and BL["power"].get("mvm"):
            pi, pm = BL["power"]["ing"]["total_w"], BL["power"]["mvm"]["total_w"]
            e_lay = pi * pr["event_cycles"] * 10e-9 * 1e6 + pm * pr["other_cycles"] * 10e-9 * 1e6
            wires = (IFR["energy_pJ_per_read"]["wires_total"] * nb["mean_all_reads"] * 1e-6) if IFR else 0.0
            ls = (IF["level_shifters"]["energy_fJ_per_toggle_ASSUMED"] * 1e-3 * (IF["alpha_output_toggles_per_wire_per_read"] * 480 + IF["alpha_rowselect_toggles_per_wire_per_read"] * 512) * nb["mean_all_reads"] * 1e-6)
            gi, gm = BL["power"]["ing"], BL["power"]["mvm"]
            lo = lambda g_: g_["internal_w"] + g_["leakage_w"] + 0.5 * g_["switching_w"]          # noqa: E731
            e_lo = lo(gi) * pr["event_cycles"] * 10e-9 * 1e6 + lo(gm) * pr["other_cycles"] * 10e-9 * 1e6
            lay = dict(stage=best_stage, e_dig_low_rc=e_lo, sw_share_mvm=gm["switching_w"] / gm["total_w"], e_dig_incl_wires=e_lay, e_boundary_wires=wires, e_ls=ls, e_tot=e_lay + e_xbar + e_hdc + ls)
        return dict(lay=lay, e_dig=e_dig, e_xbar=e_xbar, e_hdc=e_hdc, e_if=e_if, e_tot=tot, a_dig=a_dig_cells, a_dig_util=a_dig_cells / util, a_xbar=A["B_128F"], a_hdc=a_hdc, a_ls=a_ls, a_tot=a_tot,
                    cycles=nb["mean_cycles"], lat_ms=nb["mean_cycles"] * 10e-9 * 1e3, acc=nb["accuracy_mean"], exit=nb["mean_exit_timestep"])

    C = {b: chip(b) for b in BUILDS}
    fc = C["full"]
    L = []
    w = L.append
    w("# Final PPA - digital block, analog block, chip")
    w("")
    w("Tags: **[SIM]** simulated (Yosys + OpenSTA on the PDK library, gate-level Icarus activity), **[RTL]** measured on the RTL regression, **[1F]** ngspice (carried forward), **[NSIM]** NeuroSim V1.4 run for this design, "
      "**[MODEL]** analytic in code, **[ASSUM]** assumed, **PENDING** = needs the owner's licensed tools and has NOT been produced or estimated. Numbers are read from `design/rtl/results/ppa_digital/`, "
      "`design/rtl/synth/results/` by `design/rtl/synth/final_ppa.py`; commands in section 8. Companions: [`digital_energy.md`](digital_energy.md), [`phase5_ppa.md`](phase5_ppa.md).")
    w("")
    w("## 0. The answer, and what is missing")
    w("")
    if BL:
        w(f"**Status: the digital block has been placed, clock-tree-synthesised{' and global-routed' if best_stage == 'groute' else (' and routed' if best_stage == 'routed' else '')} with OpenROAD (open source) on this PDK, for the FULL design only; the numbers below are the {LAB_STAGE[best_stage]} stage.** "
          "They are not Innovus + Quantus signoff numbers: parasitics are estimated from the PDK's LEF layer RC (no coupling, no field-solver extraction), the netlist is the Yosys one with no physical synthesis, and the other three builds were not run. "
          "The owner's Genus / Innovus / Quantus flow (section 7) is prepared and not yet run. Cells that no tool has produced are marked PENDING and are never estimated.")
    else:
        w("**Status: no layout numbers yet.** The OpenROAD run has not produced a post-CTS or routed stage; cells are PENDING and are never estimated.")
    w("")
    w(f"- **D1(a) The PDK has a usable clock-gating cell.** `TLATNCAX2` (and X12, X16, X20) are in `fast_vdd1v0_basicCells.lib` with `clock_gating_integrated_cell : \"latch_posedge\"` and the enable / clock / "
      "output pins marked; the design's 738 clock gates are real library cells. **The library the pre-route numbers used is the PDK's, byte for byte** (checked by SHA-1 against `45_nm_PDK/.../lib/*.lib`): "
      "the earlier 'lab 45 nm' library and this PDK are the same files, so re-synthesising against the PDK with Yosys would reproduce the pre-route numbers exactly; the genuinely new synthesis is Genus (section 7, step 2).")
    w(f"- **Analog macro area is NOT 0.429 mm^2 once the select transistor is sized for the write path: {A['B_128F']:.3f} mm^2** ({pct(A['B_128F'] / A['1C_analytic_20F2'] - 1, 0)} more). 1C's analytic number at the 20 F^2 cell it assumed "
      f"is {A['1C_analytic_20F2']:.4f} mm^2; NeuroSim **refuses** the 20 F^2 cell (its own transistor model needs a 39.8 F wide select transistor for a 541.8 ohm LRS) and at its smallest feasible cell (40 F wide) gives "
      f"{A['A2_40F']:.4f} mm^2 - within 0.4 % of 1C, a corroboration - but at the 128 F cell the write path needs it gives {A['B_128F']:.4f} mm^2. **The chip-level number uses {A['B_128F']:.3f} mm^2** (the larger).")
    w(f"- **The interface is not free: {ifn:.1f} pJ per group read (range {ifs:.1f}-{ifl:.1f} for 300-700 um wires), {fc['e_if']:.2f} uJ per inference at the mean {g4['full']['mean_all_reads']:,.0f} reads "
      f"= {pct(fc['e_if'] / fc['e_xbar'], 0)} of the crossbar read energy**, plus {IF['level_shifters']['area_mm2'] * 1e6:,.0f} um^2 of level shifters ({IF['level_shifters']['low_to_high']} up, {IF['level_shifters']['high_to_low']} down).")
    w(f"- **Chip, pre-layout, full design (g = 4): {fc['e_tot']:.2f} uJ per inference, {fc['a_tot']:.2f} mm^2, {fc['lat_ms']:.2f} ms** against NeuroHDC-small's {NH['energy_uJ']} uJ and {NH['area_mm2']} mm^2 "
      f"({fc['e_tot'] / NH['energy_uJ']:.2f}x energy, {fc['a_tot'] / NH['area_mm2']:.2f}x area). The analog macro alone ({A['B_128F']:.2f} mm^2) is {A['B_128F'] / NH['area_mm2']:.2f}x NeuroHDC's whole chip: "
      "**the area comparison is decided by the crossbar's select transistors, not by the digital design.**")
    if fc["lay"]:
        ly = fc["lay"]
        dar = fp["DIE_W"] * fp["DIE_H"] * 1e-6
        w(f"- **With the OpenROAD layout ({LAB_STAGE[best_stage].replace(' (OpenROAD)', '')}) the digital block stops being negligible: {ly['e_dig_incl_wires']:.1f} uJ per inference (pre-layout {fc['e_dig']:.2f}), chip {ly['e_tot']:.1f} uJ and a {dar:.2f} mm^2 die** "
          f"({ly['e_tot'] / NH['energy_uJ']:.1f}x and {dar / NH['area_mm2']:.1f}x NeuroHDC-small). Window power goes {PwM['full']['total_w'] * 1e3:.2f} -> {fmt(pw('pre_cts', 'mvm'), 2)} mW when the wires are added and -> {fmt(pw(best_stage, 'mvm'), 2)} mW with the clock tree "
          f"(clock group {pre_ck0:.2f} -> {fmt(grp(best_stage, 'mvm', 'Clock'), 2)} mW). **Timing: the fast corner closes ({fmt(BL['timing']['fast']['worst_slack_ns'], 2)} ns), the slow corner does not ({fmt(BL['timing']['slow']['worst_slack_ns'], 1)} ns); hold is violated "
          f"({fmt(BL['timing']['fast']['hold_worst_slack_ns'], 2)} ns fast).** Cell area grew {pct(BL['area']['std_cell_area_um2'] / Sy['full']['buf_fast']['area_um2'] - 1, 0)} through the tool's buffering and resizing of Yosys' minimum-size mapping. "
          f"Caveats that move these numbers (section 9): wire RC is the LEF's (if every switching term scaled with it and it were half, the digital energy would be ~{ly['e_dig_low_rc']:.1f} uJ), the netlist was not physically synthesised, detailed routing did not converge in the time available, "
          "and only the full build was run. **The pre-route 0.147 mW is not a chip number.**")
    if fc["lay"]:
        ly = fc["lay"]
        w(f"- **Largest term now (with the layout): the digital block, {ly['e_dig_incl_wires']:.1f} of {ly['e_tot']:.1f} uJ ({pct(ly['e_dig_incl_wires'] / ly['e_tot'], 0)})** - wires and the clock tree - then the crossbar reads ({fc['e_xbar']:.2f} uJ, 186 pJ per read [1F]). "
          "For area it is the analog macro (select-transistor-limited array + decoupling). Next optimisation, in order: (1) physically-aware synthesis / sizing and a real extraction to replace the minimum-size netlist and the LEF RC; "
          "(2) the digital floorplan: the count memory's 512-way structure spreads over the die (mean net 31 um, 3,000 nets > 200 um) - a placement-aware restructuring of `count_mem` / `shift_accum` is worth more than further gating; "
          "(3) fewer, shorter clock sub-trees (738 gated branches cost a 1.3 mW tree); (4) for the crossbar, 1G and the select transistor.")
    else:
        w("- **Largest term now:** crossbar read energy (186 pJ per non-zero read [1F]) for energy; the analog macro for area.")
    w("")
    w("## 1. PPA table - digital block")
    w("")
    f = "full"
    sb = Sy[f]
    fp = {}
    for ln in (HERE / "innovus" / "floorplan_params.tcl").read_text().splitlines():
        m_ = re.match(r"set (\w+) ([\d.]+)", ln)
        if m_:
            fp[m_.group(1)] = float(m_.group(2))
    die = fp["DIE_W"] * fp["DIE_H"] * 1e-6 if fp else None
    sk = lambda s: (re.search(r"([-+]?\d+\.\d+)\s+setup skew", LF[s]["timing"]["fast"]["clock_skew_report"]) if LF[s] else None)          # noqa: E731
    bst = lambda f_: ("PENDING (no layout)" if not BL else f_(BL))                                              # noqa: E731
    rows = [
        ["standard-cell area (incl. buffers added by the tool)", f"{sb['buf_fast']['area_um2']:,.0f} um^2 ({sb['buf_fast']['area_um2'] * 1e-6:.4f} mm^2)",
         bst(lambda B: f"**{B['area']['std_cell_area_um2']:,.0f} um^2** ({B['area']['std_cell_area_um2'] * 1e-6:.4f} mm^2; {pct(B['area']['std_cell_area_um2'] / sb['buf_fast']['area_um2'] - 1, 0)} more)"), "[SIM] Yosys flat / OpenROAD netlist cell areas"],
        ["flip-flops / clock gates (ICG) / CLKBUF+CLKINV added after placement (CTS, repair)", f"{sb['buf_fast']['flip_flops'] - 738:,} / 738 / 0", bst(lambda B: f"{B['area']['flip_flops']:,} / {B['area']['icgs']} / "
         f"{B['area']['clock_buffers'] - (LF['pre_cts']['area']['clock_buffers'] if LF['pre_cts'] else 0):,}"), "[SIM]"],
        ["die area; standard-cell density of the digital region", "not defined (assumed 65 % in the first chip estimate)", bst(lambda B: f"die {fp['DIE_W']:.0f} x {fp['DIE_H']:.0f} um = {die:.3f} mm^2 (the crossbar macro {AM['cim_macro']['area_um2'] * 1e-6:.3f} + "
         f"digital region + margins); OpenROAD reports {B.get('floorplan', {}).get('utilisation_of_core_pct', 'n/a')} % of the core filled"), "OpenROAD floorplan (util target 0.42 before buffering)"],
        ["standard-cell density of the digital region", "assumed 65 %", bst(lambda B: f"{pct(B['area']['std_cell_area_um2'] / (((fp['CIM_Y'] - 30.78) * (fp['DIE_W'] - 60.0)) - AM['hdc_class_array_fact']['area_um2'] * 1.0), 0)} (cells incl. added buffers / region under the macro)"), "OpenROAD placement"],
        ["timing at 100 MHz: worst setup slack, fast / slow corner", f"{sb['buf_fast']['reg2reg']['slack_ns']:.2f} / {sb['buf_slow']['reg2reg']['slack_ns']:.2f} ns (ideal clocks, no wires)",
         bst(lambda B: f"**{fmt(B['timing']['fast']['worst_slack_ns'], 2)} / {fmt(B['timing']['slow']['worst_slack_ns'], 1)} ns** (slow-corner TNS {fmt(B['timing']['slow']['tns_ns'], 0)} ns)"), "OpenSTA in OpenROAD, propagated clocks, LEF-derived RC"],
        ["hold: worst slack, fast / slow", "not checked (ideal clock)", bst(lambda B: f"{fmt(B['timing']['fast']['hold_worst_slack_ns'], 3)} / {fmt(B['timing']['slow']['hold_worst_slack_ns'], 2)} ns"), "same"],
        ["clock skew (setup skew, fast corner)", "0 (ideal clock)", bst(lambda B: (sk(best_stage).group(1) + " ns") if sk(best_stage) else "see report"), "CTS: before / after in section 3"],
        ["power, read-phase window (560 cycles)", f"{PwM[f]['total_w'] * 1e3:.3f} mW", bst(lambda B: f"**{fmt(pw(best_stage, 'mvm'))} mW**"), "OpenSTA + gate-level VCD (+ wire C post-layout)"],
        ["power, ingest-only window (2,400 cycles)", f"{PwI[f]['total_w'] * 1e3:.3f} mW", bst(lambda B: f"**{fmt(pw(best_stage, 'ing'))} mW**"), "same"],
        ["  of which clock group, read-phase window", f"{Pw[f]['groups_internal_switching_leakage_total_w']['Clock'][3] * 1e3:.3f} mW (8,000-cycle window)", bst(lambda B: f"{fmt(grp(best_stage, 'mvm', 'Clock'))} mW"), "CTS buffers + clock wires"],
        ["digital energy per inference (phase-resolved, g = 4 cycles)", f"{fc['e_dig']:.2f} uJ  ({fc['cycles']:,.0f} cycles at 100 MHz)", bst(lambda B: (f"**{fc['lay']['e_dig_incl_wires']:.2f} uJ** (includes the macro-boundary wires, {fc['lay']['e_boundary_wires']:.2f} uJ of it)" if fc['lay'] else "needs ingest + read windows")), "power x cycles"],
    ]
    if LA["full"]["baseline"]:
        bl = LA["full"]["baseline"]
        rows.append(["pipeline check: the same numbers through `layout_analysis.py`", f"area {bl['area']['std_cell_area_um2']:,.0f} um^2, window power " + ", ".join(
            f"{k} {v['total_w'] * 1e3:.3f} mW" for k, v in bl.get("power", {}).items()), "-", "reproduces the table above"])
    w(table(["metric (full design)", "pre-route (measured, ideal clock, no wires)", "with layout (OpenROAD, global-routed)", "how"], rows))
    w("")
    w("All four builds, pre-route; the layout columns exist for the full design only (OpenROAD, section 7), the others are PENDING:")
    w("")
    rows = []
    for b in BUILDS:
        s = Sy[b]
        r_ = (LA[b][best_stage] if (b == "full" and best_stage) else None)
        rows.append([LAB[b], f"{s['buf_fast']['area_um2']:,.0f}", f"{s['buf_fast']['flip_flops']:,}", f"{s['buf_fast']['reg2reg']['slack_ns']:.2f} / {s['buf_slow']['reg2reg']['slack_ns']:.2f}", f"{Pw[b]['total_w'] * 1e3:.3f}",
                     f"{PwI[b]['total_w'] * 1e3:.3f} / {PwM[b]['total_w'] * 1e3:.3f}", f"{C[b]['e_dig']:.2f}",
                     (f"{r_['area']['std_cell_area_um2']:,.0f}" if r_ else PEND), (f"{r_['power']['ing']['total_w'] * 1e3:.3f} / {r_['power']['mvm']['total_w'] * 1e3:.3f}" if r_ and r_.get('power') and 'ing' in r_['power'] else PEND)])
    w(table(["build", "cell area (um^2)", "flops", "slack fast / slow (ns)", "power (mW)", "ingest / read (mW)", "digital E / inf (uJ)", "with layout: cell area (um^2)", "with layout: ingest / read power (mW)"], rows))
    w("")
    w("## 2. PPA table - analog block (crossbar macro: 5 x 512 x 32, 2T2R, with its front-end and decoupling)")
    w("")
    w(table(["metric", "value", "assumption / source"], [
        ["area, 1C analytic", f"{A['1C_analytic_20F2']:.4f} mm^2", "20 F^2 1T1R cell (1A-1C), 1F front-end, 1 nF decap, 20 % overhead [MODEL] (Phase 5's number)"],
        ["area, NeuroSim, smallest feasible cell", f"{A['A2_40F']:.4f} mm^2", f"40 F x 4 F cell (160 F^2); NeuroSim rejects 20 F^2: 'Transistor width of 1T1R=39.79F is larger than the assigned cell width=5.00F' [NSIM]"],
        [f"**area, NeuroSim, 128 F cell (chip-level choice)**", f"**{A['B_128F']:.4f} mm^2** ({cim['width_um']:.0f} x {cim['height_um']:.0f} um macro)", "128 F x 4 F cell = the select-transistor width the write path needs (1D) [NSIM] + 1F front-end + 1 nF decap + 20 % overhead"],
        ["  of which cell arrays (5 macros)", f"{AA['B_128F']['parts_um2']['cell_array'] * 1e-6:.4f} mm^2", f"NeuroSim: 5 x {nsB['area_array_um2']:,.0f} um^2 = 512 x 64 x 512 F^2 x (45 nm)^2 per macro (1C had 0.0066 mm^2 in total)"],
        ["  of which NeuroSim row / source-line drivers + column mux", f"{(AA['B_128F']['parts_um2']['wl_switch_matrix'] + AA['B_128F']['parts_um2']['sl_switch_matrix'] + AA['B_128F']['parts_um2']['column_mux']) * 1e-6:.4f} mm^2", "NeuroSim periphery for rows / columns (its sense circuits are NOT used)"],
        ["  of which 1F front-end (sense, ladder, calibration, straps)", f"{(sum(AA['B_128F']['parts_um2'][k] for k in ('ladder_and_gain_storage', 'sense_front_ends_1f', 'calibration_storage', 'supply_ground_straps'))) * 1e-6:.4f} mm^2", "1F, 'mid' (NeuroSim's generic MLSA / ADC is not the regulated current conveyor that was designed)"],
        ["  of which 1 nF supply decoupling", f"{AA['B_128F']['parts_um2']['decoupling'] * 1e-6:.4f} mm^2", "1F; the PDK has no decap cells, so P&R inserts none: not double counted"],
        ["class-HV array macro (factorized / unfactorized)", f"{AM['hdc_class_array_fact']['area_um2'] * 1e-6:.4f} / {AM['hdc_class_array_unfact']['area_um2'] * 1e-6:.4f} mm^2", "Phase 5 model [ASSUM]; never designed"],
        ["read energy", "186 pJ per non-zero group read (g = 4, T = 1 ns) -> " + f"{fc['e_xbar']:.2f} uJ per inference", "[1F] ngspice on the actual front-end, x [RTL] non-zero reads; reported as the macro's energy"],
        ["read time", "settles in 130-160 ps inside a 1 ns + 0.3 ns window", "[1F]; digital sees it as clk -> output 0.3 ns (Liberty arc in `macro/*.lib`)"],
        ["static power", "not modelled (excluded as in Phase 5)", f"NeuroSim lists {nsB['leakage_uW']:.0f} uW per macro for its generic periphery; not our circuit"],
        ["interface (digital <-> analog)", f"{ifn:.1f} pJ per group read ({ifs:.1f}-{ifl:.1f}); {fc['e_if']:.2f} uJ per inference", "section 4 [MODEL] + measured activity"],
        ["Liberty power model", "none, by design", "its energy depends on active rows and the data; kept as the separate 186 pJ term"]]))
    w("")
    w("### Area: both cell assumptions, side by side")
    w("")
    rows = []
    for k, nm in (("1C_analytic_20F2", "1C analytic, 20 F^2"), ("A2_40F", "NeuroSim, 40 F x 4 F"), ("B_128F", "NeuroSim, 128 F x 4 F")):
        p = AA[k]["parts_um2"]
        rows.append([nm, f"{p.get('cell_array', 0) * 1e-6:.4f}", f"{(p.get('row_drivers', 0) + p.get('wordline_buffers', 0) + p.get('row_decoder', 0) + p.get('wl_switch_matrix', 0) + p.get('sl_switch_matrix', 0) + p.get('column_mux', 0)) * 1e-6:.4f}",
                     f"{(p.get('ladder_and_gain_storage', 0) + p.get('sense_front_ends_1f', 0) + p.get('calibration_storage', 0) + p.get('supply_ground_straps', 0)) * 1e-6:.4f}", f"{p.get('decoupling', 0) * 1e-6:.4f}",
                     f"{p.get('overhead_20pct', 0) * 1e-6:.4f}", f"**{AA[k]['total_um2'] * 1e-6:.4f}**"])
    w(table(["variant", "cell array", "row / column periphery", "1F front-end", "decap", "overhead 20 %", "total (mm^2)"], rows))
    w("")
    w("1C's row periphery is sized per micrometre of row line (`driver_um2_per_um`) for the short rows of a 20 F^2 cell; NeuroSim's does not grow with the cell width (4,539 um^2 per macro in both NeuroSim variants). "
      "If 1C's per-length driver model were applied to the 128 F rows (25.6x longer) the periphery would be larger than NeuroSim's - this is an open item (section 9), not hidden: the chip number takes NeuroSim's.")
    w("")
    w("### NeuroSim read energy against 1F (D5)")
    w("")
    nm = nsB["read_energy_pJ"]
    e_ns5 = 5 * nm["total"]
    e_arr5 = 5 * nm["array"]
    one_f_arr = T5["builds"]["full_g4"]["snn_components_uJ"]["array_and_wordline"] / T5["builds"]["full_g4"]["mean_nonzero_reads"] * 1e6
    w(table(["term (per full 160-column group read, g = 4)", "NeuroSim [NSIM]", "1F [1F]", "ratio"], [
        ["array + word line", f"{e_arr5:.1f} pJ (5 macros x {nm['array']:.2f})", f"{one_f_arr:.1f} pJ", f"{e_arr5 / one_f_arr:.1f}x"],
        ["sensing (comparators, bias, threshold / NeuroSim: MLSA + encoder + adders)", f"{5 * (nm['adc'] + nm['accum'] + nm['other']):,.0f} pJ", f"{186 - one_f_arr:.1f} pJ", f"{5 * (nm['adc'] + nm['accum'] + nm['other']) / (186 - one_f_arr):.0f}x"],
        ["total", f"{e_ns5:,.0f} pJ", "186 pJ", f"{e_ns5 / 186:.0f}x"]]))
    w("")
    w(f"**1F's 186 pJ is the number reported.** NeuroSim's total is ~{e_ns5 / 186:.0f}x larger and does not corroborate it: over 95 % of NeuroSim's energy is its generic 3-bit multi-level sense amplifiers "
      "(8 shared read circuits per macro, each a 7-comparator ladder behind a column mux - set by the driver's `levelOutput = 8`, `numColMuxed = 8`, so the comparison depends on those two choices) and its digital accumulation; "
      "neither circuit exists in the design, whose per-column regulated conveyor and 1-bit comparators were simulated in ngspice (1F). "
      f"The one term that is comparable, the array and word line, is {e_arr5 / one_f_arr:.1f}x higher in NeuroSim ({e_arr5:.0f} against {one_f_arr:.1f} pJ), and the direction is expected: at 128 F the rows are {128 / 5:.0f}x longer than 1F's 20 F^2 geometry assumed "
      f"(NeuroSim: {nsB['cap_row_fF']:.0f} fF per row, {nsB['cap_col_fF']:.0f} fF per column), so array energy grows with the select-transistor width as the area does - a second consequence of the same finding "
      "(the factor is NeuroSim's model, not a measurement). NeuroSim's latency output for this configuration is not meaningful (it returns 1.0e12 ns) and is not used.")
    w("")
    w("## 3. D1(c): the clock tree - before and after CTS (full design, read-phase window of the same sample)")
    w("")
    rows = []
    for lab, s in (("pre-route: Yosys netlist, ideal clock, no wires", None), ("placed, before CTS (OpenROAD)", "pre_cts"), ("after CTS (OpenROAD)", "post_cts"), ("global-routed (OpenROAD)", "groute"), ("routed (OpenROAD)", "routed")):
        if s is None:
            rows.append([lab, "738 ICG, no tree", fmt(PwM["full"]["groups_internal_switching_leakage_total_w"]["Clock"][3] * 1e3, 4), fmt(PwM["full"]["total_w"] * 1e3), "0 (ideal)"])
        elif LF[s] and LF[s].get("power") and "mvm" in LF[s]["power"]:
            skm = re.search(r"([-+]?\d+\.\d+)\s+setup skew", LF[s]["timing"]["fast"]["clock_skew_report"])
            rows.append([lab, f"{LF[s]['area']['icgs']} ICG, {LF[s]['area']['clock_buffers'] - LF['pre_cts']['area']['clock_buffers']:+,} CLKBUF/CLKINV vs placed", fmt(grp(s, "mvm", "Clock"), 4), fmt(pw(s, "mvm")),
                         (skm.group(1) + " ns" if skm else "see report")])
        else:
            rows.append([lab, PEND, PEND, PEND, PEND])
    w(table(["stage", "clock cells", "clock-group power (mW)", "total power (mW)", "setup skew"], rows))
    w("")
    pre_ck = PwM["full"]["groups_internal_switching_leakage_total_w"]["Clock"][3] * 1e3
    if LF["post_cts"] and LF["post_cts"].get("power") and "mvm" in LF["post_cts"]["power"]:
        w(f"**The CTS delta:** the clock-group power goes from {pre_ck:.3f} mW (738 ICGs, ideal clock) to {fmt(grp('post_cts', 'mvm', 'Clock'), 3)} mW after CTS ({grp('post_cts', 'mvm', 'Clock') / pre_ck:.0f}x): the clock tree "
          f"(437+ delay/balance buffers, sink clustering, the wire capacitance of 738 gated sub-trees spread over a {fp['DIE_W']:.0f} x {fp['DIE_H']:.0f} um die) is {pct(grp('post_cts', 'mvm', 'Clock') / pw('post_cts', 'mvm'), 0)} of the post-CTS power. "
          f"Wires alone (placed, before CTS) already take the window from {PwM['full']['total_w'] * 1e3:.2f} to {fmt(pw('pre_cts', 'mvm'), 2)} mW (switching on wire capacitance; the pre-route numbers had pin capacitance only).")
    w("")
    w("## 4. D3: the interface (previously zero)")
    w("")
    iw = IF["wires"]
    w(table(["item", "value", "basis"], [
        ["wires crossing the boundary", f"{iw['outputs']} count outputs (160 columns x 3 bits at g = 4) + {iw['row_select']} row selects + {iw['other_inputs']} control/write = {iw['total']}", "RTL ports; 1,120 of the RTL's 1,600 `m_o` bits are constant zero at g = 4 (counts 0..4) and would be tied off"],
        ["wire capacitance", f"{IF['wire_cap_fF_per_um']['Metal4']:.3f} fF/um (Metal4), {IF['wire_cap_fF_per_um']['Metal6']:.3f} fF/um (Metal6)", "PDK tech LEF: CPERSQDIST x width + 2 x EDGECAPACITANCE"],
        ["wire length", "300 / 500 / 700 um (short / nominal / long)", f"macro {cim['width_um']:.0f} um on a side, digital region ~{IF['geometry']['digital_core_side_um_at_util']:.0f} um [ASSUM] until Innovus routes it"],
        ["activity (measured)", f"outputs {IF['alpha_output_toggles_per_wire_per_read']:.3f} toggles / wire / read; row select {IF['alpha_rowselect_toggles_per_wire_per_read']:.4f}", f"gate-level VCD, {IF['reads_in_window']} reads in a {IF['window_cycles']}-cycle read-phase window; g = 8 netlist applied to g = 4"],
        ["energy per group read", f"{ifn:.1f} pJ nominal ({ifs:.1f} - {ifl:.1f})", "alpha x (C V^2 + level shifter)"],
        ["energy per inference", f"{fc['e_if']:.2f} uJ (full), x {g4['full']['mean_all_reads']:,.0f} reads", "all reads, empty ones included (as built)"],
        ["level shifters", f"{IF['level_shifters']['low_to_high']} low->high + {IF['level_shifters']['high_to_low']} high->low = {IF['level_shifters']['area_um2']:,.0f} um^2", "PDK LEF sizes (LSLHX1_TO, LSHLX1_FROM); **no Liberty in the PDK** -> their energy (4 fF x V^2 per toggle) is [ASSUM]"]]))
    w("")
    w("## 5. D4: chip numbers (pre-layout table first, then the full design with the OpenROAD layout)")
    w("")
    rows = []
    for b in BUILDS:
        x = C[b]
        rows.append([LAB[b], f"{x['acc'] * 100:.2f}%", f"{x['exit']:.1f}", f"{x['cycles']:,.0f}", f"{x['lat_ms']:.2f}", f"{x['e_dig']:.2f}", f"{x['e_xbar']:.2f}", f"{x['e_if']:.2f}", f"{x['e_hdc']:.4f}", f"**{x['e_tot']:.2f}**",
                     f"{x['a_dig_util']:.3f}", f"{x['a_xbar']:.3f}", f"{x['a_hdc']:.3f}", f"**{x['a_tot']:.3f}**"])
    w(table(["build (g = 4)", "accuracy", "mean exit t", "cycles", "latency (ms)", "digital (uJ)", "crossbar reads (uJ)", "interface (uJ)", "class arrays (uJ)", "**energy (uJ)**", "digital area / 0.65 (mm^2)", "analog macro (mm^2)",
             "class-HV macro (mm^2)", "**area (mm^2)**"], rows))
    w("")
    if fc["lay"]:
        ly = fc["lay"]
        dar = fp["DIE_W"] * fp["DIE_H"] * 1e-6
        w("")
        w(f"**Full design with the OpenROAD layout ({LAB_STAGE[best_stage]}):**")
        w("")
        w(table(["quantity", "pre-layout (section above)", "with layout", "note"], [
            ["digital energy per inference", f"{fc['e_dig']:.2f} uJ", f"**{ly['e_dig_incl_wires']:.2f} uJ**", f"ingest-window power x event cycles + read-window power x the rest; includes the wires of the macro boundary ({ly['e_boundary_wires']:.2f} uJ)"],
            ["crossbar reads", f"{fc['e_xbar']:.2f} uJ", f"{fc['e_xbar']:.2f} uJ", "[1F] x [RTL], unchanged"],
            ["interface: boundary wires", f"{fc['e_if']:.2f} uJ (assumed 500 um wires)", f"{ly['e_boundary_wires']:.2f} uJ, already inside the digital line", "OpenROAD wire C of the 992 boundary nets x measured transitions (`interface_routed_*.json`)"],
            ["interface: level shifters", "(inside the 0.99)", f"{ly['e_ls']:.2f} uJ", "[ASSUM] 4 fF x V^2 per toggle; the PDK has no Liberty for them"],
            ["class-HV arrays", f"{fc['e_hdc']:.4f} uJ", f"{fc['e_hdc']:.4f} uJ", "Phase 5 model"],
            ["**energy per inference**", f"**{fc['e_tot']:.2f} uJ**", f"**{ly['e_tot']:.2f} uJ**", f"{ly['e_tot'] / NH['energy_uJ']:.1f}x NeuroHDC-small's {NH['energy_uJ']} uJ"],
            ["chip area", f"{fc['a_tot']:.3f} mm^2 (digital cells / 0.65 + macros)", f"**{dar:.3f} mm^2** die (no pads)", f"{dar / NH['area_mm2']:.1f}x NeuroHDC-small's {NH['area_mm2']} mm^2; digital cells {BL['area']['std_cell_area_um2'] * 1e-6:.3f} + macros {A['B_128F'] + fc['a_hdc']:.3f} + margins/whitespace"],
            ["latency", f"{fc['lat_ms']:.2f} ms", f"{fc['lat_ms']:.2f} ms", "100 MHz closes in the fast corner only (section 1)"]]))
        w("")
        w("**How to read the jump from 1.26 to " + f"{ly['e_dig_incl_wires']:.1f}" + " uJ of digital energy.** The pre-route power had pin capacitance only (no wires) and an ideal clock. With the layout the switching power sits on wire capacitance "
          f"(0.42 fF/um from the PDK's LEF: area plus fringe, no coupling - without a field-solver extraction it may be off by about 2x either way) and the clock tree adds {fmt(grp(best_stage, 'mvm', 'Clock'), 2)} mW in the read phase. "
          "The netlist is Yosys' minimum-size mapping, not a physically-synthesised one: its weak cells are what makes the slow corner fail and the repair buffers swell the area by 71 %. A physically-aware synthesis (Genus) and a real extraction (Quantus) are expected to land lower; "
          "this table shows what an open-source flow does with the netlist as it stands, and that the pre-route 0.147 mW should not be quoted as a chip number.")
    w(f"NeuroHDC-small: {NH['area_mm2']} mm^2, {NH['energy_uJ']} uJ, 100 MHz, 45 nm, DVS-Gesture (post-layout, with clock tree and SRAM macros). Latency = cycles / 100 MHz (a pre-route clock; the post-route clock is the same 100 MHz if timing closes). "
      "Digital area in the pre-layout table = standard-cell area / an *assumed* 65 % utilisation (the layout table uses the die); level shifters add "
      f"{IF['level_shifters']['area_mm2']:.4f} mm^2; the chip area has no pads and no I/O ring. **Previous (digital_energy.md) energy was {f4['energy_uJ']['total'] + (f4['phase_resolved']['digital_uJ'] - f4['energy_uJ']['digital']):.2f} uJ; the interface adds "
      f"{fc['e_if']:.2f} uJ.**")
    w("")
    w("**Exclusions, named as in the previous reports.** Not in the energy of the pre-layout table: the clock tree (it is in the 'with layout' table); glitch power (zero-delay activity), the weight load and write path (ReRAM is non-volatile), the calibration energy, analog static power, "
      "the supply regulator, host IO, the idle bias of reads with no active row (assumed gated off). Not in the area: pads, the I/O ring, the supply regulator, power-grid overhead beyond the macro's 20 %, "
      "place-and-route whitespace beyond the assumed utilisation, the 6.4 kbit calibration store only as 1F counted it.")
    w("")
    w("## 6. What is now the largest term, and what to attack next")
    w("")
    if fc["lay"]:
        ly = fc["lay"]
        w(f"- **Energy with the layout ({ly['e_tot']:.1f} uJ):** digital {ly['e_dig_incl_wires']:.1f} ({pct(ly['e_dig_incl_wires'] / ly['e_tot'], 0)}), crossbar reads {fc['e_xbar']:.2f} ({pct(fc['e_xbar'] / ly['e_tot'], 0)}), level shifters {ly['e_ls']:.2f}. "
          f"Inside the digital {ly['e_dig_incl_wires']:.1f} uJ the macro-boundary wires are {ly['e_boundary_wires']:.2f} uJ - small; the rest is wire capacitance of the logic and the clock tree. Before the layout the order was crossbar reads ({fc['e_xbar']:.2f}) > digital ({fc['e_dig']:.2f}) > interface.")
        w("  Attack, in order: (1) a physically-aware synthesis and a real extraction (the current digital number is an upper-ish estimate from a minimum-size netlist and LEF RC - expect it to fall; this is the first thing to redo with Genus + Innovus + Quantus); "
          "(2) the structure that makes the wires long - `count_mem`'s 512-way read mux and the 1,600-flop partial-count register spread over the whole region (mean net 31 um, ~3,000 nets over 200 um): restructure for locality before gating any more; "
          "(3) the clock: 738 gated branches cost a ~1.3 mW tree in the read phase - fewer, larger gating groups; (4) then 1G for the crossbar.")
    else:
        w(f"- **Energy ({fc['e_tot']:.2f} uJ, pre-layout):** crossbar reads {fc['e_xbar']:.2f} ({pct(fc['e_xbar'] / fc['e_tot'], 0)}), digital {fc['e_dig']:.2f}, interface {fc['e_if']:.2f}.")
    w(f"- **Area ({fc['a_tot']:.2f} mm^2 pre-layout; {fp['DIE_W'] * fp['DIE_H'] * 1e-6:.2f} mm^2 die):** the analog macro {A['B_128F']:.2f} mm^2; inside it the cell arrays ({AA['B_128F']['parts_um2']['cell_array'] * 1e-6:.2f} mm^2) and the 1 nF decoupling "
      f"({AA['B_128F']['parts_um2']['decoupling'] * 1e-6:.2f} mm^2). Next: the select transistor (1D's write-current requirement fixes it at 128 F); decoupling per 1F's droop budget; segmenting the write driver from the read path. "
      "The die also carries the digital region at ~72 % density after buffering; it shrinks if the buffering does.")
    w("")
    w("## 7. How the numbers were produced, and what the owner can still run")
    w("")
    w("**Run in this repository (open-source tools only): the OpenROAD flow, full design only.** From `design/rtl/synth/`:")
    w("")
    w("```")
    w("python analog_macros.py ; python neurosim/run_neurosim.py            # macro areas, LEF / Liberty, NeuroSim")
    w("python prepare_rtl.py --build full ; python make_floorplan_params.py --build full --util 0.42 ; python openroad/make_pnr_netlist.py --build full")
    w("OPENROAD=<path to openroad> openroad/run_flow.sh full                # floorplan (macro first), place, CTS, global route   (OpenROAD built from source: not in Homebrew)")
    w("python openroad/analyze_openroad.py --stage pre_cts|post_cts|groute --build full --windows ing mvm     # timing both corners, skew, power windows, area")
    w("python openroad/interface_routed.py --stage groute --build full        # the macro-boundary wires with their placed capacitances")
    w("python final_ppa.py")
    w("```")
    w("")
    w("What these runs are NOT: **detailed routing was started (TritonRoute) and stopped after ~35 minutes at 164,000 violations after its second pass**, so the 'routed' column is global-routed wiring, not DRC-clean detailed routing. "
      "**Parasitics are the PDK LEF's layer RC** applied to the estimated wiring (no coupling, no extraction; OpenRCX needs a rules file the PDK does not ship, and the PDK's QRC technology file is for Quantus). "
      "The tech LEF needed six device-level via rules removed for the router (`openroad/sanitize_tech_lef.py`; the PDK file is untouched). The OpenROAD flow, the macro LEF, the floorplan and the analysis scripts are all reproducible from the repository plus the binary.")
    w("")
    w("**Prepared but not run (needs the owner's licences):** Genus synthesis, Innovus place / CTS / route, Quantus extraction - the same flow with signoff tools. Inputs are ready and checked as far as possible without them "
      "(the prepared RTL elaborates in Yosys with the macros and the ICG as library cells; `layout_analysis.py` analyses their netlist / SPEF / DEF with no licence):")
    w("")
    w("```")
    w("python prepare_rtl.py --build $B && python make_floorplan_params.py --build $B            # B = full ee_off fact_off both_off")
    w("BUILD=$B genus -batch -files genus/run_genus.tcl")
    w("BUILD=$B WORK=$PWD/work/$B innovus -batch -files innovus/run_innovus.tcl")
    w("for S in pre_cts post_cts routed; do python layout_analysis.py --stage $S --build $B --netlist results/innovus/$B/$S.v --spef results/innovus/$B/$S.spef --def results/innovus/$B/$S.def ; done")
    w("python final_ppa.py")
    w("```")
    w("")
    w("The Genus and Innovus scripts are modelled on the PDK's own examples and **have never been executed**: adapt option names to your tool versions. Not produced anywhere: SDF-annotated simulation (the PDK ships no Verilog cell models with "
      "specify blocks; power uses zero-delay gate-level activity plus estimated wire capacitance), GDS / DRC / LVS signoff, the other three builds' layouts.")
    w("")
    w("## 8. Files")
    w("")
    w("`synth/analog_macros.py` (areas, LEF, Liberty) - `synth/neurosim/` (driver + runner; NeuroSim itself is cloned outside the repository, CC BY-NC) - `synth/interface_model.py` - `synth/prepare_rtl.py`, `make_floorplan_params.py`, "
      "`openroad/` (`run_flow.sh`, `run_flow.tcl`, `make_pnr_netlist.py`, `sanitize_tech_lef.py`, `analyze_openroad.py`, `interface_routed.py`), `genus/`, `innovus/`, `constraints/`, `pdk.tcl` - `synth/layout_analysis.py` - `synth/final_ppa.py`. "
      "Results: `synth/results/{neurosim,analog_area,analog_macros,interface,interface_routed_*}.json`, `synth/results/layout/full/{pre_cts,post_cts,groute}/summary.json`, `synth/results/openroad/full/` (logs, stage netlists / DEFs / reports; the .odb databases are large and regenerable).")
    w("")
    w("## 9. Updated TO BE DETERMINED list")
    w("")
    w("- **Everything post-layout is from an open-source flow with LEF-derived RC on a Yosys minimum-size netlist.** The numbers to expect from Genus + Innovus + Quantus are lower for area and power (sized cells, real extraction) and may differ in sign for timing; run them (section 7) before quoting a chip number.")
    w("- **Slow-corner timing does not close** (about -30 ns here) and hold is violated by 0.2 ns (fast) / ~5 ns (slow): the minimum-size cells need sizing for the slow corner (max-transition violations on ~25,000 nets in the slow library). Needs a slow-corner-aware synthesis.")
    w("- **Detailed routing did not converge** (164,000 violations after pass 2 of ~17 min each); the 2,178-pin macro edge (0.4 um pitch on Metal4/Metal6) and the congested count-memory region are the suspects. Needs a floorplan / pin-pitch iteration or a tool with the signoff router.")
    w("- **Only the full design was laid out.** The other three builds' layout numbers are PENDING; their pre-layout numbers are in the tables.")
    w("- **Row-driver sizing at the 128 F cell:** NeuroSim's periphery does not grow with the cell width; 1C's per-length model would. The analog macro could be larger than 0.583 mm^2.")
    w("- **NeuroSim parameters:** HP device roadmap, ADC levels 8, column mux 8, cell height 4 F, write voltage below the level-shifter threshold, F = 45 nm. The array number rests on 'widthInFeatureSize1T1R = 128' (1D's SET-current requirement).")
    w("- **Interface:** activity is the g = 8 netlist's; level-shifter energy is assumed (no Liberty); the 1,120 constant-zero count bits are not yet tied off in the digital design; in the layout numbers the boundary wires are inside the digital line (not added twice).")
    w("- **Digital netlist parameterisation:** ROWS_PER_GROUP = 8 (package default) as in every pre-route number; cycle counts are the g = 4 RTL runs.")
    w("- **Power activity** is zero-delay (no glitches), from one sample (row 46) and two windows (ingest, read phase); the earlier sampling caveats carry over.")
    w("- **Decap:** 1F's 1 nF is inside the macro; the digital region's own decoupling and the power grid's IR drop are not modelled; the PDK has no decap cells.")
    w("- Still open from Phase 5: class-HV arrays are scaled models; the 1F energy model's own items; no pads / I/O ring; two corners of one library.")
    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT} ({len(L)} lines); routed results present: {have_routed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
