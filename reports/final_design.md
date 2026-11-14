# Final design: theta-free, dataset-independent (v5)

Open-source tools only (Yosys, OpenROAD, OpenSTA, ngspice, NeuroSim), 45 nm, 100 MHz. One chip, one configuration for both datasets: **no early exit, no theta**. The earlier early-exit design is kept in `final_design_early_exit.md`.

## Result against NeuroHDC-small (layout `s7`)

| | DVS-Gesture, ours | DVS-Gesture, NeuroHDC-small | N-MNIST, ours | N-MNIST, NeuroHDC-small |
|---|---|---|---|---|
| accuracy | 80.42 % (80.83 / 81.67 / 78.75, bit-exact, 3 seeds x 240) | 87.5 % published; 82.36 % our bit-exact reimplementation | 95.00 % (bit-exact, 1,000 samples) | 97.28 % published; 94.91 % our bit-exact reimplementation |
| energy, digital at 0.9 V (timing sign-off corner) | **3.01 uJ** (3.0097) | 3.01 uJ | **0.194 uJ** | 0.315 uJ |
| energy, digital at 1.1 V (fast corner) | 3.75 uJ | | 0.236 uJ | |
| die area | **0.3810 mm^2** | 0.399 mm^2 | **0.3810 mm^2** | 0.399 mm^2 |
| latency | **1.380 ms** | 1.8 ms | **66.9 us** | 80.77 us |

Paper values from its Table III, scaled by its authors to 45 nm with Stillmaker & Baas (nominal supply). The crossbar (1.04 uJ DVS, 0.093 uJ N-MNIST) is costed at its 1.1 V analog supply in both rows. Energy is **provisional**: global-route parasitics, no detail route.

**Which energy row to compare.** Timing is signed off at the slow corner, 0.9 V and 125 C, with +0.223 ns setup slack at 100 MHz, so the digital logic runs at 0.9 V with margin. The 0.9 V row uses that same slow library for power. It is pessimistic in two respects: slow process, and leakage at 125 C. No typical 0.9 V library exists in the PDK. The 1.1 V row is the fast corner (1.1 V, 0 C), the basis of all earlier reports. Count-SRAM energies (CACTI) are not voltage-scaled in either row.

**Against the paper:** N-MNIST wins energy (-38 % at 0.9 V, -25 % at 1.1 V), area (-4.5 %) and latency (-17 %). DVS-Gesture wins area and latency (-23 %); its energy equals the paper at 0.9 V and is 25 % higher at 1.1 V.

DVS-Gesture energy split at 0.9 V: crossbar 1.04 uJ (10.3k reads x 100.3 pJ), scan-side digital 0.79 uJ (41.3k passes x 19.1 pJ), ingest 0.87 uJ (407k events x 2.13 pJ), per-cycle baseline 0.32 uJ (138.0k cycles x 2.31 pJ: clock trunk and leakage, 111 uW of it the 24 count-SRAM macros).

**Correction to the previous report:** the crossbar cost of 83.28 pJ per read assumed the read statistics of fixed row groups (1.6 active rows, 1.47 comparator decisions). Packed reads are mostly full: 3.65 active rows and 2.77 decisions at 4 rows per read, which cost 97.7 pJ. The previous design (`r14`) was therefore 4.24 uJ DVS, not 4.05.

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
- **Analog assumptions not simulated:** (1) rows packed within a band differ by under about 2 % in row gain; (2) program-verify with 4 averaged reads reaches sigma_LRS 0.045 (Phase 1D-ii model); (3) partial reads cost a full read; (4) the shared-channel analog mux (10 um^2 per column) is not designed; (5) decoder area 1,500 um^2 per row decoder.
- **SRAM model** [ASSUM]: CACTI 7, generic ITRS 45 nm LOP, 256 B macro: 1,130 um^2, read 0.284 pJ, write 0.340 pJ, leakage 4.64 uW. The macro abstract blocks Metal1-4 only.
- DVS-Gesture cycle counts use the 20 real event streams plus synthetic shuffled streams for the remaining rows (`golden.synth_events`). N-MNIST power windows use a rank-1 approximation of the class image; the SNN activity is exact.
