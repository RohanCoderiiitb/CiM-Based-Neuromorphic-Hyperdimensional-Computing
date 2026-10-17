"""1D-i report: <repo>/reports/phase1d_i_report.md, every number read from results/write_path/*.json.
Usage: python -m write.make_report"""
from __future__ import annotations

import json

import paths as RP

J = lambda p: json.loads(p.read_text())

# area model of the write path [ASSUM where marked]
CORE_RW_OHM_UM = 548.7          # [SIM, 1A] R_tx x W of the PTM core NMOS (1C driver sizing)
CORE_AREA_PER_UM = 0.0702e6 / (5120 * 54.87)     # um^2 per um of driver width, from 1C's 0.0702 mm^2 for 5,120 drivers at 10 ohm [MODEL]
THICK_RW = (1000.0, 1500.0, 2500.0)     # ohm um [ASSUM] on-resistance x width of a 2.5 V thick-oxide I/O NMOS in triode (no card in PTM)
THICK_AREA_FACTOR = (1.5, 2.0, 3.0)     # [ASSUM] layout area per um of width relative to the core device (L 0.27 um vs 45 nm, wider spacing)


def driver_area_mm2(r_drv: float, rw: float, factor: float, n: int = 5120) -> float:
    return n * (rw / r_drv) * CORE_AREA_PER_UM * factor * 1e-6


def f(x, n=2):
    return f"{x:.{n}f}"


def main() -> None:
    d1 = J(RP.WRITE / "d1_parallel.json")
    d1t = J(RP.WRITE / "d1_transient.json")
    d2 = J(RP.WRITE / "d2_unselected.json")
    d3 = J(RP.WRITE / "d3_halfselect.json")
    d45 = J(RP.WRITE / "d4_d5.json")
    dl = d1["delivery"]
    base = [r for r in d1["rows"] if r["kind"] == "base"]

    def row(mode, v, rw, ori="bl", vwl=1.1):
        return [r for r in base if r["params"]["mode"] == mode and abs(r["params"]["v_drive"] - v) < 1e-9 and r["params"]["row"] == rw and r["params"]["orientation"] == ori and r["params"]["v_wl"] == vwl][0]

    L = []
    A = L.append
    A("# Phase 1D-i report - the array-level write path\n")
    A("Tags: **[SIM]** ngspice (PTM 45 nm LP BSIM4 access transistors, the full five-macro row), **[MODEL]** analytic in code, **[ASSUM]** assumed, **[CHOICE]** design decision, "
      "**[SP]** Stanford-PKU default. Every number below is read from `results/write_path/*.json` by `python -m write.make_report`; commands in section 9.\n")
    A("**The device in this sub-phase is BEHAVIOURAL, not the compact model**: it holds its resistance (1A's 541.82 / 218,586 ohm) until |V| across it has exceeded a threshold "
      "for longer than a pulse-width parameter, then moves to the other state (`write/behav.py`). **Every threshold here is a swept parameter (0.8-2.0 V, 10 ns-1 us) and is "
      "provisional; 1D-ii replaces them with the compact model's own dynamics.** Carried forward from 1C/1F and not re-derived: 512 x 160 cells in five 32-cell macros, 20 F^2 "
      "access transistor (W = 0.54 um, word line 1.1 V), row drivers at both ends of every macro row (10 ohm), rails 0.0072 ohm/pitch fed from both ends, 0.72 ohm/pitch "
      "row line and bitline, 0.2 fF/pitch line capacitance.\n")

    # ---- 0
    s_ok = dl["set|1.2|512|bl|1.1"]
    A("## 0. The answer\n")
    A(f"- **Row-parallel SET works on the read-sized array: 160 devices per pulse (one per cell, one row at a time), {d1t[0]['i_peak_a'] * 1e3:.1f} mA peak, and every target reaches "
      f"its threshold with 0.1-0.2 V of headroom** (worst row and worst column; rails droop {row('set', 1.6, 256)['after']['v_rail_droop'] * 1e3:.0f} mV at the middle row, the row line "
      f"{row('set', 1.6, 512)['after']['row_droop_max'] * 1e3:.0f} mV). The rails and drivers are **not** what limits the parallelism; the shared word line and bitlines are (two rows "
      "cannot be written at once). Section 1.")
    A("- **What limits the write is the 1.1 V core access transistor, in three ways.** (i) **One polarity is source-follower capped at ~0.5 V across the device**: with the "
      "transistor on the bitline side a RESET can never put more than "
      f"{dl['reset|0.8|512|bl|1.1']['best_v_dev']:.2f} V across the 541.8 ohm state (and ~0.48-0.56 V across an HRS-side device); with it on the row-line side the same happens to SET. "
      "(ii) **RESET of the 541.8 ohm LRS is undeliverable at any swept threshold** in either orientation, even with the word line overdriven to 2.5 V: it needs "
      ">= 0.8 V / 541.8 ohm = 1.5 mA, the 20 F^2 transistor gives 0.17-0.33 mA. (iii) **SET above ~1.3 V puts more than 1.1 V across the written cell's own transistor** "
      f"(Vds {dl['set|1.2|512|bl|1.1']['vds_max']:.2f} V at the drive that delivers 1.2 V, {dl['set|1.6|512|bl|1.1']['vds_max']:.2f} V for 1.6 V). Section 1.3.")
    A("- **The write voltage path cannot share the core read drivers.** Any write above 1.1 V needs thick-oxide (I/O) drivers on every row end and on every bitline, and "
      "the read driver's output sits on the same row line, so it must be thick-oxide too: **one thick-oxide driver per row end with a supply mux (0.35 V read / V_write)** "
      f"at {driver_area_mm2(10, 1500, 2.0):.2f} mm^2 for the 5,120 row drivers (range {driver_area_mm2(10, 1000, 1.5):.2f}-{driver_area_mm2(10, 2500, 3.0):.2f} [ASSUM]) against 1C's 0.070 mm^2 - "
      "the largest area item of the array. Section 1.4.")
    A("- **Unselected bitlines: drive them, never float or ground them.** Floating, an HRS neighbour sees up to the full write voltage for 4-9 ns (switches if t_min <= 5 ns, "
      "measured with the behavioural device); clamped to 0 V every non-target is written and an LRS row doubles the current. **Recommended: non-target bitlines at V/2 in the SET "
      "phase** - the non-target's own access transistor then cuts off (its source sits above V_WL - V_th), so it sees < 0.03 V and carries < 0.2 uA in total, and no access transistor "
      "outside the written cell sees more than V/2. Section 2.")
    A("- **2T2R half-select: two row-parallel phases (RESET, then SET), the partner addressed by its own bitline.** No cell change is needed for addressing; the partner sees "
      "< 0.03 V. Unselected rows: leakage bounds the disturb (0.16-0.27 nA per cell at 125 C, < 0.1 mV across the device). **But the RESET phase has no bias scheme that keeps "
      "the 511 x 160 off transistors on a target bitline inside 1.1 V above V_RESET = 1.4 V**: their gate sits at 0 V and their drain on the bitline. Section 3.")
    p100 = [r for r in d45["program"] if abs(r["width_s"] - 100e-9) < 1e-12][0]
    p1u = [r for r in d45["program"] if abs(r["width_s"] - 1e-6) < 1e-12][0]
    A(f"- **Full-array program at the measured parallelism: {p100['time_s'] * 1e3:.2f} ms at 100 ns pulses, {p1u['time_s'] * 1e3:.1f} ms at 1 us** (512 rows x 2 phases x 3 pulses [ASSUM] "
      f"with a verify after each); energy at 1B's 10 pJ [ASSUM] {p100['energy_assumed_j'] * 1e6:.1f} uJ, but the array-level estimate at the measured row current is "
      f"{p100['energy_array_estimate_j'] * 1e6:.1f} uJ at 100 ns and {p1u['energy_array_estimate_j'] * 1e6:.0f} uJ at 1 us: **10 pJ per pulse is optimistic for any pulse longer than ~30 ns.** "
      f"Peak write current {d45['i_row_peak_a'] * 1e3:.0f} mA on a 1-2 V write rail (below the read PDN's 69 mA, but a different rail with its own decoupling). Section 4.")
    A("- **Reprogramming: the front-end trims and the rank-3 gain correction survive; the ladder survives only if the program-verify places the population mean where it did "
      f"before.** A full regeneration is {d45['recal'][0]['reads'] + d45['recal'][2]['reads']:,} full-array reads ({d45['recal_time_s']['full'] * 1e3:.2f} ms); the trim re-fit "
      f"alone is {d45['recal'][2]['reads']} reads ({d45['recal_time_s']['trims_only'] * 1e6:.1f} us) and is the same procedure as 1F's 5 K thermal recalibration. Section 5.")
    A("- **Handoff to 1D-ii (section 7): SET can deliver 0.8-2.4 V to an HRS device (bitline-side transistor, 1.1 V word line), at 200-330 uA of per-device current, any pulse "
      "width from 10 ns to DC, 160 devices per pulse; within the 1.1 V transistor rating the SET drive is limited to ~1.3 V. RESET can deliver at most ~0.5 V across a "
      "high-resistance device and 0.09-0.13 V across a 541.8 ohm one, at 0.17-0.22 mA from the 541.8 ohm state (section 1.3).** Every device number that needs more is flagged as needing a "
      "different array.\n")

    # ---- 1
    A("## 1. D1 - can the read-sized array carry a write\n")
    A("`write/rowdeck.py` builds the selected row of the full array in ngspice: five macros of 64 bitlines, the row line (0.72 ohm per bitline pitch) broken between macros with a "
      "write driver at both ends of every macro row, all ten drivers on one tap of the supply rail (0.0072 ohm/row pitch, fed both ends: the tap at the middle row sees "
      "0.92 ohm), every bitline as the selected cell (behavioural device + BSIM4 transistor, word line 1.1 V) then an 8-section RC ladder of bitline (0.72 ohm and 0.2 fF per "
      "pitch from the selected row to the edge) then a bitline driver (10 ohm [ASSUM]) returning through the ground rail (0.0072 ohm/column pitch, one pad per macro). "
      "Row 512 is the worst case for the bitline (369 ohm of wire in series), row 256 for the supply rail. The written row: the LRS device of each of 160 cells "
      "(random weights), the partner held as in section 2. Snapshots (`write/d1_parallel.py`): *before* (all targets still HRS: the threshold check), *last* "
      "(all targets switched except the worst-placed one per macro: the voltage left for the last device while its neighbours draw their post-switch current), *after* (all switched: peak current).\n")
    A("### 1.1 Row-parallel SET: delivered voltage, current, droop (transistor on the bitline side, word line 1.1 V)\n")
    A("| V_drive (V) | row | before: min V at a target (V) | last: V at the last target (V) | supply current after (mA) | rail droop (mV) | largest driver current (mA) / drop (mV) | row-line droop (mV) | Vds of a written transistor (V) |")
    A("|---|---|---|---|---|---|---|---|---|")
    for v in (1.0, 1.2, 1.4, 1.6, 2.0, 2.4):
        for rw in (256, 512):
            r = row("set", v, rw)
            A(f"| {v} | {rw} | {r['before']['v_dev_min']:.3f} | {r['last']['v_dev_min']:.3f} | {r['after']['i_supply'] * 1e3:.1f} | {r['after']['v_rail_droop'] * 1e3:.1f} | "
              f"{r['after']['i_driver_max'] * 1e3:.2f} / {r['after']['v_driver_drop_max'] * 1e3:.0f} | {r['after']['row_droop_max'] * 1e3:.0f} | {r['after']['vds_max_target']:.2f} |")
    A("")
    A("- **Delivery (a target that does not reach threshold is not programmed):** the smallest V_drive at which every target, including the last one, sees more than the "
      "swept threshold:\n")
    A("| threshold V_th (V) | V_drive needed, row 256 / 512 (V) | voltage at the last target (V) | Vds of the written transistor at that drive (V) | within the 1.1 V rating |")
    A("|---|---|---|---|---|")
    for vth in ("0.8", "1.0", "1.2", "1.4", "1.6", "1.8", "2.0"):
        a, b = dl[f"set|{vth}|256|bl|1.1"], dl[f"set|{vth}|512|bl|1.1"]
        A(f"| {vth} | {a['v_drive_min']} / {b['v_drive_min']} | {a['last_v']:.3f} / {b['last_v']:.3f} | {max(a['vds_max'], b['vds_max']):.2f} | {'yes' if a['within_tx_rating'] and b['within_tx_rating'] else '**no**'} |")
    A("")
    A("  The array loses 0.06-0.14 V between the pad and the last device at 10 ohm drivers (rail + driver + row line); 0.1-0.2 V of headroom on the 0.1 V grid of the sweep covers it at every threshold. "
      "**Every swept threshold is deliverable for SET; thresholds above ~1.2 V need a drive that puts more than 1.1 V across the written cell's own (core) transistor once it has switched** "
      "(the behavioural LRS is 541.8 ohm, so after switching the transistor carries the write current in saturation and holds the rest of the drive).")
    A("- **The far columns** (1C found starvation at read voltages): with both-end drivers the worst row-line position is the middle of each macro; its loss at the full 160-cell "
      f"write is {row('set', 1.6, 512)['after']['row_droop_max'] * 1e3:.0f} mV at 1.6 V - small against the threshold, and every column was switched in the transient (1.4).")
    A("### 1.2 The rails and the drivers at write current\n")
    A("| V_drive (V) | row | R_WDRV (ohm) | rail (ohm/pitch) | supply (mA) | rail droop (mV) | driver drop (mV) | loss pad -> last target (mV) |")
    A("|---|---|---|---|---|---|---|---|")
    for r in [x for x in d1["rows"] if x["kind"] == "drivers_rails" and x["params"]["v_drive"] == 1.6]:
        p = r["params"]
        A(f"| {p['v_drive']} | {p['row']} | {p['r_wdrv']:.0f} | {p['r_rail']} | {r['after']['i_supply'] * 1e3:.1f} | {r['after']['v_rail_droop'] * 1e3:.1f} | {r['after']['v_driver_drop_max'] * 1e3:.0f} | "
          f"{(p['v_drive'] - r['last']['v_dev_min']) * 1e3:.0f} |")
    A("")
    A("- **The 0.0072 ohm/pitch rails sized for the 69 mA read hold the write** (34-46 mA): 33-43 mV at the middle row. **At 0.072 ohm/pitch they do not** (0.33-0.38 V lost at "
      "the middle row - more than the headroom). Drivers: 10-20 ohm keeps the loss to 0.08-0.16 V; 50 ohm loses 0.2-0.3 V. **A write driver of <= 20 ohm per row end is the "
      "requirement**, the same class as 1C's read driver.")
    A("### 1.3 What the access transistor allows - both polarities, both orientations, word line 1.1-2.5 V\n")
    A("Delivered |V| across the target at its starting state (SET: HRS, RESET: the 541.8 ohm LRS), best over V_drive <= 2.5 V, row 512:\n")
    A("| word line (V) | SET, transistor on bitline side | SET, transistor on row-line side | RESET, bitline side | RESET, row-line side |")
    A("|---|---|---|---|---|")
    for vwl in (1.1, 1.5, 1.8, 2.5):
        cells = []
        for mode, ori in (("set", "bl"), ("set", "rl"), ("reset", "bl"), ("reset", "rl")):
            sel = [r for r in base if r["params"]["mode"] == mode and r["params"]["orientation"] == ori and r["params"]["v_wl"] == vwl and r["params"]["row"] == 512]
            best = max(min(r["before"]["v_dev_min"], r["last"]["v_dev_min"]) for r in sel)
            cells.append(f"{best:.2f} V")
        A(f"| {vwl}{' (rated)' if vwl == 1.1 else ' (overstress)'} | " + " | ".join(cells) + " |")
    A("")
    A("- **The source follower.** An NMOS whose source is the node next to the device cannot pull that node above V_WL - V_th (~0.5 V at 1.1 V, falling with body effect). "
      "With the transistor on the bitline side that node is the device's low side in RESET; on the row-line side it is the device's high side in SET. **So at a 1.1 V word "
      "line one polarity is capped at ~0.5 V whatever the drive.** [CHOICE] **bitline side** - the orientation in which SET (which needs current: the LRS is reached under "
      "transistor compliance) gets the full voltage; RESET is the capped polarity. 1A-1C simulated the read with the transistor on the row-line side; the read is unaffected "
      "to first order (in both orientations the transistor's source sits at the 0.25 V sense node in 1F's read: see the 1D-ii report's R_tx check).")
    A("- **RESET of the 541.8 ohm state is not deliverable, in either orientation, at any word line up to 2.5 V**: the device current needed for a threshold of 0.8 V is 1.5 mA, "
      "and the transistor delivers 0.17-0.22 mA (bitline side) / 0.22-0.33 mA (row-line side) at 1.1 V and at most 0.7-0.9 mA at 2.5 V. With the behavioural model this means: "
      "**the 1A LRS cannot be RESET by the 20 F^2 cell.** This is a property of the read-optimised operating point (a 541.8 ohm state behind a minimum-size transistor), not "
      "of any threshold value, and it is the first thing 1D-ii has to test with the compact model.")
    A("### 1.4 The write voltage path: shared or separate drivers, and the area\n")
    A(f"Write voltages above 1.1 V cannot pass through or sit on a core device. The read drivers (1C: 5,120 core devices, W = 54.9 um each at 10 ohm, 0.070 mm^2) drive the same row "
      f"lines; during a write their outputs see V_write. Options [area: thick-oxide R x W = 1000 / 1500 / 2500 ohm um and 1.5 / 2 / 3x the core area per um, ASSUM; core 548.7 ohm um, 1A]:\n")
    A("| option | what is thick-oxide | row-driver area (mm^2), low / mid / high | verdict |")
    A("|---|---|---|---|")
    A(f"| A. one driver per row end, thick-oxide, supply mux 0.35 V / V_write | 5,120 drivers sized for the READ (10 ohm) | {driver_area_mm2(10, 1000, 1.5):.2f} / {driver_area_mm2(10, 1500, 2):.2f} / {driver_area_mm2(10, 2500, 3):.2f} | **recommended**: one device, sized by the read |")
    A(f"| B. separate thick-oxide write drivers (20 ohm) + core read drivers behind a thick-oxide isolation switch (2 ohm) | 5,120 write drivers + 5,120 switches | "
      f"{driver_area_mm2(20, 1000, 1.5) + driver_area_mm2(2, 1000, 1.5) + 0.0702:.2f} / {driver_area_mm2(20, 1500, 2) + driver_area_mm2(2, 1500, 2) + 0.0702:.2f} / {driver_area_mm2(20, 2500, 3) + driver_area_mm2(2, 2500, 3) + 0.0702:.2f} | the switch in the read path must be ~5x below R_DRV: larger than A |")
    A("| C. keep everything core, V_write <= 1.1 V | none | 0.070 (1C) | only for device thresholds below ~0.9 V; RESET still capped (1.3) |")
    A("")
    A("Bitlines need the same: a three-level write driver per bitline (0, V/2, V; it sinks <= 0.33 mA, a 100 ohm device is enough) and a thick-oxide isolation switch between "
      "the bitline and the 1F sense front-end (core devices at a 0.25 V virtual ground), 320 of each: ~0.01-0.03 mm^2 [ASSUM]. "
      "**The write path costs 0.15-0.96 mm^2 of thick-oxide drivers - comparable to or larger than 1F's whole 0.43 mm^2.** 1C's row-driver total (already 50% of the array) "
      "multiplies by 2.2-13x.")
    A("### 1.5 The largest viable parallelism\n")
    A("| cells written per pulse (spread over the five macros) | V_drive 1.6 V: V at the last target (V) | supply (mA) | largest driver current (mA) | row-line droop (mV) |")
    A("|---|---|---|---|---|")
    for r in [x for x in d1["rows"] if x["kind"] == "parallel" and x["params"]["v_drive"] == 1.6]:
        A(f"| {r['n_par']} | {r['last']['v_dev_min']:.3f} | {r['after']['i_supply'] * 1e3:.1f} | {r['after']['i_driver_max'] * 1e3:.2f} | {r['after']['row_droop_max'] * 1e3:.0f} |")
    A("")
    A("**Largest viable parallelism: 160 devices per pulse = one whole row (one device per cell), limited by the array structure, not by the rails or drivers.** All 320 devices of a "
      "row share one word line, so the two devices of a cell cannot be written in the same pulse in opposite directions (section 3), and two rows on the same bitlines cannot be "
      "written at once. The rails would carry several rows (a second row adds ~35 mA and ~35 mV at the middle tap) if the word lines were segmented per macro - not part of 1C's "
      "array [CHOICE: not adopted].")
    A("### 1.6 The write as a transient (behavioural device in all 320 positions)\n")
    A("| case | targets switched | non-targets switched | switch time of the targets (ns) | peak supply current (mA) |")
    A("|---|---|---|---|---|")
    for r in d1t:
        c = r["case"]
        A(f"| V_drive {c['v_drive']} V, V_th {c['vth']} V, t_min {c['tmin'] * 1e9:.0f} ns, non-targets {c['unselected'] if c['v_inh'] is None else 'at ' + str(c['v_inh']) + ' V'} | {r['targets_switched']}/{r['n_targets']} | "
          f"{r['nontargets_switched']} | {r['t_switch_min'] * 1e9:.1f}-{r['t_switch_max'] * 1e9:.1f} | {r['i_peak_a'] * 1e3:.1f} |")
    A("")
    A("![Figure 22: what reaches the device; the transistor's stress and the RESET cap](../figures/fig22_write_delivery.png)\n")
    A("*Figure 22.* Left: the voltage that reaches the last target device of a row-parallel write (far row, word line 1.1 V) against the write supply, for SET of an HRS device and "
      "RESET of the 541.8 ohm LRS, with the access transistor on either side; grey: the swept device thresholds. Only SET with the transistor on the bitline side reaches the band. "
      "Right: the Vds of the written cell's own transistor after it has switched (SET) and the source-follower cap on RESET for word lines 1.1-2.5 V; dotted: the 1.1 V rating.\n")

    # ---- 2
    A("## 2. D2 - the unselected (non-target) bitlines\n")
    A("In a row-parallel write every cell has one target and one non-target device (its partner); in a partial row whole cells are non-targets. `write/d2_unselected.py`.\n")
    A("**(a) Floating.** The bitline (102 fF) charges toward the row line through the non-target device and its access transistor, which is ON (the word line is shared). Measured "
      "(transient, device held at its state, far row):\n")
    A("| V_drive (V) | non-target state | peak V across it (V) | time above 0.8 V (ns) | time above 1.0 V (ns) | time above 1.2 V (ns) |")
    A("|---|---|---|---|---|---|")
    for r in d2["float"]:
        c = max(r["curves"].values(), key=lambda c: c["peak"])
        A(f"| {r['v_drive']} | {r['state']} | {c['peak']:.3f} | {c['time_above_s']['0.8'] * 1e9:.2f} | {c['time_above_s']['1.0'] * 1e9:.2f} | {c['time_above_s']['1.2'] * 1e9:.2f} |")
    A("")
    A("- **It depends on what the neighbour stores** (as 1C found at read voltages): an LRS neighbour charges its bitline in ~0.2 ns and never sees more than 0.06 V; an HRS "
      "neighbour sees nearly the full drive for 4-9 ns (the bitline only has to reach V_WL - V_th ~ 0.5 V for its transistor to cut off, after which the internal node follows the "
      "row line). **Disturb if t_min < ~5-9 ns** - confirmed with the behavioural device in all 320 positions: at t_min = 5 ns all 160 HRS neighbours switched, at 10 ns none "
      "(section 1.6). With the compact model there is no threshold, only a rate: 1D-ii quantifies the gap an HRS neighbour loses in these few nanoseconds.")
    A("\n**(b) Clamped.** DC, far row, non-targets held at 0 V / at V/2 / at the row level V:\n")
    A("| V_drive (V) | non-targets | clamp to 0 V: max V across (V), current (mA) | inhibit V/2: max V (V), current (mA) | inhibit V: max V (V), current (mA) |")
    A("|---|---|---|---|---|")
    for v in (1.0, 1.2, 1.6, 2.0):
        for st in ("LRS", "HRS"):
            c = {m: [x for x in d2["dc"] if x["mode"] == m and x["v_drive"] == v and x["row"] == 512 and x["nontarget_state"] == st][0]["after"] for m in ("clamp0", "inhibit_V2", "inhibit_V")}
            A(f"| {v} | {st} | {c['clamp0']['nontarget_vdev_max']:.3f}, {c['clamp0']['nontarget_i_total'] * 1e3:.2f} | {c['inhibit_V2']['nontarget_vdev_max']:.4f}, {c['inhibit_V2']['nontarget_i_total'] * 1e3:.4f} | "
              f"{c['inhibit_V']['nontarget_vdev_max']:.4f}, {c['inhibit_V']['nontarget_i_total'] * 1e3:.5f} |")
    A("")
    A("- **Clamped to 0 V** every non-target sees the full write: it is being written, not protected; with LRS non-targets the row draws twice the current "
      "(the clamp current equals the target current: 32-41 mA more on the rails of section 1.2). Rejected.")
    A("- **Inhibit at V or V/2**: the non-target's own access transistor has its source on the bitline; once the bitline is above V_WL - V_th (~0.5 V) the transistor is off and "
      "the device sees essentially nothing (the internal node floats to the row level). At V/2 below ~1.4 V the transistor is still partly on: up to 0.2 V and 0.2 mA total at 1.0 V, "
      "0.02 V at 1.2 V.")
    A("- **(c) Recommendation: drive the non-target bitlines to V/2 in the SET phase (to the row level, 0 V, in the RESET phase).** Disturb < 0.03 V and < 0.2 mA extra at V >= 1.2 V. "
      "V/2 rather than V because of the access transistors on the UNSELECTED rows (section 3): with the bitline at V their gate (0 V) to drain voltage is V; at V/2 it is V/2. "
      "Floating is acceptable only if the device's minimum switching time is > ~10 ns (an assumption 1D-ii must check).")
    A("\n![Figure 23: floating and clamped non-target bitlines](../figures/fig23_unselected_bitlines.png)\n")
    A("*Figure 23.* Left: voltage across a floating non-target device during a row-parallel SET (far row): an HRS neighbour holds most of the write voltage for several ns, an LRS "
      "neighbour almost none. Right: the DC current through the 160 non-target devices when their bitlines are clamped to 0 V, held at V/2 or at the row level.\n")

    # ---- 3
    A("## 3. D3 - half-select inside the 2T2R cell and on the unselected rows\n")
    A("**(a) Addressing.** Both devices of a cell share the word line and the row line but sit on different bitlines, so **separate bitline drive is enough** - no cell change. "
      "A cell's two devices go in opposite directions, so a row is written in **two row-parallel phases: RESET (the devices that must become HRS) then SET (the devices that "
      "must become LRS)** [CHOICE: RESET first, so that during the SET phase every partner is HRS and its transistor cuts off at V/2; an LRS partner at V/2 and 1.2 V draws 17 uA "
      "per row through the partly-on transistor].")
    A("\n**(b)/(c) Every device class during one phase** (`write/d3_halfselect.py`: device + BSIM4 transistor between ideal line levels; non-target bitline, unselected row line "
      "and unselected word line each swept over 0 / V/2 / V; device LRS and HRS; 27 and 125 C). Admissible = no non-target device sees more than 0.4 V (half the lowest swept "
      "threshold) [CHOICE] and the unselected array draws < 100 uA; among those, the scheme with the smallest stress on the transistors other than the written one:\n")
    A("| phase | V (V) | non-target BL | unselected RL | unselected WL | |V| on the target (V) | worst non-target |V| (V) | written transistor stress (V) | other transistors' stress (V) | unselected-array leakage 27 / 125 C (uA) |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for ph in ("set", "reset"):
        for v in (1.0, 1.2, 1.4, 1.6, 2.0, 2.2):
            b = d3["best"].get(f"{ph}|{v}|bl|27.0")
            bh = d3["best"].get(f"{ph}|{v}|bl|125.0")
            if b is None:
                A(f"| {ph.upper()} | {v} | - | - | - | - | - | - | **no admissible scheme** | - |")
            else:
                A(f"| {ph.upper()} | {v} | {b['bln']} | {b['rlu']} | {b['wlu']} | {b['deliver_v']:.3f} | {b['disturb_v']:.3f} | {b['stress_target_v']:.2f} | {b['stress_others_v']:.2f} | "
                  f"{b['i_unselected_total_a'] * 1e6:.2f} / {bh['i_unselected_total_a'] * 1e6 if bh else float('nan'):.1f} |")
    A("")
    sv = [r for r in d3["rows"] if r["phase"] == "set" and r["ori"] == "bl" and r["bln"] == "V/2" and r["rlu"] == "0" and r["wlu"] == "0" and r["v"] == 1.6]
    c27 = [r for r in sv if r["temp"] == 27.0][0]["classes"]; c125 = [r for r in sv if r["temp"] == 125.0][0]["classes"]
    A(f"- **The partner during its partner's SET** (S-N, V/2 on its bitline, 1.6 V): {abs(c27['S-N|HRS']['v_dev']) * 1e3:.2f} mV across it at 27 C, {abs(c125['S-N|HRS']['v_dev']) * 1e3:.2f} mV at 125 C, "
      "against the RESET (and SET) thresholds of 0.8-2.0 V: a margin of > 0.79 V. Section 2's transient adds no switching skew (the inhibit is driven by the same pulse shape).")
    A(f"- **Unselected rows**: per off cell at the write bias the leakage is {c27['U-N|HRS']['i'] * 1e12:.1f} pA at 27 C and {c125['U-N|HRS']['i'] * 1e12:.0f} pA at 125 C "
      f"(1A: 4.6 pA at the read bias, 27 C); the voltage it puts across the device is {abs(c125['U-N|HRS']['v_dev']) * 1e6:.0f} uV at 125 C. **Leakage bounds half-select on unselected rows "
      "at the write voltage and at 125 C, by > 4 orders of magnitude.** (The total, 81,760 off cells, is 1-25 uA - a small DC load on the write supply.)")
    A("- **What it does to the core transistors.** SET: with V/2 on the non-target bitlines no transistor outside the written cell sees more than V/2 - inside 1.1 V up to "
      "V = 2.2 V; **the written cell's own transistor holds V - V_device in compliance: above 1.1 V for V >= ~1.3 V.** RESET: a target bitline at V faces 511 off transistors whose "
      "gate is at 0 V, so their gate-drain voltage is V; raising the unselected word lines turns them on (amperes through 81,760 cells). **No admissible RESET scheme keeps "
      "the array inside 1.1 V above V_RESET = 1.1 V, and none is admissible at all above 1.4 V** (gate-induced drain leakage then exceeds the load limit). "
      "Together with 1.3: **a RESET above ~1.1 V needs thick-oxide access transistors - a different array.**")
    A("\n![Figure 24: transistor stress of the best admissible bias scheme](../figures/fig24_bias_schemes.png)\n")
    A("*Figure 24.* The largest terminal voltage on any access transistor for the best admissible bias scheme, against the write voltage: SET (transistor on the bitline side) keeps "
      "every other transistor at V/2, but the written transistor itself exceeds 1.1 V from ~1.3 V; RESET has no admissible scheme above 1.4 V and exceeds the rating from 1.1 V.\n")

    # ---- 4
    A("## 4. D4 - program time, energy, sequencing\n")
    A(f"Parallelism 160 devices per pulse (section 1.5), two phases per row, 512 rows, **3 pulses per device and 10 pJ per pulse are 1B's [ASSUM] until 1D-ii**, a verify read "
      f"(1F's 10 ns read cycle) after each pulse, write <-> verify switch-over 2 x 5 ns [ASSUM], pulse edges 1 ns. 1B's placeholder: 4.9 uJ, 0.31 ms at 100 ns (row-parallel, no verify).\n")
    A("| pulse width | full-array program time (ms) | energy at 10 pJ/pulse [ASSUM] (uJ) | array energy at the measured row current (uJ) [MODEL] | verify reads (uJ) | without verify: time (ms) |")
    A("|---|---|---|---|---|---|")
    for r, r0 in zip(d45["program"], d45["program_no_verify"]):
        A(f"| {r['width_s'] * 1e9:.0f} ns | {r['time_s'] * 1e3:.3f} | {r['energy_assumed_j'] * 1e6:.2f} | {r['energy_array_estimate_j'] * 1e6:.2f} | {r['energy_verify_j'] * 1e6:.2f} | {r0['time_s'] * 1e3:.3f} |")
    A("")
    A(f"- The array-level estimate uses the measured row current ({d45['i_row_peak_a'] * 1e3:.1f} mA at 1.2 V: the behavioural LRS at the transistor's compliance) for half the "
      "pulse on average [MODEL]: **at pulses longer than ~30 ns the post-switch current, not the switching event, dominates the energy**, and 10 pJ per pulse is optimistic by 1-2 "
      "orders at 1 us. 1D-ii replaces both the pulse count and the energy with the compact model's.")
    A(f"- **Peak write current: {d45['i_row_peak_a'] * 1e3:.0f} mA** (34-46 mA over V_drive 1.0-2.2 V, section 1.1) against the read PDN's 69 mA: lower, but **on a separate 1-2 V write rail**; "
      "1F section 5's decoupling sits on the 0.35 V read rail and does not serve it. The write rail needs its own regulator and decoupling: a 40 mA step with a ~16 MHz regulator loop "
      "(1F's assumption) and 50 mV of droop needs ~8 nF [MODEL: I / (2 pi f_reg) / dV] - unless the pulse edges are slowed to the regulator's bandwidth (a 1 us pulse with 100 ns edges needs much less).")
    A("\n**(b) The write sequence - a requirement for the RTL (not implemented):**\n")
    A("```")
    for s in d45["sequence"]:
        A(s)
    A("```\n")

    # ---- 5
    A("## 5. D5 - what reprogramming costs the rest of the design\n")
    A("| stored state | depends on | survives a reprogram? | regeneration |")
    A("|---|---|---|---|")
    for r in d45["recal"]:
        A(f"| {r['item']} | {r['depends_on']} | {r['survives_reprogram']} | {r['regenerate']} |")
    A("")
    A(f"- **The split the brief expected holds, with one qualification.** 1F's front-end trims are a property of the front-end, not of the cells - but they are FITTED through "
      "known cells, so they can only be re-fitted once the array holds known data (after the program, never during it). 1C's thresholds depend on the cells, but only through the "
      "population mean of the programmed conductances (the geometry and the target states set them; the individual cell's spread is the budget's sigma term): if the program-verify "
      "window is centred where it was, the table survives.")
    A(f"- **Cost:** trims only: {d45['recal'][2]['reads']} full-array reads = {d45['recal_time_s']['trims_only'] * 1e6:.1f} us and {d45['recal_energy_j']['trims_only'] * 1e9:.0f} nJ "
      f"(1F's 228 pJ per read); a full ladder regeneration: {d45['recal'][0]['reads']:,} reads = {d45['recal_time_s']['full'] * 1e3:.2f} ms and {d45['recal_energy_j']['full'] * 1e6:.1f} uJ, "
      "plus a per-column two-parameter least-squares fit on 18 points (~100 multiply-adds per column, 16k for the array) on the digital side. Both are small against the program itself.")
    A("- **(c) Post-program calibration and the 5 K thermal recalibration are the same procedure for the trims** (18 known configurations x 9 reads, re-fit 2 x 2 parameters per "
      "column). The post-program calibration adds a check of the ladder's level scale (a few reference reads per group; full regeneration only if it moved). Whether the thermal "
      "recalibration must ALSO touch the ladder depends on the cell's read-current temperature coefficient - the compact model has none in the device, but the access transistor "
      "does: 1D-ii D3 measures it.\n")

    # ---- 6
    A("## 6. Every device parameter of this sub-phase is swept and provisional\n")
    A("| parameter | values | status |")
    A("|---|---|---|")
    A("| SET threshold V_th | 0.8-2.0 V (0.1 V steps) | [ASSUM, swept]: replaced by the compact model's rate equation in 1D-ii (there is no threshold, only a rate) |")
    A("| RESET threshold | 0.8-2.0 V | [ASSUM, swept]: as above |")
    A("| minimum switching time t_min | 5 ns-1 us (transients 5, 10, 100 ns) | [ASSUM, swept]: replaced in 1D-ii |")
    A("| switching time constant after firing | 2 ns | [CHOICE] numerical; latched once fired |")
    A("| LRS / HRS during the write | 541.82 / 218,586 ohm, linear | [SIM 1A] at the read bias; the compact model is strongly non-linear at write voltages (1D-ii) |")
    A("| pulses per device, energy per pulse | 3, 10 pJ | [ASSUM, 1B]: replaced by 1D-ii D2 |")
    A("")

    # ---- 7
    A("## 7. Handoff to 1D-ii - what the array can deliver\n")
    A("| quantity | value | status |")
    A("|---|---|---|")
    A("| cell orientation | access transistor on the BITLINE side | [CHOICE], section 1.3 |")
    A("| SET: voltage across an HRS device | V_drive - 0.06..0.14 V, for V_drive 0.8-2.5 V | [SIM] |")
    A("| SET: per-device current | 0.20-0.33 mA (transistor compliance at word line 1.1 V; set by the transistor, not the drive) | [SIM] |")
    A("| SET: within the 1.1 V transistor rating | V_drive <= ~1.3 V for a 541.8 ohm post-switch state (Vds = V - V_device: a more resistive post-SET state allows more) | [SIM]; 1D-ii re-checks with the real state |")
    A("| RESET: voltage across the device | <= ~0.48-0.56 V for a high-resistance device (source follower), 0.09-0.13 V for the 541.8 ohm state | [SIM] |")
    A("| RESET: per-device current | 0.17-0.22 mA from the 541.8 ohm state | [SIM] |")
    A("| RESET above 1.1 V on the bitline | outside the rating of the 511 off transistors per column | [SIM] section 3 |")
    A("| pulse width | 10 ns (1 ns edges; the array's own RC is < 0.1 ns) to DC: the array holds a level indefinitely, the cost is time | [SIM] |")
    A("| parallelism | 160 devices per pulse (one row, one device per cell, per phase) | [SIM] |")
    A("| series resistance in the write path | row side ~17 ohm (drivers + half a macro row + rail); bitline side 11 ohm (row 1) to 379 ohm (row 512) | [MODEL] |")
    A("| unselected bitlines | V/2 (SET phase), 0 V (RESET phase); floating disturbs an HRS neighbour for 4-9 ns | [SIM] |")
    A("| a different array | anything that needs > 0.33 mA per device, > ~0.5 V across the device in RESET, or > 1.1 V on a bitline in RESET | flag |")
    A("")
    A("**Handoff to the RTL:** the write sequence of section 4(b) as a specification: row-sequential, two phases, a 160-bit weight row giving both target masks, a 320-bit retired "
      "mask, three bias levels on the bitlines (0, V/2, V), the write/verify mode switch.\n")

    # ---- 8
    A("## 8. TO BE DETERMINED (updated list)\n")
    A("- **The device's switching thresholds, minimum switching time, forming** - 1D-ii (compact model).")
    A("- **Thick-oxide device data** (on-resistance x width, area per width, oxide rating): no card in PTM; the write-driver area (0.15-0.96 mm^2) rests on [ASSUM] values.")
    A("- **Write-rail regulator and decoupling** (a separate 1-2 V rail; ~8 nF for a fast 40 mA step [MODEL]).")
    A("- **Hot-carrier / oxide reliability of the 1.1 V access transistor at Vds 1.1-1.8 V during a SET** - the SET points above ~1.3 V are flagged as outside the rating, not as failing.")
    A("- Carried from 1C/1F: sigma_lnG (1D-ii), drift (1D-ii), wire / rail / driver resistance [ASSUM], comparator latch noise, threshold generator, the calibration procedure "
      "(now specified in section 5 as reads; the reference data are the freshly programmed weights).\n")

    # ---- 9
    A("## 9. Files and reproduction\n")
    A("```")
    A("python -m write.d1_parallel      # D1: delivery, droop, drivers, rails, parallelism, both polarities/orientations/word lines (~30 s on 24 cores)")
    A("python -m write.d1_transient     # D1/D2: the row-parallel write with the behavioural device in all 320 positions")
    A("python -m write.d2_unselected    # D2: floating / clamped / inhibited non-target bitlines")
    A("python -m write.d3_halfselect    # D3: device classes x bias schemes, 27 and 125 C")
    A("python -m write.d4_d5            # D4/D5: program time, energy, sequence, recalibration")
    A("python -m write.figures          # figures 22-24")
    A("python -m write.make_report      # this file")
    A("```")
    A("`write/rowdeck.py` (the row deck), `write/behav.py` (the behavioural device), `write/run.py` (DC / transient helpers). ngspice >= 38 is resolved by `spice/osdi.py` (PATH or nix).")
    RP.REPORT_1D_I.write_text("\n".join(L) + "\n")
    print("wrote", RP.REPORT_1D_I)


if __name__ == "__main__":
    main()
