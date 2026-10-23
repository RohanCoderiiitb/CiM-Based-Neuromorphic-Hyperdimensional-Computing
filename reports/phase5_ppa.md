# Phase 5 report - synthesis, power, and the combined PPA of the complete accelerator

Tags: **[SIM]** simulated (Yosys + OpenSTA on the 45 nm library, gate-level Icarus for the activity; ngspice in 1C/1F), **[RTL]** measured on the RTL regression (the read counts, the exit timestep), **[1F]** carried forward from [`phase1f_report.md`](phase1f_report.md) unchanged, **[MODEL]** analytic in code, **[ASSUM]** assumed (section 8). Every number is read from `design/rtl/results/ppa/*.json` by `design/rtl/scripts/make_report_ppa.py`; commands in section 9. Companion: [`phase234_report.md`](phase234_report.md).

## 0. The answer

- **Timing: the 100 MHz clock closes, and 1E's 67-gate path needs no pipelining - provided the mapping buffers high-fanout nets.** With the mapping the FFT project used (Yosys `abc` without buffering) the worst register-to-register path misses by 2.69 ns (minimum period 12.7 ns); the first 7.2 ns of it are two unbuffered nets (a flip-flop driving a 512-wide select at 2.3 ns clock-to-Q and an `INVX1` at 5.0 ns), not the popcount-then-add. With `abc -D` and a driving-cell / load constraint (fanout buffering and sizing, +4.9 % area) the minimum period is **2.01 ns at the fast corner and 8.12 ns at the slow corner** of the same library: slack 1.8 ns at 10 ns in the slow corner. 1E's RTL is unchanged. Pre-layout: no clock tree, no wire load, no P&R.
- **Digital area 0.235 mm^2 (full design), 10,584 flip-flops** (45 nm, buffered mapping); 0.226 mm^2 without the factorization; the early-exit comparator and FSM are 285 um^2 (0.11% of the digital area, below the synthesis noise of the flat totals - the flat total of the early-exit-OFF build is not smaller; the attribution is by module, section 2).
- **Digital power 3.31 mW as designed - and it is 89% flip-flop clock energy**: gate-level activity annotates 287,342 of 287,342 pins (100 %), and 1E's 10,584 flip-flops - about 5.6k of them the count memory - are clocked every cycle (no clock gating). At ~2.8 fJ per flop per clock edge that is the whole story: the logic's switching power is 0.15 mW.
- **THE NUMBER THAT MATTERS - energy per inference at the measured exit timestep** (recommended point g = 4, 40 columns per pass, T = 1 ns; mean of 3 seeds x 240 samples): full design **19.23 uJ at the exit (mean exit timestep 57.6)** against 33.03 uJ with the same network run to the end - **42% saved**; the analog crossbar part alone 3.11 against 5.29 uJ. NeuroHDC-small: 3.01 uJ. **Energy is not read-dominated in this implementation**: at the exit the split is crossbar reads 3.11, digital 16.12, class-HV arrays 0.000 uJ; the early exit saves both because both scale with the cycles and the reads up to the exit, but the project's central argument - reads are the dominant term - holds for the analog side, not for the chip as built (section 4.3).
- **What the number is made of, and what could move it (section 4.3):** as built 19.2 uJ; with the a = 0 reads removed from the cycle count (1E/1F follow-up, not implemented) 13.3 uJ; adding ideal clock gating (a measured-activity *bound*, not a design) 4.3 uJ = 1.4x NeuroHDC-small. The first-order lever is the digital clock, then the empty reads; early exit multiplies whatever is left by ~0.58.
- **Against NeuroHDC-small (0.399 mm^2, 3.01 uJ, 100 MHz, 45 nm, DVS-Gesture):** area 0.671 mm^2 (1.68x), energy 19.23 uJ (6.39x). Both comparisons are unfavourable by construction in the exclusions below.
- **Recommended operating point:** g = 4, 40 columns per pass (4 passes), read pulse T = 1 ns (+ 0.3 ns tail), 1 nF supply decoupling, the R=1 factorized class hypervector, early exit at threshold **50** (the strict knee of the R=1 model, accuracy 80.42%), 100 MHz. g = 8 closes the margin budget only for sigma_lnG <= 0.07 (1F) and is reported alongside.

## 1. What is and is not in these numbers

| part | how | tag |
|---|---|---|
| digital logic (1E SNN + query + exit) | Yosys 0.69 + abc to the Cadence 45 nm `fast_vdd1v0_basicCells.lib` (1.1 V), flattened, `abc -D 10000 -constr` (driving cell BUFX2, load 0.02 pF); OpenSTA 3.1.0 for timing and power | [SIM] |
| digital power | gate-level simulation of the synthesized netlist (Icarus, liberty cells as Verilog models, the analog arrays as their behavioural models) on a real DVS-Gesture sample, an 8,000-cycle window starting at cycle 12,000 (timesteps ~3-5); the VCD annotates every pin; `report_power`. Checked against the golden model (spikes, X, V, scores of the timesteps the run completes: post-synthesis equivalence) | [SIM] |
| SNN crossbar reads | non-zero group reads per inference measured on the RTL up to the exit; energy per non-zero read from 1F: 186 pJ (g = 4, T = 1 ns), 228 pJ (g = 8, T = 2 ns); a = 0 reads draw nothing (recorded, not implemented) | [RTL] x [1F] |
| class-HV arrays | reads priced from 1F's per-column read cost, area from 1C's per-row and 1F's per-column parts (never designed) | [ASSUM] / [MODEL] |
| SNN array area | 1F's table (mid), with the 1 nF decoupling of the recommended point | [1F] |
| cycles | RTL cycles at 160 columns per read + (passes - 1) per group read (validated against the RTL's own 20-column run, section 4.4) | [RTL] + [MODEL] |

**Exclusions (named plainly, as 1C and 1F did).** Not in the energy: the clock tree and the clock network (ideal clock; with one the sequential term grows), wire capacitance of the digital logic, the supply regulator and decoupling-capacitor leakage, the calibration energy (recalibration every ~5 K), the write/program path and the weight load (ReRAM is non-volatile; the RTL's reload after an exit is a model artefact and is excluded), the host/IO interface, SRAM-style leakage of the analog arrays at rest, and the idle bias of reads with no active row (assumed gated off; sensitivity in 4.2). Not in the area: place-and-route overhead and utilisation, pads, the clock tree, the supply regulator, decoupling beyond 1 nF, and the 6.4 kbit calibration store (1F). NeuroHDC-small's figures are a whole accelerator including its clock tree and SRAM macros at a stated 100 MHz; ours is the same function with the weight memory in ReRAM and a pre-layout digital part.

## 2. (a) Synthesis

| build | area, FFT-flow mapping (um^2) | min period, FFT-flow mapping (ns) | area, buffered mapping (um^2) | flip-flops | cells | min period fast corner (ns) | slack @ 10 ns fast (ns) | min period slow corner (ns) | slack @ 10 ns slow (ns) | worst I/O slack @ 10 ns (ns) |
|---|---|---|---|---|---|---|---|---|---|---|
| full design | 223,948 | 12.69 | 234,969 | 10,584 | 79,249 | 2.01 | 7.99 | 8.12 | 1.77 | 4.95 |
| early exit OFF | 225,533 | 12.88 | 236,554 | 10,570 | 79,524 | 2.06 | 7.95 | 8.08 | 1.81 | 4.91 |
| factorization OFF | 215,241 | 12.73 | 226,071 | 9,527 | 78,395 | 2.01 | 7.99 | 8.00 | 1.89 | 4.95 |
| both OFF | 216,947 | 13.12 | 227,735 | 9,513 | 78,156 | 2.10 | 7.90 | 8.22 | 1.67 | 4.91 |

'Min period' is the worst register-to-register arrival + setup (the analog arrays' outputs launch 0.3 ns after the clock edge [ASSUM]); the I/O column is the worst port-to-port path with input and output delays of period/4. The four builds elaborate with `check -assert` clean and zero latches in generic Yosys as well (`results/synthesis/hdc_*`), longest topological path 68 gates in all four (1E: 67).

**1E's 67-gate path.** The FFT-flow mapping's worst path starts at a flip-flop whose output drives the 512-wide bit-row select (clock-to-Q 2.27 ns) and an `INVX1` with the same fanout (4.97 ns): 7.2 ns before the logic starts; the 40-odd levels of popcount and fold take the remaining 5.4 ns. Fanout buffering removes the 7.2 ns, and the register-to-register path is then the popcount-then-add itself at 1.99 ns (fast corner) - far inside 10 ns, so **registering the popcount (one extra cycle per MVM) is not needed and was not done**; 1E's RTL is unchanged. If a flow without fanout buffering must be used, pipelining the popcount would not fix the 7 ns of unbuffered fanout either.

### Area by module (full design, hierarchical synthesis, same library and mapping)

| module | area (um^2) | share | variants/instances |
|---|---|---|---|
| shift_accum | 114,780 | 46.5% | 1 |
| count_mem | 88,299 | 35.7% | 1 |
| hdc_query | 13,608 | 5.5% | 1 |
| if_neuron_array | 11,293 | 4.6% | 1 |
| snn_ctrl | 5,758 | 2.3% | 1 |
| snn_top | 4,208 | 1.7% | 1 |
| plane_seq | 2,224 | 0.9% | 1 |
| top2_tree | 2,105 | 0.9% | 9 |
| addr_gen | 1,410 | 0.6% | 1 |
| hdc_score | 1,178 | 0.5% | 1 |
| event_ctr | 984 | 0.4% | 1 |
| popcount | 403 | 0.2% | 14 |
| exit_ctrl | 285 | 0.1% | 1 |
| spike_reg | 271 | 0.1% | 1 |
| cim_neurohdc_top | 149 | 0.1% | 1 |
| weight_load | 144 | 0.1% | 1 |

(Hierarchical total 247,098 um^2 against the flattened 234,969: cross-module optimisation.) The query stage is `hdc_query` + `hdc_score` + `top2_tree` + `exit_ctrl` = 17,176 um^2 (7.0%); the SNN is the rest, `shift_accum` (46%, the two 512-bit popcounts and the 160-column fold) and `count_mem` (36%, 5,632 flip-flops) dominating.

### Power (a)

| build | total (mW) | sequential (mW) | combinational (mW) | of which switching (mW) | leakage (uW) | pins annotated | gate level == golden over timesteps |
|---|---|---|---|---|---|---|---|
| full design | 3.310 | 2.930 | 0.375 | 0.155 | 12.4 | 287,342 / 287,342 | 5 (yes) |
| early exit OFF | 3.310 | 2.930 | 0.378 | 0.155 | 12.5 | 288,250 / 288,250 | 5 (yes) |
| factorization OFF | 3.020 | 2.640 | 0.380 | 0.157 | 12.0 | 282,724 / 282,724 | 5 (yes) |
| both OFF | 3.010 | 2.640 | 0.376 | 0.155 | 12.1 | 282,364 / 282,364 | 5 (yes) |

**Clock-gating headroom (measured, not applied).** In the 8,000-cycle window of the full build 2,959 of 10,584 flip-flops ever change value, and the total number of Q transitions is 262,491 against 84,672,000 flop-cycles: an average of 0.0031 transitions per flop per cycle. An ideally clock-gated implementation needs a clock edge only when a flop changes: its sequential power would be bounded below by about 0.009 mW (= 2.93 mW x the activity) instead of 2.93 mW. That is a bound, not a design (clock-gating cells, their enable timing and the clock-tree would eat part of it); it is stated so that the energy tables can show both, section 4.3.

| module (instance prefix) | flip-flops | ever change in the window | Q transitions |
|---|---|---|---|
| u_snn.u_count_mem | 5,663 | 982 | 77,070 |
| u_snn.u_shift_accum | 1,605 | 1,124 | 94,090 |
| u_query | 1,072 | 6 | 12 |
| v_o | 520 | 223 | 271 |
| x_o | 420 | 397 | 2,561 |
| u_snn.u_ctrl | 197 | 58 | 47,551 |
| scores_o | 110 | 53 | 66 |
| ts_cycles_ingest_o | 32 | 3 | 6 |
| ts_cycles_o | 32 | 2 | 4 |
| ts_fwd_o | 32 | 5 | 6 |
| ts_zero_groups_o | 32 | 1 | 1 |
| ts_reads_issued_o | 32 | 0 | 0 |
| ts_reads_plane_o | 32 | 0 | 0 |
| ts_reads_allcols_o | 32 | 0 | 0 |
| ts_rows_read_o | 32 | 0 | 0 |
| ts_rows_skipped_o | 32 | 0 | 0 |
| ts_events_o | 32 | 4 | 8 |
| u_snn.sq_issued | 32 | 10 | 2,304 |
| u_snn.sq_plane | 32 | 10 | 2,304 |
| u_snn.sq_allcols | 32 | 10 | 2,304 |
| u_snn.sq_rows | 32 | 4 | 36 |
| u_snn.sq_skipped | 32 | 2 | 8 |
| u_snn.u_event_ctr | 22 | 18 | 31,453 |
| u_snn.ev_n | 21 | 0 | 0 |
| spike_o | 20 | 4 | 4 |
| u_snn.neuron_spike | 20 | 4 | 4 |
| u_snn.thresh_q[19] | 15 | 0 | 0 |
| u_snn.thresh_q[18] | 15 | 0 | 0 |
| u_snn.thresh_q[17] | 15 | 0 | 0 |
| u_snn.thresh_q[16] | 15 | 0 | 0 |
| u_snn.thresh_q[15] | 15 | 0 | 0 |
| u_snn.thresh_q[14] | 15 | 0 | 0 |
| u_snn.thresh_q[13] | 15 | 0 | 0 |
| u_snn.thresh_q[12] | 15 | 0 | 0 |
| u_snn.thresh_q[11] | 15 | 0 | 0 |
| u_snn.thresh_q[10] | 15 | 0 | 0 |
| u_snn.thresh_q[9] | 15 | 0 | 0 |
| u_snn.thresh_q[8] | 15 | 0 | 0 |
| u_snn.thresh_q[7] | 15 | 0 | 0 |
| u_snn.thresh_q[6] | 15 | 0 | 0 |
| u_snn.thresh_q[5] | 15 | 0 | 0 |
| u_snn.thresh_q[4] | 15 | 0 | 0 |
| u_snn.thresh_q[3] | 15 | 0 | 0 |
| u_snn.thresh_q[2] | 15 | 0 | 0 |
| u_snn.thresh_q[1] | 15 | 0 | 0 |
| u_snn.thresh_q[0] | 15 | 0 | 0 |
| theta_q | 12 | 0 | 0 |
| u_snn.u_weight_load | 12 | 0 | 0 |
| top2_o | 11 | 6 | 7 |
| top1_o | 11 | 6 | 9 |
| u_snn.coord_mul_q | 9 | 0 | 0 |
| group_idx_o | 9 | 6 | 2,268 |
| _000000_ | 7 | 3 | 4 |
| u_snn.ts_idx | 7 | 3 | 4 |
| pred_tstep_o | 7 | 0 | 0 |
| dec_t | 7 | 3 | 4 |
| spike_tstep_o | 7 | 3 | 4 |
| u_snn.u_plane_seq | 6 | 2 | 76 |
| u_snn.aer_shift_q | 4 | 0 | 0 |
| pred_o | 4 | 0 | 0 |
| top1_idx_o | 4 | 0 | 0 |
| bitrow_idx_o | 4 | 4 | 40 |
| state_o | 2 | 0 | 0 |
| u_snn.seq_done | 1 | 1 | 4 |
| weights_loaded_o | 1 | 0 | 0 |
| u_snn.thresh_shared_q | 1 | 0 | 0 |
| exit_en_q | 1 | 0 | 0 |
| exited_o | 1 | 0 | 0 |
| pred_valid_o | 1 | 0 | 0 |
| inf_done_o | 1 | 0 | 0 |
| dec_valid_o | 1 | 1 | 4 |
| spike_valid_o | 1 | 1 | 4 |
| u_snn.spikes_done | 1 | 0 | 0 |
| wl_ready_o | 1 | 0 | 0 |

## 3. (b) The analog side, carried forward from 1F and 1E (not re-derived)

|  | g = 4 (recommended) | g = 8 |
|---|---|---|
| sensing | 40 columns per pass, 4 passes | 20 columns per pass, 8 passes |
| read pulse T (+ 0.3 ns tail) | 1 ns | 2 ns |
| supply decoupling | 1 nF (droop 7.1 mV) | 1 nF (droop 8.0 mV) |
| energy per non-zero group read, total | 185.8 pJ | 227.6 pJ |
|   array + word line | 4.5 pJ | 11.8 pJ |
|   sense bias | 82.3 pJ | 105.4 pJ |
|   comparators | 29.8 pJ | 36.5 pJ |
|   threshold correction (digital) | 69.2 pJ | 73.9 pJ |
| non-zero reads per inference, full run (1F / measured on the RTL here) | 28,476 / 28,476 | 20,420 / 20,420 |
| energy per inference, full run, SNN array only (1F) | 5.29 uJ | 4.65 uJ |
| idle bias if an empty read were issued | 78 pJ | 96 pJ |

The RTL's measured read counts reproduce 1F's: 53,590 reads of which 20,420 non-zero at g = 8 (1F/1E: 53,590 / 20,420), and they depend only on the input events, not on the model. Array area with the real sense periphery (1F, mid, 1 nF decoupling): 0.429 mm^2 (low 0.288, high 0.645); without decoupling 0.229. The g surface (1F section 8): g = 4 for sigma_lnG <= 0.15; g = 8 only for sigma_lnG <= 0.07; g = 16 only with segmented columns at <= 0.045.

## 4. (c) Energy per inference at the measured exit timestep

Per inference, mean over the 240 test samples x 3 seeds, of the sample's own energy: crossbar reads = non-zero group reads actually issued up to the sample's exit x energy per read; digital = digital power x cycles/100 MHz (cycles up to the exit, including the 1F multi-pass sensing); class-HV arrays = reads of the 10 columns per timestep up to the exit.

| g | run | mean exit timestep | events ingested | non-zero reads | cycles | crossbar reads (uJ) | digital (uJ) | class-HV arrays (uJ) | total (uJ) |
|---|---|---|---|---|---|---|---|---|---|
| 4 | full design | 57.6 | 57.6% | 16,748 | 486,963 | 3.111 | 16.118 | 0.0005 | **19.230** |
| 4 | same network, run to the end | 100.0 | 100.0% | 28,476 | 838,141 | 5.290 | 27.742 | 0.0008 | **33.033** |
| 8 | full design | 57.6 | 57.6% | 11,985 | 486,963 | 2.728 | 16.118 | 0.0007 | **18.847** |
| 8 | same network, run to the end | 100.0 | 100.0% | 20,420 | 838,141 | 4.648 | 27.742 | 0.0012 | **32.391** |

- g = 4: early exit saves 13.803 uJ (41.8%): crossbar reads 2.179, digital 11.624, class-HV arrays 0.0004 uJ. Energy at the *mean exit timestep* of the read profile instead of the mean of per-sample energies: crossbar 3.066 uJ (against 3.111 - they agree because the per-timestep read profile is flat).
- g = 8: early exit saves 13.544 uJ (41.8%): crossbar reads 1.920, digital 11.624, class-HV arrays 0.0005 uJ. Energy at the *mean exit timestep* of the read profile instead of the mean of per-sample energies: crossbar 2.689 uJ (against 2.728 - they agree because the per-timestep read profile is flat).

### 4.1 Where the crossbar part comes from (full design, g = 4)

| component | uJ at the exit | uJ, run to the end |
|---|---|---|
| array and wordline | 0.075 | 0.128 |
| sense bias | 1.378 | 2.343 |
| comparators | 0.500 | 0.849 |
| threshold correction | 1.158 | 1.970 |
| total | 3.111 | 5.290 |

### 4.2 Sensitivities

- **a = 0 reads issued.** The RTL issues 78,703 empty reads per inference (g = 4); if each paid the front-end's idle bias (78 pJ) the full design would add 3.52 uJ at the exit (22.75 uJ total). Skipping them is the 1E follow-up 1F recorded; not implemented here (non-goal).
- **HDC array model.** The class-HV arrays are 0.1 % of the energy under the stated per-column costs; they would stay below 1 % even at 10x.

### 4.3 The digital term, and what clock gating could change

Three readings of the same measurements (g = 4, mean of 3 seeds x 240 samples; the crossbar and class-HV terms are identical in all three):

| build | cycles: as built / with a = 0 skip | (1) as built (uJ) | (2) + a = 0 skip, 1F's cycle model (uJ) | (3) + ideal clock gating, bound (uJ) | (2)+(3) (uJ) |
|---|---|---|---|---|---|
| full design (exit) | 486,963 / 307,466 | 19.23 | 13.29 | 5.01 | 4.31 |
| early exit OFF (run to the end) | 838,141 / 523,329 | 33.03 | 22.61 | 8.55 | 7.33 |
| factorization OFF (exit) | 511,181 / 321,699 | 18.71 | 12.99 | 5.26 | 4.52 |
| both OFF | 838,141 / 523,329 | 30.53 | 21.06 | 8.48 | 7.29 |

(1) is the RTL as it stands: ungated clocks, and the sequencer walks every group read, empty ones too, once per sensing pass (the analog side is assumed to power the front end only for non-zero reads). (2) removes the empty reads from the cycle count (1E/1F's recorded follow-up; not implemented). (3) is a *bound*: the sequential power scaled by the measured flip-flop activity (0.0031 Q transitions per flop per cycle, section 2) - an implementation with ideal clock gating; real gating cells, enable timing and the clock tree would eat part of it. The digital term is 84% of (1); the crossbar reads are 16%. **The largest lever left is digital clocking, not the reads.** With (2)+(3) the full design would be 4.31 uJ, 1.43x NeuroHDC-small.

### 4.4 Cycle model check

1E's sequencer senses 160 or 20 columns per read; 1F's recommended 40 columns per pass is modelled as `cycles_160col + 7 x group_reads_allcols (g = 4, 8 passes of 20 columns)`. Validated on the RTL's own 20-column run of the same 24 samples and threshold: worst error 0 cycles (mean 0.00) on 618,462 cycles per inference. (1E measured the same identity at g = 8: 837,745 against 462,617 + 7 x 53,590.)

## 5. (d) Comparison with NeuroHDC-small

|  | NeuroHDC-small (as published) | this design, full, g = 4 | this design, full, g = 8 | ratio (g = 4) |
|---|---|---|---|---|
| technology / clock | 45 nm, 100 MHz | 45 nm library, 100 MHz | 45 nm library, 100 MHz | - |
| area (mm^2) | 0.399 | 0.671 | 0.671 | 1.68x |
| energy per inference (uJ), DVS-Gesture | 3.01 | 19.23 | 18.85 | 6.39x |
| accuracy | 87.5 % (paper) / 82.36 % (our reimplementation, 3 seeds) | 80.42% | 80.42% | - |

Area of this design, g = 4: digital 0.235 + SNN crossbar with sense periphery and 1 nF decoupling 0.429 + class-HV array 0.0074 = **0.671 mm^2**. The exclusions of section 1 apply to both sides unequally: NeuroHDC's numbers are a post-layout whole accelerator with its clock tree; ours are pre-layout and omit the clock tree, place-and-route overhead, the regulator, calibration and the host interface. Our crossbar numbers are simulated circuits with assumed mismatch (1F), not silicon.

## 6. (e) The ablation table (the paper's result table)

Recommended point g = 4 (40 columns per pass, T = 1 ns); last column: total energy at g = 8 (20 columns per pass, T = 2 ns).

| build | class HV | exit | accuracy | mean exit timestep | non-zero reads | cycles | crossbar (uJ) | digital (uJ) | class-HV arrays (uJ) | total energy (uJ) | digital (mm^2) | class-HV array (mm^2) | total area (mm^2) | energy at g = 8 (uJ) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| full design | R=1 factorized | margin exit | 80.42% | 57.6 | 16,748 | 486,963 | 3.11 | 16.12 | 0.000 | **19.23** | 0.235 | 0.0074 | 0.671 | 18.85 |
| early exit OFF | R=1 factorized | off | 80.42% | 100.0 | 28,476 | 838,141 | 5.29 | 27.74 | 0.001 | **33.03** | 0.237 | 0.0074 | 0.673 | 32.39 |
| factorization OFF | unfactorized | margin exit | 82.36% | 60.7 | 17,555 | 511,181 | 3.26 | 15.44 | 0.009 | **18.71** | 0.226 | 0.1149 | 0.770 | 18.31 |
| both OFF | unfactorized | off | 82.36% | 100.0 | 28,476 | 838,141 | 5.29 | 25.23 | 0.014 | **30.53** | 0.228 | 0.1149 | 0.772 | 29.89 |

What each contribution is worth (all separately attributable):

- **Early exit**, same network: 13.80 uJ (42%) on the R=1 model, 11.82 uJ (39%) on the baseline; accuracy 0.00% / 0.00% (points) relative to running to the end.
- **Factorized class hypervector**, with early exit on: accuracy -1.94% (points; a different, jointly trained network), energy +0.523 uJ (digital +0.681, class-HV arrays -0.0082, crossbar -0.150 uJ - the last is the exit timestep of the two networks, not the mapping), area -0.099 mm^2 (digital +0.0089, class-HV array -0.1075). The factorization buys the class-HV *array* (16 macros -> 1, about 0.11 mm^2 in the model) at the price of 1,050 digital flip-flops for the sign table and bias registers - which, ungated, cost 1.41 uJ per inference in clock energy: the sign table belongs in a small memory or behind a clock gate, not in free-running flip-flops.

## 7. Recommended operating point

| parameter | value | why |
|---|---|---|
| g (rows per group) | 4 | 1F: g = 8 closes only for sigma_lnG <= 0.07; g = 4 closes through 0.15 (the honest design point) |
| columns per pass | 40 (4 passes) | 1F section 5: 69 mA for 160 columns is not deliverable; 40 columns at g = 4 peak at 8.7 mA with 1 nF |
| read pulse | T = 1 ns + 0.3 ns tail | 1F: set by noise + calibration residual |
| exit threshold (XNOR margin units) | 50 (R=1 model); 56 (unfactorized baseline) | strict knee: accuracy equals the full run's and stays so for every larger threshold; software bipolar threshold = 2x |
| class hypervector | R=1 factorized | 16 macros -> 1, 20,000 -> 1,250 bits; costs 2.0 points of accuracy at training time (80.4 % vs 82.4 %) |
| clock | 100 MHz | closes with 8 ns of slack in the slow corner; the design is input-bound, so a higher clock only raises power |

## 8. Assumptions and open items (updated TO BE DETERMINED list)

- **Digital power is as designed (ungated) and window-sampled.** One sample, 8,000 cycles (timesteps ~3-5), the same window for all builds; ingest and MVM phases are both inside it but a different window or sample would move the combinational part (~0.4 mW) by tens of percent; the sequential part is activity-independent. No clock tree, so the real clock power is higher; no clock gating, so a real design with it is lower (4.3).
- **Class-HV array energy and area are scaled models** ([ASSUM]); the arrays were never designed (10 columns, 20 or 2,000 rows, sensing of 0..20 counts for the factorized one, bit-wise reads for the unfactorized one).
- **a = 0 reads** are assumed free and are not skipped in the RTL (non-goal); 1G.
- **40 columns per pass** is not an RTL option (1E's sequencer has 160 or 20); the cycle count adds one cycle per extra pass per read, a model validated on the 20-column RTL run.
- **The 1F energy model** (sense bias, comparators, threshold correction at Horowitz op energies) is carried forward unchanged, with its own open items (comparator latch noise, threshold generator, calibration energy).
- **No NeuroSim cross-check** (optional; not done). **No place-and-route**, so no utilisation, wire load, clock tree, or post-layout timing.
- **Timing at two corners of one library only**; the library is the FFT project's lab 45 nm card, not a foundry-qualified PDK.
- **The OpenSTA binary** was built from source (version 3.1.0, Tcl 8.6, CUDD); it is not in the repository (`design/rtl/tools/` is ignored) - the build recipe is in section 9.
- The accuracy column is on the 240 DVS-Gesture test samples with thresholds chosen on them (phase234_report.md, open items).

## 9. Reproduce

```
# OpenSTA (not in Homebrew): brew install cmake swig bison flex eigen tcl-tk@8 ; build CUDD (github.com/ivmai/cudd) ; git clone github.com/The-OpenROAD-Project/OpenSTA ;
#   cmake -DBUILD_TESTS=OFF -DCUDD_DIR=<cudd> -DTCL_LIBRARY=<tcl-tk@8>/lib/libtcl8.6.dylib -DTCL_HEADER=<tcl-tk@8>/include/tcl-tk/tcl.h -DFLEX_INCLUDE_DIR=<flex>/include ... ; make ; cp sta design/rtl/tools/sta
venv/bin/python design/rtl/scripts/synth_ppa.py [--hier]      # area and timing, 4 builds x 3 mapping/corner variants
venv/bin/python design/rtl/scripts/synth_power.py              # gate-level activity and power, 4 builds (~10 min each)
venv/bin/python design/rtl/scripts/phase5_ppa.py && venv/bin/python design/rtl/scripts/make_report_ppa.py
```
