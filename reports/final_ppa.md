# Final PPA - digital block, analog block, chip

Tags: **[SIM]** simulated (Yosys + OpenSTA on the PDK library, gate-level Icarus activity), **[RTL]** measured on the RTL regression, **[1F]** ngspice (carried forward), **[NSIM]** NeuroSim V1.4 run for this design, **[MODEL]** analytic in code, **[ASSUM]** assumed, **PENDING** = needs the owner's licensed tools and has NOT been produced or estimated. Numbers are read from `design/rtl/results/ppa_digital/`, `design/rtl/synth/results/` by `design/rtl/synth/final_ppa.py`; commands in section 8. Companions: [`digital_energy.md`](digital_energy.md), [`phase5_ppa.md`](phase5_ppa.md).

## 0. The answer, and what is missing

**Status: the digital block has been placed, clock-tree-synthesised and global-routed with OpenROAD (open source) on this PDK, for the FULL design only; the numbers below are the global-routed (OpenROAD) stage.** They are not Innovus + Quantus signoff numbers: parasitics are estimated from the PDK's LEF layer RC (no coupling, no field-solver extraction), the netlist is the Yosys one with no physical synthesis, and the other three builds were not run. The owner's Genus / Innovus / Quantus flow (section 7) is prepared and not yet run. Cells that no tool has produced are marked PENDING and are never estimated.

- **D1(a) The PDK has a usable clock-gating cell.** `TLATNCAX2` (and X12, X16, X20) are in `fast_vdd1v0_basicCells.lib` with `clock_gating_integrated_cell : "latch_posedge"` and the enable / clock / output pins marked; the design's 738 clock gates are real library cells. **The library the pre-route numbers used is the PDK's, byte for byte** (checked by SHA-1 against `45_nm_PDK/.../lib/*.lib`): the earlier 'lab 45 nm' library and this PDK are the same files, so re-synthesising against the PDK with Yosys would reproduce the pre-route numbers exactly; the genuinely new synthesis is Genus (section 7, step 2).
- **Analog macro area is NOT 0.429 mm^2 once the select transistor is sized for the write path: 0.583 mm^2** (36% more). 1C's analytic number at the 20 F^2 cell it assumed is 0.4289 mm^2; NeuroSim **refuses** the 20 F^2 cell (its own transistor model needs a 39.8 F wide select transistor for a 541.8 ohm LRS) and at its smallest feasible cell (40 F wide) gives 0.4272 mm^2 - within 0.4 % of 1C, a corroboration - but at the 128 F cell the write path needs it gives 0.5833 mm^2. **The chip-level number uses 0.583 mm^2** (the larger).
- **The interface is not free: 16.1 pJ per group read (range 9.9-22.3 for 300-700 um wires), 0.99 uJ per inference at the mean 61,622 reads = 32% of the crossbar read energy**, plus 11,679 um^2 of level shifters (480 up, 575 down).
- **Chip, pre-layout, full design (g = 4): 5.36 uJ per inference, 0.92 mm^2, 4.87 ms** against NeuroHDC-small's 3.01 uJ and 0.399 mm^2 (1.78x energy, 2.30x area). The analog macro alone (0.58 mm^2) is 1.46x NeuroHDC's whole chip: **the area comparison is decided by the crossbar's select transistors, not by the digital design.**
- **With the OpenROAD layout (global-routed) the digital block stops being negligible: 11.6 uJ per inference (pre-layout 1.26), chip 14.7 uJ and a 1.22 mm^2 die** (4.9x and 3.1x NeuroHDC-small). Window power goes 0.41 -> 1.90 mW when the wires are added and -> 3.24 mW with the clock tree (clock group 0.04 -> 1.30 mW). **Timing: the fast corner closes (1.33 ns), the slow corner does not (-31.8 ns); hold is violated (-0.24 ns fast).** Cell area grew 71% through the tool's buffering and resizing of Yosys' minimum-size mapping. Caveats that move these numbers (section 9): wire RC is the LEF's (if every switching term scaled with it and it were half, the digital energy would be ~7.5 uJ), the netlist was not physically synthesised, detailed routing did not converge in the time available, and only the full build was run. **The pre-route 0.147 mW is not a chip number.**
- **Largest term now (with the layout): the digital block, 11.6 of 14.7 uJ (79%)** - wires and the clock tree - then the crossbar reads (3.11 uJ, 186 pJ per read [1F]). For area it is the analog macro (select-transistor-limited array + decoupling). Next optimisation, in order: (1) physically-aware synthesis / sizing and a real extraction to replace the minimum-size netlist and the LEF RC; (2) the digital floorplan: the count memory's 512-way structure spreads over the die (mean net 31 um, 3,000 nets > 200 um) - a placement-aware restructuring of `count_mem` / `shift_accum` is worth more than further gating; (3) fewer, shorter clock sub-trees (738 gated branches cost a 1.3 mW tree); (4) for the crossbar, 1G and the select transistor.

## 1. PPA table - digital block

| metric (full design) | pre-route (measured, ideal clock, no wires) | with layout (OpenROAD, global-routed) | how |
|---|---|---|---|
| standard-cell area (incl. buffers added by the tool) | 205,722 um^2 (0.2057 mm^2) | **351,913 um^2** (0.3519 mm^2; 71% more) | [SIM] Yosys flat / OpenROAD netlist cell areas |
| flip-flops / clock gates (ICG) / CLKBUF+CLKINV added after placement (CTS, repair) | 9,930 / 738 / 0 | 9,930 / 738 / 3,546 | [SIM] |
| die area; standard-cell density of the digital region | not defined (assumed 65 % in the first chip estimate) | die 823 x 1480 um = 1.218 mm^2 (the crossbar macro 0.583 + digital region + margins); OpenROAD reports 87.0 % of the core filled | OpenROAD floorplan (util target 0.42 before buffering) |
| standard-cell density of the digital region | assumed 65 % | 71% (cells incl. added buffers / region under the macro) | OpenROAD placement |
| timing at 100 MHz: worst setup slack, fast / slow corner | 8.01 / 1.76 ns (ideal clocks, no wires) | **1.33 / -31.8 ns** (slow-corner TNS -31229 ns) | OpenSTA in OpenROAD, propagated clocks, LEF-derived RC |
| hold: worst slack, fast / slow | not checked (ideal clock) | -0.236 / -5.20 ns | same |
| clock skew (setup skew, fast corner) | 0 (ideal clock) | 1.222 ns | CTS: before / after in section 3 |
| power, read-phase window (560 cycles) | 0.407 mW | **3.240 mW** | OpenSTA + gate-level VCD (+ wire C post-layout) |
| power, ingest-only window (2,400 cycles) | 0.105 mW | **1.490 mW** | same |
|   of which clock group, read-phase window | 0.030 mW (8,000-cycle window) | 1.300 mW | CTS buffers + clock wires |
| digital energy per inference (phase-resolved, g = 4 cycles) | 1.26 uJ  (486,963 cycles at 100 MHz) | **11.59 uJ** (includes the macro-boundary wires, 0.26 uJ of it) | power x cycles |
| pipeline check: the same numbers through `layout_analysis.py` | area 205,722 um^2, window power all 0.147 mW, ing 0.105 mW, mvm 0.407 mW | - | reproduces the table above |

All four builds, pre-route; the layout columns exist for the full design only (OpenROAD, section 7), the others are PENDING:

| build | cell area (um^2) | flops | slack fast / slow (ns) | power (mW) | ingest / read (mW) | digital E / inf (uJ) | with layout: cell area (um^2) | with layout: ingest / read power (mW) |
|---|---|---|---|---|---|---|---|---|
| full design | 205,722 | 10,668 | 8.01 / 1.76 | 0.147 | 0.105 / 0.407 | 1.26 | 351,913 | 1.490 / 3.240 |
| early exit OFF | 199,298 | 10,654 | 7.99 / 1.73 | 0.145 | 0.105 / 0.400 | 2.15 | **PENDING (not run)** | **PENDING (not run)** |
| factorization OFF | 193,367 | 9,504 | 8.01 / 1.91 | 0.141 | 0.100 / 0.396 | 1.28 | **PENDING (not run)** | **PENDING (not run)** |
| both OFF | 198,367 | 9,490 | 7.99 / 1.69 | 0.141 | 0.100 / 0.401 | 2.14 | **PENDING (not run)** | **PENDING (not run)** |

## 2. PPA table - analog block (crossbar macro: 5 x 512 x 32, 2T2R, with its front-end and decoupling)

| metric | value | assumption / source |
|---|---|---|
| area, 1C analytic | 0.4289 mm^2 | 20 F^2 1T1R cell (1A-1C), 1F front-end, 1 nF decap, 20 % overhead [MODEL] (Phase 5's number) |
| area, NeuroSim, smallest feasible cell | 0.4272 mm^2 | 40 F x 4 F cell (160 F^2); NeuroSim rejects 20 F^2: 'Transistor width of 1T1R=39.79F is larger than the assigned cell width=5.00F' [NSIM] |
| **area, NeuroSim, 128 F cell (chip-level choice)** | **0.5833 mm^2** (763 x 764 um macro) | 128 F x 4 F cell = the select-transistor width the write path needs (1D) [NSIM] + 1F front-end + 1 nF decap + 20 % overhead |
|   of which cell arrays (5 macros) | 0.1699 mm^2 | NeuroSim: 5 x 33,974 um^2 = 512 x 64 x 512 F^2 x (45 nm)^2 per macro (1C had 0.0066 mm^2 in total) |
|   of which NeuroSim row / source-line drivers + column mux | 0.0444 mm^2 | NeuroSim periphery for rows / columns (its sense circuits are NOT used) |
|   of which 1F front-end (sense, ladder, calibration, straps) | 0.1052 mm^2 | 1F, 'mid' (NeuroSim's generic MLSA / ADC is not the regulated current conveyor that was designed) |
|   of which 1 nF supply decoupling | 0.1667 mm^2 | 1F; the PDK has no decap cells, so P&R inserts none: not double counted |
| class-HV array macro (factorized / unfactorized) | 0.0074 / 0.1149 mm^2 | Phase 5 model [ASSUM]; never designed |
| read energy | 186 pJ per non-zero group read (g = 4, T = 1 ns) -> 3.11 uJ per inference | [1F] ngspice on the actual front-end, x [RTL] non-zero reads; reported as the macro's energy |
| read time | settles in 130-160 ps inside a 1 ns + 0.3 ns window | [1F]; digital sees it as clk -> output 0.3 ns (Liberty arc in `macro/*.lib`) |
| static power | not modelled (excluded as in Phase 5) | NeuroSim lists 79 uW per macro for its generic periphery; not our circuit |
| interface (digital <-> analog) | 16.1 pJ per group read (9.9-22.3); 0.99 uJ per inference | section 4 [MODEL] + measured activity |
| Liberty power model | none, by design | its energy depends on active rows and the data; kept as the separate 186 pJ term |

### Area: both cell assumptions, side by side

| variant | cell array | row / column periphery | 1F front-end | decap | overhead 20 % | total (mm^2) |
|---|---|---|---|---|---|---|
| 1C analytic, 20 F^2 | 0.0066 | 0.0789 | 0.1052 | 0.1667 | 0.0715 | **0.4289** |
| NeuroSim, 40 F x 4 F | 0.0531 | 0.0310 | 0.1052 | 0.1667 | 0.0712 | **0.4272** |
| NeuroSim, 128 F x 4 F | 0.1699 | 0.0444 | 0.1052 | 0.1667 | 0.0972 | **0.5833** |

1C's row periphery is sized per micrometre of row line (`driver_um2_per_um`) for the short rows of a 20 F^2 cell; NeuroSim's does not grow with the cell width (4,539 um^2 per macro in both NeuroSim variants). If 1C's per-length driver model were applied to the 128 F rows (25.6x longer) the periphery would be larger than NeuroSim's - this is an open item (section 9), not hidden: the chip number takes NeuroSim's.

### NeuroSim read energy against 1F (D5)

| term (per full 160-column group read, g = 4) | NeuroSim [NSIM] | 1F [1F] | ratio |
|---|---|---|---|
| array + word line | 29.9 pJ (5 macros x 5.98) | 4.5 pJ | 6.6x |
| sensing (comparators, bias, threshold / NeuroSim: MLSA + encoder + adders) | 7,515 pJ | 181.5 pJ | 41x |
| total | 7,515 pJ | 186 pJ | 40x |

**1F's 186 pJ is the number reported.** NeuroSim's total is ~40x larger and does not corroborate it: over 95 % of NeuroSim's energy is its generic 3-bit multi-level sense amplifiers (8 shared read circuits per macro, each a 7-comparator ladder behind a column mux - set by the driver's `levelOutput = 8`, `numColMuxed = 8`, so the comparison depends on those two choices) and its digital accumulation; neither circuit exists in the design, whose per-column regulated conveyor and 1-bit comparators were simulated in ngspice (1F). The one term that is comparable, the array and word line, is 6.6x higher in NeuroSim (30 against 4.5 pJ), and the direction is expected: at 128 F the rows are 26x longer than 1F's 20 F^2 geometry assumed (NeuroSim: 74 fF per row, 320 fF per column), so array energy grows with the select-transistor width as the area does - a second consequence of the same finding (the factor is NeuroSim's model, not a measurement). NeuroSim's latency output for this configuration is not meaningful (it returns 1.0e12 ns) and is not used.

## 3. D1(c): the clock tree - before and after CTS (full design, read-phase window of the same sample)

| stage | clock cells | clock-group power (mW) | total power (mW) | setup skew |
|---|---|---|---|---|
| pre-route: Yosys netlist, ideal clock, no wires | 738 ICG, no tree | 0.0403 | 0.407 | 0 (ideal) |
| placed, before CTS (OpenROAD) | 738 ICG, +0 CLKBUF/CLKINV vs placed | 0.0403 | 1.900 | -0.839 ns |
| after CTS (OpenROAD) | 738 ICG, +3,546 CLKBUF/CLKINV vs placed | 1.2400 | 3.130 | 1.189 ns |
| global-routed (OpenROAD) | 738 ICG, +3,546 CLKBUF/CLKINV vs placed | 1.3000 | 3.240 | 1.222 ns |
| routed (OpenROAD) | **PENDING (not run)** | **PENDING (not run)** | **PENDING (not run)** | **PENDING (not run)** |

**The CTS delta:** the clock-group power goes from 0.040 mW (738 ICGs, ideal clock) to 1.240 mW after CTS (31x): the clock tree (437+ delay/balance buffers, sink clustering, the wire capacitance of 738 gated sub-trees spread over a 823 x 1480 um die) is 40% of the post-CTS power. Wires alone (placed, before CTS) already take the window from 0.41 to 1.90 mW (switching on wire capacitance; the pre-route numbers had pin capacitance only).

## 4. D3: the interface (previously zero)

| item | value | basis |
|---|---|---|
| wires crossing the boundary | 480 count outputs (160 columns x 3 bits at g = 4) + 512 row selects + 63 control/write = 1055 | RTL ports; 1,120 of the RTL's 1,600 `m_o` bits are constant zero at g = 4 (counts 0..4) and would be tied off |
| wire capacitance | 0.416 fF/um (Metal4), 0.416 fF/um (Metal6) | PDK tech LEF: CPERSQDIST x width + 2 x EDGECAPACITANCE |
| wire length | 300 / 500 / 700 um (short / nominal / long) | macro 763 um on a side, digital region ~542 um [ASSUM] until Innovus routes it |
| activity (measured) | outputs 0.125 toggles / wire / read; row select 0.0026 | gate-level VCD, 564 reads in a 1200-cycle read-phase window; g = 8 netlist applied to g = 4 |
| energy per group read | 16.1 pJ nominal (9.9 - 22.3) | alpha x (C V^2 + level shifter) |
| energy per inference | 0.99 uJ (full), x 61,622 reads | all reads, empty ones included (as built) |
| level shifters | 480 low->high + 575 high->low = 11,679 um^2 | PDK LEF sizes (LSLHX1_TO, LSHLX1_FROM); **no Liberty in the PDK** -> their energy (4 fF x V^2 per toggle) is [ASSUM] |

## 5. D4: chip numbers (pre-layout table first, then the full design with the OpenROAD layout)

| build (g = 4) | accuracy | mean exit t | cycles | latency (ms) | digital (uJ) | crossbar reads (uJ) | interface (uJ) | class arrays (uJ) | **energy (uJ)** | digital area / 0.65 (mm^2) | analog macro (mm^2) | class-HV macro (mm^2) | **area (mm^2)** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| full design | 80.42% | 57.6 | 486,963 | 4.87 | 1.26 | 3.11 | 0.99 | 0.0005 | **5.36** | 0.316 | 0.583 | 0.007 | **0.919** |
| early exit OFF | 80.42% | 100.0 | 838,141 | 8.38 | 2.15 | 5.29 | 1.72 | 0.0008 | **9.17** | 0.307 | 0.583 | 0.007 | **0.909** |
| factorization OFF | 82.36% | 60.7 | 511,181 | 5.11 | 1.28 | 3.26 | 1.04 | 0.0087 | **5.60** | 0.297 | 0.583 | 0.115 | **1.007** |
| both OFF | 82.36% | 100.0 | 838,141 | 8.38 | 2.14 | 5.29 | 1.72 | 0.0144 | **9.16** | 0.305 | 0.583 | 0.115 | **1.015** |


**Full design with the OpenROAD layout (global-routed (OpenROAD)):**

| quantity | pre-layout (section above) | with layout | note |
|---|---|---|---|
| digital energy per inference | 1.26 uJ | **11.59 uJ** | ingest-window power x event cycles + read-window power x the rest; includes the wires of the macro boundary (0.26 uJ) |
| crossbar reads | 3.11 uJ | 3.11 uJ | [1F] x [RTL], unchanged |
| interface: boundary wires | 0.99 uJ (assumed 500 um wires) | 0.26 uJ, already inside the digital line | OpenROAD wire C of the 992 boundary nets x measured transitions (`interface_routed_*.json`) |
| interface: level shifters | (inside the 0.99) | 0.02 uJ | [ASSUM] 4 fF x V^2 per toggle; the PDK has no Liberty for them |
| class-HV arrays | 0.0005 uJ | 0.0005 uJ | Phase 5 model |
| **energy per inference** | **5.36 uJ** | **14.72 uJ** | 4.9x NeuroHDC-small's 3.01 uJ |
| chip area | 0.919 mm^2 (digital cells / 0.65 + macros) | **1.218 mm^2** die (no pads) | 3.1x NeuroHDC-small's 0.399 mm^2; digital cells 0.352 + macros 0.591 + margins/whitespace |
| latency | 4.87 ms | 4.87 ms | 100 MHz closes in the fast corner only (section 1) |

**How to read the jump from 1.26 to 11.6 uJ of digital energy.** The pre-route power had pin capacitance only (no wires) and an ideal clock. With the layout the switching power sits on wire capacitance (0.42 fF/um from the PDK's LEF: area plus fringe, no coupling - without a field-solver extraction it may be off by about 2x either way) and the clock tree adds 1.30 mW in the read phase. The netlist is Yosys' minimum-size mapping, not a physically-synthesised one: its weak cells are what makes the slow corner fail and the repair buffers swell the area by 71 %. A physically-aware synthesis (Genus) and a real extraction (Quantus) are expected to land lower; this table shows what an open-source flow does with the netlist as it stands, and that the pre-route 0.147 mW should not be quoted as a chip number.
NeuroHDC-small: 0.399 mm^2, 3.01 uJ, 100 MHz, 45 nm, DVS-Gesture (post-layout, with clock tree and SRAM macros). Latency = cycles / 100 MHz (a pre-route clock; the post-route clock is the same 100 MHz if timing closes). Digital area in the pre-layout table = standard-cell area / an *assumed* 65 % utilisation (the layout table uses the die); level shifters add 0.0117 mm^2; the chip area has no pads and no I/O ring. **Previous (digital_energy.md) energy was 4.37 uJ; the interface adds 0.99 uJ.**

**Exclusions, named as in the previous reports.** Not in the energy of the pre-layout table: the clock tree (it is in the 'with layout' table); glitch power (zero-delay activity), the weight load and write path (ReRAM is non-volatile), the calibration energy, analog static power, the supply regulator, host IO, the idle bias of reads with no active row (assumed gated off). Not in the area: pads, the I/O ring, the supply regulator, power-grid overhead beyond the macro's 20 %, place-and-route whitespace beyond the assumed utilisation, the 6.4 kbit calibration store only as 1F counted it.

## 6. What is now the largest term, and what to attack next

- **Energy with the layout (14.7 uJ):** digital 11.6 (79%), crossbar reads 3.11 (21%), level shifters 0.02. Inside the digital 11.6 uJ the macro-boundary wires are 0.26 uJ - small; the rest is wire capacitance of the logic and the clock tree. Before the layout the order was crossbar reads (3.11) > digital (1.26) > interface.
  Attack, in order: (1) a physically-aware synthesis and a real extraction (the current digital number is an upper-ish estimate from a minimum-size netlist and LEF RC - expect it to fall; this is the first thing to redo with Genus + Innovus + Quantus); (2) the structure that makes the wires long - `count_mem`'s 512-way read mux and the 1,600-flop partial-count register spread over the whole region (mean net 31 um, ~3,000 nets over 200 um): restructure for locality before gating any more; (3) the clock: 738 gated branches cost a ~1.3 mW tree in the read phase - fewer, larger gating groups; (4) then 1G for the crossbar.
- **Area (0.92 mm^2 pre-layout; 1.22 mm^2 die):** the analog macro 0.58 mm^2; inside it the cell arrays (0.17 mm^2) and the 1 nF decoupling (0.17 mm^2). Next: the select transistor (1D's write-current requirement fixes it at 128 F); decoupling per 1F's droop budget; segmenting the write driver from the read path. The die also carries the digital region at ~72 % density after buffering; it shrinks if the buffering does.

## 7. How the numbers were produced, and what the owner can still run

**Run in this repository (open-source tools only): the OpenROAD flow, full design only.** From `design/rtl/synth/`:

```
python analog_macros.py ; python neurosim/run_neurosim.py            # macro areas, LEF / Liberty, NeuroSim
python prepare_rtl.py --build full ; python make_floorplan_params.py --build full --util 0.42 ; python openroad/make_pnr_netlist.py --build full
OPENROAD=<path to openroad> openroad/run_flow.sh full                # floorplan (macro first), place, CTS, global route   (OpenROAD built from source: not in Homebrew)
python openroad/analyze_openroad.py --stage pre_cts|post_cts|groute --build full --windows ing mvm     # timing both corners, skew, power windows, area
python openroad/interface_routed.py --stage groute --build full        # the macro-boundary wires with their placed capacitances
python final_ppa.py
```

What these runs are NOT: **detailed routing was started (TritonRoute) and stopped after ~35 minutes at 164,000 violations after its second pass**, so the 'routed' column is global-routed wiring, not DRC-clean detailed routing. **Parasitics are the PDK LEF's layer RC** applied to the estimated wiring (no coupling, no extraction; OpenRCX needs a rules file the PDK does not ship, and the PDK's QRC technology file is for Quantus). The tech LEF needed six device-level via rules removed for the router (`openroad/sanitize_tech_lef.py`; the PDK file is untouched). The OpenROAD flow, the macro LEF, the floorplan and the analysis scripts are all reproducible from the repository plus the binary.

**Prepared but not run (needs the owner's licences):** Genus synthesis, Innovus place / CTS / route, Quantus extraction - the same flow with signoff tools. Inputs are ready and checked as far as possible without them (the prepared RTL elaborates in Yosys with the macros and the ICG as library cells; `layout_analysis.py` analyses their netlist / SPEF / DEF with no licence):

```
python prepare_rtl.py --build $B && python make_floorplan_params.py --build $B            # B = full ee_off fact_off both_off
BUILD=$B genus -batch -files genus/run_genus.tcl
BUILD=$B WORK=$PWD/work/$B innovus -batch -files innovus/run_innovus.tcl
for S in pre_cts post_cts routed; do python layout_analysis.py --stage $S --build $B --netlist results/innovus/$B/$S.v --spef results/innovus/$B/$S.spef --def results/innovus/$B/$S.def ; done
python final_ppa.py
```

The Genus and Innovus scripts are modelled on the PDK's own examples and **have never been executed**: adapt option names to your tool versions. Not produced anywhere: SDF-annotated simulation (the PDK ships no Verilog cell models with specify blocks; power uses zero-delay gate-level activity plus estimated wire capacitance), GDS / DRC / LVS signoff, the other three builds' layouts.

## 8. Files

`synth/analog_macros.py` (areas, LEF, Liberty) - `synth/neurosim/` (driver + runner; NeuroSim itself is cloned outside the repository, CC BY-NC) - `synth/interface_model.py` - `synth/prepare_rtl.py`, `make_floorplan_params.py`, `openroad/` (`run_flow.sh`, `run_flow.tcl`, `make_pnr_netlist.py`, `sanitize_tech_lef.py`, `analyze_openroad.py`, `interface_routed.py`), `genus/`, `innovus/`, `constraints/`, `pdk.tcl` - `synth/layout_analysis.py` - `synth/final_ppa.py`. Results: `synth/results/{neurosim,analog_area,analog_macros,interface,interface_routed_*}.json`, `synth/results/layout/full/{pre_cts,post_cts,groute}/summary.json`, `synth/results/openroad/full/` (logs, stage netlists / DEFs / reports; the .odb databases are large and regenerable).

## 9. Updated TO BE DETERMINED list

- **Everything post-layout is from an open-source flow with LEF-derived RC on a Yosys minimum-size netlist.** The numbers to expect from Genus + Innovus + Quantus are lower for area and power (sized cells, real extraction) and may differ in sign for timing; run them (section 7) before quoting a chip number.
- **Slow-corner timing does not close** (about -30 ns here) and hold is violated by 0.2 ns (fast) / ~5 ns (slow): the minimum-size cells need sizing for the slow corner (max-transition violations on ~25,000 nets in the slow library). Needs a slow-corner-aware synthesis.
- **Detailed routing did not converge** (164,000 violations after pass 2 of ~17 min each); the 2,178-pin macro edge (0.4 um pitch on Metal4/Metal6) and the congested count-memory region are the suspects. Needs a floorplan / pin-pitch iteration or a tool with the signoff router.
- **Only the full design was laid out.** The other three builds' layout numbers are PENDING; their pre-layout numbers are in the tables.
- **Row-driver sizing at the 128 F cell:** NeuroSim's periphery does not grow with the cell width; 1C's per-length model would. The analog macro could be larger than 0.583 mm^2.
- **NeuroSim parameters:** HP device roadmap, ADC levels 8, column mux 8, cell height 4 F, write voltage below the level-shifter threshold, F = 45 nm. The array number rests on 'widthInFeatureSize1T1R = 128' (1D's SET-current requirement).
- **Interface:** activity is the g = 8 netlist's; level-shifter energy is assumed (no Liberty); the 1,120 constant-zero count bits are not yet tied off in the digital design; in the layout numbers the boundary wires are inside the digital line (not added twice).
- **Digital netlist parameterisation:** ROWS_PER_GROUP = 8 (package default) as in every pre-route number; cycle counts are the g = 4 RTL runs.
- **Power activity** is zero-delay (no glitches), from one sample (row 46) and two windows (ingest, read phase); the earlier sampling caveats carry over.
- **Decap:** 1F's 1 nF is inside the macro; the digital region's own decoupling and the power grid's IR drop are not modelled; the PDK has no decap cells.
- Still open from Phase 5: class-HV arrays are scaled models; the 1F energy model's own items; no pads / I/O ring; two corners of one library.
