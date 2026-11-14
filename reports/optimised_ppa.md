# Optimised PPA - open-source flow (Yosys, OpenROAD, OpenSTA, ngspice)

Everything here was produced with open-source tools only. No Genus, Innovus or Quantus script was written and nothing is deferred to them. Tags: **[RTL]** measured on the RTL regression, **[LAYOUT]** OpenROAD detail-routed netlist, **[POWER]** OpenSTA on the activity file of a gate-level simulation of that detail-routed netlist, **[1F]** ngspice, **[NSIM]** NeuroSim, **[MODEL]** analytic in code, **[ASSUM]** assumed.

**Power caveat, applies to every energy/power comparison below:** power is energy divided by latency, and NeuroHDC-small's samples are not the same length as ours (about 180k cycles for NeuroHDC against 311k cycles here for the early-exit design and 529k without early exit, on 407k events), so power is **not** like-for-like. **Energy per inference is the primary figure.**

**Exclusions are those of the earlier reports (`final_ppa.md`), unchanged:** not in the energy: glitch power (zero-delay activity), the weight load and write path (ReRAM is non-volatile), the calibration energy, analog static power, the supply regulator, host IO, and the idle bias of reads with no active row (assumed gated off - the a = 0 skip makes this true by construction here). Not in the area: pads, the I/O ring, the supply regulator, power-grid overhead beyond the macro's 20 %, the calibration store beyond 1F's count. In the energy now: the clock tree and the wire capacitance of the digital block (as in the 'with layout' table of `final_ppa.md`). No exclusion was changed, no friendlier window was picked and no pre-layout number is quoted as a result.

> **Superseded in part by [`operating_point.md`](operating_point.md) (second pass).** Doing the operating-point sweep with each point's own select transistor showed that this report evaluated the 541.8 ohm macro inconsistently: the area and write path assumed the 128 F cell, the read-path mesh, front-end noise, array energy and row-line study used the 20 F^2 cell's 1016 ohm transistor. With the 128 F transistor the row-gain residual is 9.5 % (budget 4.24 %), so the threshold correction of item 7 cannot be deleted at that macro, and the crossbar costs 2.02 uJ (1.74 with the new comparators) instead of 1.22 uJ: the consistent chip number for the 541.8 ohm macro is 5.09 uJ (4.80), not 4.29 uJ. The two-point 40 kohm study (section 6) is withdrawn: its front-end noise came from a process with stale array resistances. The timing, layout, power and regression results of this report are unaffected.

## 0. The answer

| | NeuroHDC-small | baseline (`final_ppa.md`, global-routed) | **this pass, full design** |
|---|---|---|---|
| energy per inference | 3.01 uJ | 14.72 uJ | **4.29 uJ** with the threshold correction deleted (item 7), **4.91 uJ** with the rank-1 fallback |
| average power (energy / latency) | about 1.67 mW (3.01 uJ over about 180k cycles) | 3.02 mW | 1.38 mW (3.11 ms, 311k cycles) / 1.58 mW - **not like-for-like, see caveat** |
| die area | 0.399 mm^2 | 1.218 mm^2 | **0.741 mm^2** |
| timing, detail-routed | - | fast +1.33 / slow -31.8 ns setup, hold -0.24 / -5.20 | **setup +3.58 / +0.04 ns, hold +0.150 / +0.153 ns (fast / slow), TNS 0 in both corners** |

**The energy target (3.01 uJ) is missed: 4.29 uJ is 1.43x (1.28 uJ over); the conservative 4.91 uJ is 1.63x. The area target (0.399 mm^2) is missed: 0.741 mm^2 is 1.86x.** The average power is below NeuroHDC's derived figure, but only because our run is longer; it is not a win.

The one configuration that meets the area target is the 40 kohm operating point (item 10): die 0.334 mm^2, but its energy is higher (5.1 to 6.4 uJ), so it is **not adopted** (section 6).

What closed: the digital block fell from 11.59 to 3.06 uJ (3.8x), the crossbar from 3.11 to 1.22 uJ (2.5x, rank 0) and timing closed in both corners for all four builds. What did not: the digital block alone (3.06 uJ) is above the whole 3.01 uJ budget, and the analog macro alone (0.586 mm^2) is above the whole 0.399 mm^2 budget. Section 4 breaks the gap down.

## 1. Timing, both corners, setup and hold, detail-routed [LAYOUT]

Corners: slow = 0.9 V / 125 C (setup), fast = 1.1 V / 0 C (hold); both checked for setup and hold in OpenSTA inside OpenROAD with propagated clocks. Parasitics are the PDK tech-LEF layer RC estimated from the routed wires (no coupling, no extraction). 100 MHz.

| build | slow setup WNS / TNS (ns) | slow hold WNS (ns) | fast setup WNS / TNS (ns) | fast hold WNS (ns) | detail route: residual DRC violations | die (mm^2) |
|---|---|---|---|---|---|---|
| full design | +0.040 / 0 | +0.153 | +3.581 / 0 | +0.150 | 18 (Metal2 spacing at a macro edge) | 0.741 |
| early exit OFF | +0.422 / 0 | +0.155 | +3.711 / 0 | +0.150 | 8 (same type) | 0.740 |
| factorization OFF | +0.995 / 0 | +0.154 | +3.605 / 0 | +0.150 | **0** | 1.057 (floorplan band, see section 8) |
| both OFF | +0.417 / 0 | +0.151 | +3.705 / 0 | +0.150 | 6 (same type) | 1.057 |
| 40 kohm point (item 10) | +0.403 / 0 | +0.178 | +3.477 / 0 | +0.150 | 30 (same type) | 0.334 |

Zero setup and hold violations in both corners for every build before any power number was taken. The residual DRC markers are all Metal2 spacing violations where a signal wire runs along the vertical edge of a macro obstruction; none touches timing. Two attempts to remove them (a 0.3 um routing keep-out beside the macros on Metal1-4, then Metal2-4) made the router worse (39 shorts with the standard cells' Metal1; then 1,132 violations at 30 % of the first iteration) and were reverted. They are listed in section 9.

Before: fast +1.33 / slow -31.8 ns setup, hold -0.24 / -5.20 ns, detail route not converged.

## 2. One line per item

Energy is per inference, full design, 100 MHz. The digital block is measured only for the whole pass (items 1, 3, 4, 5, 6 together; section 3 says why), the crossbar line is the stacked chain of `sense/energy_opt.py` at the RTL's 16,748 non-zero group reads per inference [RTL][1F].

| # | item | what was done and measured | energy after the item (uJ) | power (mW) | area (die, mm^2) |
|---|---|---|---|---|---|
| 0 | baseline | `final_ppa.md`: digital 11.59, crossbar 3.11, interface 0.02 | 14.72 | 3.02 (4.87 ms) | 1.218 |
| 1 | skip the a = 0 reads | the sequencer scans group-major and issues only non-zero group reads: 16,748 reads per inference instead of 61,622, so the cycle count falls from 486,963 to 310,860 together with item 4 (cycles at the same early-exit setting, [RTL] 720 samples) | combined with 3, 4, 5, 6 below | - | - |
| 2 | timing closure | slow-library synthesis (Yosys `abc -dont_use *XL *X1`), two-corner MCMM `repair_design` / `repair_timing` (setup and hold), global + detail route in one session: slow setup -31.8 -> +0.04 ns, hold -5.20 -> +0.153 ns, TNS 0, section 1 | (no energy change of its own; removes the 88 CTS delay buffers, about 0.31 mW, and the hold buffers' worth of the old tree) | - | - |
| 3 | `count_mem` as an SRAM macro | `count_sram` 1 kB, double-pumped single port (read on the rising, write on the falling edge), LEF + Liberty + behavioural model; **[ASSUM] CACTI 7, 45 nm LOP, 1 kB: 0.632 / 0.635 pJ per read / write, 15.5 uW leakage, 3,745 um^2**; 142 uW in the ingest window | - | - | - |
| 4 | restructure `shift_accum` | tree + one shift, pass-aware (two weight planes per 40-column pass), 40 columns per pass instead of 160: flip-flops 10,668 -> 1,941, cell area 205,722 -> 41,636 um^2, macro pins 2,178 -> 548 | - | - | - |
| 5 | clock tree and floorplan | coarser gating (gate-min 1), CTS without insertion delay, density 0.85, util 0.40: section 3.2 tables | - | - | - |
| 6 | tie off constant `m_o` bits | the macro's `m_o` holds only the 40 x W_M bits of the current pass, and the constant / unobserved outputs of the top level (`DEBUG_OUTPUTS`, constant bits) are removed from the netlist and tied off in the gate-level testbench; together with item 4 the macro pins fall 2,178 -> 548 | - | - | - |
| 1-6 | **digital block, measured together** | detail-routed `f_full`, ingest window 0.543 mW, scan window 2.46 mW (fast library), x 239,149 / 71,712 cycles | digital **3.06** (fast lib; **2.14** with the slow library's 0.9 V power) | 0.98 | 0.741 |
| 7 | delete the row-line threshold correction | the crossbar line, rank 0 (static per-column scale): 3.11 -> 1.95 uJ. Section 5.1 gives the implied metal width. Fallback rank 1: 2.58 | crossbar **1.95** (rank 1: 2.58) | - | - |
| 8 | front-end wake-up | (a) boost bias 0.42 V for 0.6 ns, ramp energy x 0.73, settles in 0.95 ns [1F ngspice]: 1.95 -> 1.70; (b) front-end kept powered across the 4 passes of a read, ramp paid 40x instead of 160x per read: -> **1.26** | crossbar **1.26** | - | - |
| 9 | bit-significance readout | per-weight-plane (bias, window) from the tolerated error of each plane (`plane_readout.json`, `lowbias.json`; planes 0-1 vb 0.52 V, planes 2-7 vb 0.50 V, T = 1 ns): -> **1.22** | crossbar **1.22** (rank 1 chain: 1.85) | - | - |
| 10 | operating point 40 kohm | evaluated side by side, section 6. **Not adopted** (energy-first rule): energy +0.8 to +2.1 uJ, die 0.334 mm^2 | adopted point unchanged | - | - |
| 11 | what the measurements pointed at | section 7 | - | - | - |
| | **final, full design** | digital 3.06 + crossbar 1.22 + level shifters 0.003 + class-HV 0.0005 | **4.29** (rank 1: 4.91) | **1.38** (1.58) over 3.11 ms | **0.741** |

## 3. Digital block

### 3.1 Four builds, detail-routed, power from the gate-level activity [POWER]

Power windows: sample row 46, timestep 10, from the RTL counters. `ing`: 2,400 cycles starting at cycle 44,339 inside the ingest phase; `mvm`: the non-ingest part of the timestep, 1,258 cycles starting at cycle 47,237 (timestep spans 4,458 cycles starting at 44,039, of which 3,196 ingest). **Annotation: 100 %** (every window, both libraries: 56,415 pins annotated / 0 unannotated for the full design; 53,270, 58,398, 55,736 for ee_off, fact_off, both_off). **The gate-level simulation is zero-delay: glitch power is excluded** (and every earlier number excluded it too). The gate-level run reproduced the RTL golden outputs for every build and window (`golden True`). The same window is used for all builds (it lies before any early exit), and one window stands for the whole run.

Energy = ingest power x events ingested / 100 MHz + scan power x (cycles - events) / 100 MHz, cycles and events being the RTL regression means over 720 samples (3 seeds x 240).

| build | accuracy | mean exit t | cycles | latency (ms) | ingest / scan power (mW), fast lib | digital (uJ) fast / slow lib | crossbar (uJ) rank 0 / rank 1 | level shifters + class HV (uJ) | **energy (uJ) rank 0 / rank 1** | avg power (mW) rank 0 / rank 1 | die (mm^2) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| full design | 80.42 % | 57.6 | 310,860 | 3.11 | 0.543 / 2.46 | 3.06 / 2.14 | 1.22 / 1.85 | 0.004 | **4.29 / 4.91** | 1.38 / 1.58 | 0.741 |
| early exit OFF | 80.42 % | 100.0 | 529,486 | 5.29 | 0.543 / 2.29 | 5.01 / 3.52 | 2.08 / 3.14 | 0.006 | **7.10 / 8.16** | 1.34 / 1.54 | 0.740 |
| factorization OFF | 82.36 % | 60.7 | 325,340 | 3.25 | 0.537 / 2.37 | 3.13 / 2.19 | 1.28 / 1.94 | 0.012 | **4.42 / 5.07** | 1.36 / 1.56 | 1.057 |
| both OFF | 82.36 % | 100.0 | 529,486 | 5.29 | 0.507 / 2.24 | 4.81 / 3.38 | 2.08 / 3.14 | 0.018 | **6.91 / 7.96** | 1.30 / 1.50 | 1.057 |

(Before this pass the four builds were 5.36 / 9.17 / 5.60 / 9.16 uJ pre-layout and only the full design had a layout, 14.72 uJ. The ranking of the builds is unchanged. Factorisation OFF is slightly more accurate and costs 0.13 uJ and 0.115 mm^2 of class-array macro [ASSUM, Phase 5 model]; early exit saves 2.8 uJ.)

Where the full design's 3.06 uJ goes: ingest 1.30 uJ (0.543 mW x 239,149 cycles) and scan 1.76 uJ (2.46 mW x 71,712 cycles). Inside the scan window: standard-cell logic 0.80 mW (32 %), wire-repair buffers 0.71 mW (29 %), clock tree 0.66 mW (27 %: leaf 0.27, root 0.19, mid 0.15, other 0.04), load-slew buffers 0.11 mW, hold buffers 0.10 mW, fanout buffers 0.02 mW, the macro instances (counter SRAM and crossbar boundary) 0.07 mW. Ingest window: clock root 0.19 mW (35 %), unnamed logic 0.13 mW, SRAM 0.14 mW, wire buffers 0.05 mW.

### 3.2 Item 5, clock tree and floorplan (tables from the runs; groute-stage power on the same netlist family, fast library, 100 MHz)

Gating granularity (`clockgate -min_net_size`, flops sharing one enable before an ICG is inserted):

| gate-min | ingest / scan (mW) | slow setup WNS (ns) | die (mm^2) |
|---|---|---|---|
| 1 (**chosen**, util 0.40) | 0.543 / 2.46 | +0.040 | 0.741 |
| 2 | 0.551 / 2.48 | not run to the same stage | 0.729 |
| 4 (util 0.45) | 0.625 / 2.50 | +0.325 | 0.729 |
| 8 | 0.649 / 2.56 | +0.135 | 0.729 |
| 16 | 1.120 / 2.87 | -0.398 | 0.732 |
| 32 | 1.200 / 2.99 | -0.002 | 0.733 |
| 64 | 1.220 / 3.01 | +0.402 | 0.733 |

Coarse gating loses: a gate with many flops behind it opens on any one of them and the whole tree under it toggles (ingest 0.54 -> 1.22 mW). The finest granularity is the best, at 0.04 ns of slow-corner setup margin (TNS 0). Gate-min 2 and 3 at util 0.40 give 0.495 / 2.40 and 0.577 / 2.41 mW but fail slow setup (-0.270, -0.075 ns), so gate-min 1 is the finest setting that closes.

Utilisation / density (same netlist, groute stage): util 0.40 / density 0.85 gives 0.543 / 2.46 mW (die 0.741); util 0.45 gives 0.621 / 2.51 (0.729) at gate-min 3 and 0.625 / 2.50 at gate-min 4; an earlier netlist at util 0.35 / density 0.70 gave 0.589 / 2.66 and at util 0.55 / density 0.90 the placer left 1.11 / 2.93 mW. **Compaction** (a narrower core under the macro, `--core-w 380` or 500): die 0.86 to 0.99 mm^2 and power 0.85 / 3.36 mW, i.e. worse on both: the wires of a tall narrow block cost more than the macro-edge wires they save, so the full-width strip stays. CTS: sink clustering 30 / 80 um -> 6 / 30 um and `-no_insertion_delay` (88 delay buffers, about 0.31 mW, removed) are what is left in `flow.tcl`. Region constraints: macros are pinned (`FIRM`), the standard cells sit in the strip against the macro's pin edge and the rest of the strip under the macro is a placement blockage.

### 3.3 Why items 1, 3, 4 and 6 have no separate power line

They change the architecture (the sequencer, the counter memory, the accumulator and the macro interface together), so each isolated step needs its own RTL variant, a gate-level testbench for that variant and a layout. The two snapshots of the old architecture that I did lay out (`p_c1` without and `p_c1_a0off` with the a = 0 skip) are timing-open (slow setup -9.6 and -4.8 ns at the global-route stage) and their gate-level run does **not** match the golden outputs in the current testbench (`golden False`), so under the rules for this pass their power cannot be quoted and is not. The combined measured step (11.59 -> 3.06 uJ) and the architecture metrics (cycles, flops, cell area, pins) are what is reported.

## 4. Final numbers against the targets, and the gap

| | NeuroHDC-small | this pass, full design, rank 0 | rank 1 | ratio (rank 0 / rank 1) |
|---|---|---|---|---|
| energy per inference | 3.01 uJ | 4.29 uJ | 4.91 uJ | 1.43x / 1.63x |
| die area | 0.399 mm^2 | 0.741 mm^2 | 0.741 | 1.86x |
| average power | about 1.67 mW | 1.38 mW | 1.58 mW | 0.83x / 0.94x - not like-for-like |

**Energy gap, 1.28 uJ (rank 0), is made of:**
- digital block 3.06 uJ, 1.30 ingest + 1.76 scan. This one term is already **above** NeuroHDC's whole 3.01 uJ, so the target cannot be met by the crossbar alone. Within the scan window 29 % of the power is wire-repair buffers, 27 % the clock tree and 32 % the logic; the ingest window is dominated by the clock root (35 %) and the counter SRAM (26 %).
- crossbar 1.22 uJ: sense bias 0.65, comparators 0.50, array + word line 0.08. The comparators are a fixed 30 pJ per non-zero group read ([1F]) that nothing in this pass touched.
- level shifters 0.003 uJ and class arrays 0.0005 uJ: negligible.

To reach 3.01 uJ with the crossbar as is, the digital block would have to fall below about 1.79 uJ (-42 %). With the ingest term (1.30 uJ) untouched that leaves 0.49 uJ for the scan: the scan power from 2.46 to about 0.68 mW at the same cycle count, or about 20,000 scan cycles instead of 71,712 at the same power. With the rank-1 fallback the digital block would have to fall to 1.16 uJ (-62 %).

**Area gap, 0.342 mm^2 (0.741 vs 0.399), is made of:** the analog macro 0.586 mm^2 (79 % of the die; 0.187 mm^2 more than NeuroHDC's whole chip: the 128 F select transistor that a 541.8 ohm LRS needs, section 6), the digital strip and margins 0.155 mm^2 (cells 0.042 mm^2 at util 0.40, the SRAM and class-array macros 0.011 mm^2, the rest whitespace and margins).

## 5. Item 7 and item 8-9 detail

### 5.1 Item 7, the threshold correction, and the metal width it implies [MODEL]

The correction removes the variation of the row-line gain with the group and the number of active rows. Mesh solve of the true macro (32 cells per row, both-end drivers, g = 4, 128 groups, driver 10 ohm), sweep of the row-line resistance per 128 F cell (`row_line_metal_sweep.json`): residual after a per-column scale only (rank 0) against the budget margin left at g = 4, **4.24 %**:

| row line, ohm per cell | gain spread | rank-0 residual | share of the 4.24 % margin | rank-1 residual |
|---|---|---|---|---|
| 18.43 (the model's 3.2 ohm/um at 128 F) | 80 % | 6.8 % | 161 % | 6.5 % |
| 4.97 (PDK Metal2-7 at its 70 nm minimum width, 0.0604 ohm/sq) | about 45 % | about 7 % | over | 5 % |
| 1.15 | 17 % | 4.06 % | 96 % | 1.9 % |
| 0.685 (PDK Metal9, 0.0214 ohm/sq, at its 0.18 um minimum width) | about 12 % | **about 3.3 %** | **about 77 %** | 1.3 % |
| 0.18 | 5.4 % | 2.1 % | 50 % | 0.35 % |

**Implied metal width for deleting the correction (rank 0): at least 0.30 um on Metal2-Metal7 (4.3x the 70 nm minimum, 1.15 ohm per cell, consuming 96 % of the margin), or the Metal9 minimum width of 0.18 um (0.685 ohm per cell, 77 % of the margin); with half the margin kept free it is 1.9 um on Metal2-Metal7 or 0.68 um on Metal9.** The 3.2 ohm/um the earlier model used corresponds to a wire of about 19 nm on Metal2-7, so it is pessimistic for this PDK; the PDK's Metal2-7 minimum-width row would need a rank-2 correction (about 5 ohm per cell).

I adopt rank 0 for the headline with the row line strapped on Metal9 at minimum width **[ASSUM: the array row line can be strapped on Metal9 across the 5.76 um cell, with a via per cell]**; the rank-1 chain (4.91 uJ) is the fallback if that margin consumption is not acceptable.

### 5.2 Items 8 and 9 [1F]

Item 8a: boosted wake-up, vb 0.42 V for 0.6 ns, peak 1.09 mA, ramp energy x 0.73, settle 0.95 ns. Item 8b: the 40 shared channels stay powered across the 4 passes of a read, so the ramp is paid 40x not 160x. Item 9: planes 0-1 tolerate p_err 0.9 % / 0.3 %, planes 2-7 need 3e-4 to 3e-6; planes 0-1 use vb 0.52 V, 2-7 vb 0.50 V, all T = 1 ns (0.18 / 0.23 pJ per column read): it saves 0.03 uJ only, because the per-read idle bias is already small after 8b.

| step | crossbar uJ, rank 0 | rank 1 |
|---|---|---|
| 1F baseline (rank 3) | 1.95 | 3.11 |
| + 7 (correction deleted / rank 1) | 1.95 | 2.58 |
| + 8a | 1.70 | 2.32 |
| + 8b | 1.26 | 1.88 |
| + 9 | **1.22** | **1.85** |

## 6. Item 10, the operating point (Ron = 40 kohm, 20 F^2 cell), side by side

Both points evaluated with the same machinery (device levels and spread, the row-line mesh at that LRS, the 1F front-end in ngspice with that array behind it, energy with the window T that makes 5 sigma of the front-end noise at most a quarter of the collected level step; NeuroSim area). `operating_point.json`, `operating_point_report.json`, `neurosim_op_point.json`.

| | 541.8 ohm, 128 F cell (adopted) | 40 kohm, 20 F^2 cell |
|---|---|---|
| level step | 125.4 uA | 3.22 uA |
| level spacing closes at sigma_lnG | up to 0.15 | up to 0.05 (fails at 0.10) |
| row-line gain spread | 12 % (needs the Metal9 strap, 5.1) | 0.6 %: no correction at all |
| noise-limited window T | 1 ns | 16 ns (vb 0.58 V) |
| cycles per pass | 1 | 2 (modelled; **the RTL was not changed to wait**) |
| crossbar energy (this method / adopted chain) | 0.70 / 1.22 uJ | 1.69 uJ (sense 1.15, comparators 0.50, array 0.05) |
| extra digital energy for the 66,993 wait cycles | - | 0.36 uJ (ingest-window power) to 1.65 uJ (scan power) |
| total energy | **4.29 uJ** | **5.12 to 6.40 uJ** |
| latency | 3.11 ms | 3.78 ms |
| analog macro | 0.586 mm^2 (layout), 0.583 (NeuroSim) | 0.173 (array-current decap) to 0.182 mm^2 (front-end idle current in the decap) |
| die, detail-routed layout | 0.741 mm^2 | **0.334 mm^2** (macro modelled at 0.190 mm^2, conservative; timing closed in both corners, 30 residual Metal2 DRC markers) |
| against NeuroHDC | 1.43x energy, 1.86x area | 1.7x to 2.1x energy, **0.84x area (meets it)** |

**Decision: not adopted.** The rule for this pass is energy first, and the 40 kohm point is worse on energy by 0.8 to 2.1 uJ (the 39x smaller level step needs a 16 ns integration window against 0.5 ns, which dominates) while winning area by 0.41 mm^2. It is the only configuration found that meets the 0.399 mm^2 area target; if area outranked energy it would be the one to take, with the caveats that its level spacing closes only to sigma_lnG 0.05, that the RTL does not implement the longer pass, and that item 9's per-plane relaxation was not applied to it (it would lower the 1.69 uJ somewhat).

## 7. Item 11, what the measurements pointed at

- **Tried and reverted (no gain):** operand isolation in the accumulator, a Y-commit variant of `shift_accum` (+220 flops, no energy gain), clock-domain gating (no gain, one extra setup failure).
- **Kept:** CTS without insertion delay (88 buffers, about 0.31 mW), `remove_buffers` + `buffer_ports` before the final repair (stopped a legaliser blow-up that had displaced cells by 33 um on average), groute and detail route in one session (a freshly reloaded database gave hold -0.268 ns from incomplete route data), pin placement restricted away from the macro side (2,178 -> 548 macro pins, which is what let the detail router converge), the unfactorised-class-array floorplan band and top-edge pins (section 8).
- **What is left, in order of size** (all in the full design's scan window): wire-repair, load-slew, hold and fanout buffers are 38 % of the scan power (the strip is 765 um wide because the macro sets the width, so row-to-macro wires are long); the clock tree is 27 %; the counter SRAM is 26 % of the ingest window; the comparators are 41 % of the crossbar energy and untouched.

## 8. Build-specific notes

- The factorisation-OFF builds carry a 338 x 340 um class-array macro. With the default floorplan the logic was squeezed into two side strips and 1.4 mm wires appeared (slow setup -57 ns). The floorplan now keeps a full-width cell band above any macro taller than 150 um and puts that macro's output pins on its top edge as well; this is why those two dies are 1.057 mm^2 (0.74 for the other two builds). The die is therefore not the minimum for those builds: the class array is 0.115 mm^2 and the rest is the band.
- PDN generation fails ("Unable to repair all channels") for some macro widths in the 40 kohm study (426 and 458 um); 190,000 um^2 (456 um wide) was used.
- The `snn_top.sv` declaration order of `cm_ready` and `sq_active` was changed (declared before the controller instance that reads them) because Icarus rejects use before declaration. No logic changed: the full build re-synthesises to the same 41,636 um^2 / 14,535 cells / 1,941 flops, the smoke check passes, and the whole regression below was run on the final source.

## 9. Updated TBD list

1. **Residual detail-route DRC markers** (full 18, early-exit-off 8, both-off 6, 40 kohm 30; factorisation-off 0): Metal2 spacing next to a macro edge. Two keep-out attempts made it worse. They do not affect timing.
2. **Parasitics** are the tech-LEF layer RC of the routed wires: no coupling capacitance, no field-solver extraction. There is no open-source extractor for this PDK; the wire RC dominates the digital power, so the digital energy has an error bar I cannot narrow (an earlier estimate: halving the wire RC would cut it by about a third).
3. **Power is from a zero-delay gate-level simulation** (no glitches), **one sample (row 46) and one timestep (10)** per build, two windows, 100 % pin annotation. The mean window power stands for the whole run.
4. **Memory macros are models**: LEF and Liberty generated by `gen_macros.py`, SRAM energy and leakage from CACTI 7 [ASSUM]; the class-array macro is a Phase 5 model [ASSUM]; the crossbar macro has no power model by design (its energy is the [1F] ngspice term).
5. **Level shifters** (480 up, 575 down) have no Liberty in the PDK: 4 fF x V^2 per toggle [ASSUM]; the interface wires are in the routed netlist's power.
6. **Item 7** assumes the row line can be strapped on Metal9 at its minimum width, with 77 % of the accuracy margin consumed (section 5.1).
7. **Item 10**: the longer pass is modelled, not built in the RTL; the extra digital energy is bounded by two power assumptions; the 40 kohm macro area is a model (NeuroSim cell + 1F front-end + a decap scaling with supply current), laid out at a rounded-up 0.190 mm^2.
8. **No per-item digital power** for items 1, 3, 4, 6 separately (section 3.3).
9. **Power versus NeuroHDC**: derived from 3.01 uJ over about 180k cycles; not like-for-like.
10. **Not analysed**: IR drop and electromigration of the power grid (a simple Metal1 / Metal10 / Metal11 grid, no decap cells in the PDK), signal integrity, process-corner Monte Carlo of the digital block, DFT, test.
11. **The slow-library energy** (2.14 uJ digital) is lower than the fast-library figure used for comparability (3.06 uJ) because the slow corner is 0.9 V; which one a silicon part would show is a voltage choice, not a tool result.

## 10. Verification

The full regression was run once on the final source (after the declaration-order fix of section 8), on both simulators; logs in `design/rtl/results/final_regression/` and `design/rtl/results/logs/final/`, results in `design/rtl/results/hdc_final2/`. Functional results are bit-identical: every run reports 0 mismatching samples against the Phase 0 golden model and 0 assertion messages.

| suite | simulator | runs | result |
|---|---|---|---|
| HDC matrix, main (all four builds x 3 seeds, g sweep, row-gap and timestep sweeps), 240 samples each | Verilator | 162 | 0 failed, 0 mismatching samples |
| HDC matrix, extra (abort modes, abort stress, c20 check ...), 240 samples each | Verilator | 41 | 0 failed |
| HDC matrix, main, 24 random rows each | Icarus | 24 | 0 failed |
| HDC matrix, extra, 24 random rows each | Icarus | 8 | 0 failed |
| the Icarus configurations, identical arguments | Verilator twins | 32 | 0 failed |
| SNN regressions (Levels 4 and 5, g sweep 4 to 64, 20 / 40 / 160 columns, gaps, N-MNIST) | Verilator, all samples | 19 | 0 mismatching, 0 access-estimate mismatches |
| the same configurations on 48-sample subsets | Icarus | 19 | 0 mismatching; Verilator against Icarus **AGREE** on every timestep (19 of 19, 0 disagreements) |
| cocotb unit tests (every module, g sweep, column modes) | Verilator and Icarus | 61 cases each | all pass (Icarus `mvm_unit_g512` after the testbench fix below); the g-sweep X identical across 22 runs / 9 vectors on both |
| gate-level simulation of each detail-routed netlist, ingest and scan windows | Icarus (netlist) | 4 builds x 2 windows | matches the RTL golden outputs (`golden True`), section 3.1 |

- **Re-run on the final source against the earlier run** (the one before the declaration-order fix): 215 result files compared sample by sample (prediction, exit timestep, events, cycles, reads, raster hash): **0 differ**. The smoke check also shows 53 timesteps identical to the reference in every functional field.
- **Cross-simulator and cross-configuration comparison (`hdc_compare_all.py`): 47 AGREE, 6 DISAGREE.** The 6 are `abortmode_vs_reload` and `abortstress_vs_reload` for the three seeds. They differ **only in cycle-accounting columns, always by exactly 459 cycles**: the first timestep's cycle and ingest-cycle counters, the sample's total cycles and one stall counter (+459), against the reload-cycle counter (0 against 2777). 459 cycles is the counter memory's clear sweep after a flush: after an abort it falls in the first timestep of the next sample, in a reset-and-reload run it falls in the reload phase. Predictions, scores, exit timesteps, spike rasters and every other field are identical on all lines. The comparator's skip set covers the reload counter only, so it reports a disagreement; I left the comparator as it was. The same 6 appear when the comparator is run on the earlier results.
- **Two testbench problems found and fixed in this pass, neither in the design:** `snn_top.sv` used `cm_ready` and `sq_active` before declaring them, which Icarus rejects (declaration moved up, netlist unchanged); `mvm_unit.sv` sliced the group index with a zero width at g = 512 on Icarus (the unit-test log in `final_regression/unit_tests.log` still shows the failed Icarus `mvm_unit_g512` case from before that fix; it passes after it, re-run on its own).
- **Not run as part of this regression:** the layouts' own gate-level runs use one sample and two windows (section 9, item 3); the 40 kohm layout has no power run.
