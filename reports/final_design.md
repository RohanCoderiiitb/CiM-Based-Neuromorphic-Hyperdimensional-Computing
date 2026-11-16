# Final design: theta-free, dataset-independent (v5)

Open-source tools only (Yosys, OpenROAD, OpenSTA, ngspice, NeuroSim), 45 nm, 100 MHz. Two chips from one RTL: the small chip (one configuration for DVS-Gesture and N-MNIST, against NeuroHDC-small) and the large chip (ASL-DVS, against NeuroHDC-large). **No early exit, no theta.** The earlier early-exit design is kept in `final_design_early_exit.md`.

## Result against NeuroHDC-small (layout `s7`)

| | DVS-Gesture, ours | DVS-Gesture, NeuroHDC-small | N-MNIST, ours | N-MNIST, NeuroHDC-small |
|---|---|---|---|---|
| accuracy | 80.42 % (80.83 / 81.67 / 78.75, bit-exact, 3 seeds x 240) | 87.5 % published; 82.36 % our bit-exact reimplementation | 95.00 % (bit-exact, 1,000 samples) | 97.28 % published; 94.91 % our bit-exact reimplementation |
| energy, digital at 0.9 V (timing sign-off corner) | **3.01 uJ** (3.0097) | 3.01 uJ | **0.194 uJ** | 0.315 uJ |
| energy, digital at 1.1 V (fast corner) | 3.75 uJ | | 0.236 uJ | |
| die area | **0.3810 mm^2** | 0.399 mm^2 | **0.3810 mm^2** | 0.399 mm^2 |
| latency | **1.380 ms** | 1.8 ms | **66.9 us** | 80.77 us |
| throughput (1 / latency; no gap between samples) | 725 samples/s | | 14,940 samples/s | |

Paper values from its Table III, scaled by its authors to 45 nm with Stillmaker & Baas (nominal supply). The crossbar (1.04 uJ DVS, 0.093 uJ N-MNIST) is costed at its 1.1 V analog supply in both rows. Energy is **provisional**: global-route parasitics, no detail route.

**Which energy row to compare.** Timing is signed off at the slow corner, 0.9 V and 125 C, with +0.223 ns setup slack at 100 MHz, so the digital logic runs at 0.9 V with margin. The 0.9 V row uses that same slow library for power. It is pessimistic in two respects: slow process, and leakage at 125 C. No typical 0.9 V library exists in the PDK. The 1.1 V row is the fast corner (1.1 V, 0 C), the basis of all earlier reports. Count-SRAM energies (CACTI) are not voltage-scaled in either row.

**Against the paper:** N-MNIST wins energy (-38 % at 0.9 V, -25 % at 1.1 V), area (-4.5 %) and latency (-17 %). DVS-Gesture wins area and latency (-23 %); its energy equals the paper at 0.9 V and is 25 % higher at 1.1 V.

DVS-Gesture energy split at 0.9 V: crossbar 1.04 uJ (10.3k reads x 100.3 pJ), scan-side digital 0.79 uJ (41.3k passes x 19.1 pJ), ingest 0.87 uJ (407k events x 2.13 pJ), per-cycle baseline 0.32 uJ (138.0k cycles x 2.31 pJ: clock trunk and leakage, 111 uW of it the 24 count-SRAM macros).

**Correction to the previous report:** the crossbar cost of 83.28 pJ per read assumed the read statistics of fixed row groups (1.6 active rows, 1.47 comparator decisions). Packed reads are mostly full: 3.65 active rows and 2.77 decisions at 4 rows per read, which cost 97.7 pJ. The previous design (`r14`) was therefore 4.24 uJ DVS, not 4.05.

## Result against NeuroHDC-large (ASL-DVS, layout `L73`)

| | ASL-DVS, ours (large chip) | ASL-DVS, NeuroHDC-large |
|---|---|---|
| accuracy | 88.02 % (88.29 / 87.92 / 87.84, 3 seeds, full 21,591-sample test split) | 89.38 % |
| energy, digital at 0.9 V (timing sign-off corner) | **0.823 uJ** (-20.4 %) | 1.034 uJ |
| energy, digital at 1.1 V (fast corner) | 0.988 uJ (-4.5 %) | |
| die area | **0.9229 mm^2** (-21.9 %) | 1.182 mm^2 |
| latency | **152.3 us** (-45.7 %) | 280.2 us |
| throughput | 6,568 samples/s | |

Paper values from its Table III, scaled by its authors to 45 nm (as above). Energy is **provisional**: global-route parasitics, no detail route. The crossbar (0.408 uJ) is costed at its 1.1 V analog supply in both rows.

**Chip.** The same architecture and RTL as the small chip, generated with package overrides only (`design/rtl/scripts/make_large_rtl.py` -> `design/rtl_large`, never edited by hand):
- 40 neurons: 320 crossbar columns, 10 weight macros, 80 shared sense channels.
- 24 class slots, held in an unfactorized class store. The R=1 factorized store reaches only about 64.5 % validation accuracy on 24 classes.
- 12-bit event counters: ASL-DVS cell counts reach 3,913.
- A 240 x 180 second sensor geometry (17-bit AER word).

**Class store: CACTI 7, 960-bit word.** One macro of 128 rows x 960 b, of which 100 rows are used; it reads one 40 x 24 slice per timestep. Settings: ITRS LOP cells and periphery, 45 nm, 350 K, minimum area (`design/rtl/synth/opt/cacti/class_960b.cfg`). Results:
- area 0.1263 mm^2 (473 x 267 um);
- read 22.2 pJ, write 30.4 pJ;
- leakage 236 uW;
- access time 1.11 ns, so outputs launch 1.23 ns after the clock.

The same settings reproduce the earlier 1 kB counter point (`ref_1kB.cfg`): access time exact, area / energy / leakage within 10 %. The previous report scaled a 1 kB point by bits (0.044 mm^2, 182 uW), which under-counted area by about 3x. The macro stands rotated (MYR90) against the right edge, with its pin edge facing the logic.

**Accuracy.** Unfactorized NeuroHDC-large model, trained with the frozen recipe. Data: DAVIS240C recordings cut into 100 ms windows, 107,955 samples, random 80/20 split (seed 0). Integer accuracy equals float accuracy on the whole test split. The RTL is bit-exact on 2,000 real event streams x 3 seeds (tags `H_asl_s0..2`, no assertion fires).

**Energy split at 0.9 V.**
- Crossbar: 0.408 uJ (2,138 packed reads x 190.9 pJ at 80 channels, `studies/crossbar/scaleup/packed_reads_large.py`).
- Scan-side digital: 0.318 uJ.
- Ingest: 0.023 uJ (21.5k events x 1.08 pJ).
- Per-cycle baseline: 0.075 uJ (15.2k cycles x 4.90 pJ).

The idle power is 0.490 mW at 0.9 V. At 1.1 V it is 0.568 mW, of which 236.5 uW is the class-store leakage.

**Area.** Die 666 x 1385 um. Crossbar macro 0.418 mm^2 (NeuroSim 0.403 mm^2 + 15,000 um^2 decoders [ASSUM]). Class store 0.127 mm^2. 24 count SRAMs 0.028 mm^2. Standard cells about 0.149 mm^2.

**Timing (global route, both corners, independent OpenSTA check):** slow setup +0.400 ns, hold +0.076 ns; fast setup +3.709 ns, hold +0.050 ns. Zero violations at 100 MHz.

**Timing fixes in the large chip.** All are package switches (0 on the small chip, which is unchanged: identical cycles and spike rasters). Every fix is bit-exact.
- `AGREE_PIPE`: the per-class agree counts are registered before the accumulate. This adds one query cycle per timestep, but it is mostly hidden behind ingest: +4.3 cycles per sample on average.
- `TOP2_QUARTERS`: the first top-2 tournament stage registers four quarters, and the second stage merges four winners. Same cycles, same result.
- `EXIT_CLK_FREE`: the exit controller runs on the free clock.
- `LOCAL_QUERY_BUSY`, which brings:
  - a local replica of the query-busy flags in the top;
  - a free-clock copy of the spike-valid flop for the intake hold;
  - one copy of the counter-set select per lane in `count_mem`.
  Each is asserted equal to the original in simulation.

**Flow** (all opt-in options of `design/rtl/synth/opt/flow.tcl` / `fp.py`):
- timing-driven global placement (`GPL_TD`);
- placement density 0.65, utilisation 0.41;
- repair with a 500 um maximum wire length (`RD_OPTS`);
- the counter SRAM block raised to 55 % of the free height (`FP_CNT_YFRAC`), between the event pins and the plane sequencer;
- global-route repair margins setup 0.4 ns, hold 0.05 ns.

`fp.py` now refuses a floorplan whose class store overlaps the counter block.

**Crossbar read Monte Carlo** (`studies/crossbar/scaleup/mc_packed_read.py`, results in `studies/crossbar/results/macro_512x32/mc_packed_read.json`). This replaces the analytic 5-sigma check and the "row gains match to ~2 %" assumption with an end-to-end simulation of each 5-row packed read:
- every device drawn log-normal at the program-verify sigma_lnG;
- every row its own IR-drop gain, uniform over the WHOLE-macro spread of 1.55 % without calibration (also 0 %, 2 % and 4 %);
- front-end noise at its design limit (5 sigma = 1/4 step);
- the validated Newton column solver and the nearest-level ladder.

Results:
- **0 errors in 10 million reads** at sigma_lnG 0.0453 and at 0.066 (drift-inflated), for every gain spread: below 3 x 10^-7 per read at 95 % confidence, i.e. under a 0.06 % chance of any read error per ASL-DVS inference (2,138 reads).
- The worst read lands 0.72 half-steps from its correct level at 0.0453, 0.94 at 0.066; 1.0 would be an error.
- The detector is checked: errors appear at sigma_lnG 0.08 (1 x 10^-6) and 0.15 (7.5 x 10^-4).

The reported (bit-exact) accuracies therefore hold for the analog read.

**Large-chip caveats.**
- **Max-slew violations remain (slow corner, library limit 0.28 ns).** There are 2,393 violating pins (the previous layout `L43` had 4,831; `s7` has 634).
  - 124 are more than 0.5 ns over the limit.
  - 22 are more than 1 ns over, up to 4.1 ns. These are about 11 nets driven by buffers inserted in the final timing repair (query-score XNOR inputs), plus one clock-gate pin in `count_mem`.
  - STA includes these slews: the setup and hold results above are computed with them.
- **Energy fit.** The per-cycle term is anchored to the measured idle power. The five ASL-DVS windows fit within 4.4 %. Reproduce with `~/.cache/cim_neurohdc/eval_large.sh L73 H`.

## What changed since v4 (all bit-exact against the golden model)

- **5 rows per crossbar read** (was 4). Reads: DVS 12.5k -> 10.3k, N-MNIST 1.12k -> 1.00k. Device spread at the program-verify floor: 5 sigma reaches 0.83 of the half level step (4 rows: 0.76). The same margin policy as the 4-row design (closure with a 0.021 drift allowance above the floor) needs program-verify with 4 averaged verify reads (sigma_LRS 0.045, Phase 1D-ii). That costs programming time only. The macro grows to 0.2142 mm^2 plus 7,500 um^2 for five row decoders, because decoupling scales with peak array current. 6 rows (0.2349 mm^2) would erase the area win.
- **Pass-major read groups.** When a group finishes, every packer holding a full read loads at once (up to 3 reads). The group issues analog pass 0 of each read, then pass 1, and so on, so the neuron lanes keep the same neurons for several cycles. This also removed issue bubbles: N-MNIST 7,463 -> 6,693 cycles.
- **Count memory:** the read is issued straight from the accepted event (the SRAM registers its own address); the input stage register is gone.
- **HDC top-2 tournament in two cycles** (halves registered, then merged). This lets the layout close at utilisation 0.65. The query stage is busy 6 cycles per timestep instead of 5.
- **Floorplan and flow:** SRAM rows lane-major; utilisation 0.65; CTS sink clustering 30 / 160 um / 200 um; global-route repair margins setup 0.2 ns, hold 0.05 ns (were 0.4 / 0.15). Hold buffers 751 -> 114.

Kept from v4: lane-private event counters (3 lanes x 2 sets x 4 banks of 128 x 16 b SRAM), per-lane dirty flags, clear on completion, packed-row reads, sparse ping-pong scan, scan/config/HDC clock domains, registered abort and ingest enable.

## Layout (`s7`)

Die 489.8 x 777.8 um = 0.3810 mm^2: crossbar macro 221,700 um^2 (shared-channel, 5 row decoders), 24 count SRAMs as a 4 x 6 block, digital standard cells 51.4k um^2 at utilisation 0.65. Global route, both corners: slow setup +0.223 ns, hold +0.132 ns; fast setup +4.078 ns, hold +0.051 ns; zero violations.

## Power method

Gate-level simulation of the global-route netlist, five SAIF windows (three DVS-Gesture, two N-MNIST) plus an idle window (intake closed). OpenSTA with global-route SPEF, `report_power -digits 7`. Energy model `E = c0*cycles + e_ev*events + e_rd*passes`. c0 is the measured idle power per cycle at each library: the free three-term fit is ill-conditioned, because the DVS windows are ingest-saturated at a fixed events/cycle ratio, and it went negative. The free fit gives DVS totals within 0.1 uJ of the anchored one; the anchored values are reported. The model is applied to the per-sample counts of the RTL regression (tags `w16_*`). Crossbar: `studies/crossbar/scaleup/packed_reads.py` (3.5 kohm, 1 ns window cap, the packed read population of each dataset at 5 rows: DVS 100.3 pJ, N-MNIST 92.9 pJ per read).

Reproduce: `~/.cache/cim_neurohdc/eval2.sh s7 w16` (`design/rtl/synth/opt/power2.py`, `power_prof.py`, `refit.py`, `energy_v2.py`; outputs `work/opt/s7/energy_{fast,slow}_idle.json`). Attribution: `opt/power_prof.py`, `opt/buf_trace.py`, `opt/icg_prof.py`.

## Caveats

- **Provisional parasitics.** No layout of this design has finished detail route; power uses global-route parasitics. The 0.2 ns setup margin is the guard for detail-route degradation.
- **0.9 V basis:** the slow library is not a typical-corner 0.9 V library; level shifting between the 0.9 V digital domain and the 1.1 V analog macro is costed as before (0.004 uJ [ASSUM]).
- **Analog assumptions.** Simulated now: row-gain spread and device spread, together with front-end noise, in an end-to-end Monte Carlo of the packed read (see the large-chip section). It finds 0 errors in 10 million reads at sigma_lnG 0.0453 and 0.066. Still assumed: (1) program-verify with 4 averaged reads reaches sigma_LRS 0.045 (Phase 1D-ii model); (2) partial reads cost a full read; (3) the shared-channel analog mux (10 um^2 per column) is not designed; (4) decoder area 1,500 um^2 per row decoder; (5) temperature, read-time crosstalk and drift beyond sigma_lnG 0.066 are not simulated.
- **SRAM model** [ASSUM]: CACTI 7, generic ITRS 45 nm LOP, 256 B macro: 1,130 um^2, read 0.284 pJ, write 0.340 pJ, leakage 4.64 uW. The macro abstract blocks Metal1-4 only.
- DVS-Gesture cycle counts use the 20 real event streams plus synthetic shuffled streams for the remaining rows (`golden.synth_events`). N-MNIST power windows use a rank-1 approximation of the class image; the SNN activity is exact.
